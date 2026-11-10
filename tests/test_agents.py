"""수집 에이전트 · 추천 에이전트 테스트 (샘플 API 응답 사용, 네트워크 없음)."""
import json
from pathlib import Path

from core import ai, eligibility as el
from core.agents import collector as col
from core.agents.recommender import RecommenderAgent, load_catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "bokjiro"
DAUGHTER = json.loads((ROOT / "data" / "personas.json").read_text(encoding="utf-8"))["personas"][0]["profile"]


def _collected():
    items, details = col.fetch_from_dir(FIX)
    return col.collect(items, details, use_llm=False)


def test_collector_filters_and_dedupes():
    res = _collected()
    names = [p["name"] for p in res["programs"]]
    assert "장애인연금" not in names                 # 수작업 정리 제도와 중복 → 제외
    assert "[샘플] 청년 문화패스" not in names       # 장애인 대상 아님 → 제외
    assert res["meta"]["kept"] == 4 and res["meta"]["skipped_duplicates"] == 1 and res["meta"]["skipped_off_target"] == 1
    assert all(p["source"]["verified"] is False for p in res["programs"])


def test_collector_classifies_financial_vs_nonfinancial():
    by = {p["source"]["serv_id"]: p for p in _collected()["programs"]}
    assert (by["S001"]["support_type"], by["S001"]["category"]) == ("cash", "재무적 지원")
    assert (by["S006"]["support_type"], by["S006"]["category"]) == ("finance", "재무적 지원")
    assert (by["S002"]["support_type"], by["S002"]["category"]) == ("care", "비재무적 지원")
    assert (by["S003"]["support_type"], by["S003"]["category"]) == ("employment", "비재무적 지원")


def test_extract_criteria_rules():
    c = col.extract_criteria("만 18세 ~ 64세 발달장애인, 장애인복지법에 따른 등록 장애인")
    assert c["min_age"] == 18 and c["max_age"] == 64
    assert c["disability_types"] == ["지적장애", "자폐성장애"] and c["registered"] == "required"
    assert col.extract_criteria("만 6세 이상 65세 미만")["max_age"] == 64
    assert col.extract_criteria("취업 중인 중증장애인 근로자") == {"severity": "심한 장애", "employment_required": ["취업 중"]}
    assert "severity" not in col.extract_criteria("중증 및 경증 장애인")


def test_llm_output_is_validated():
    raw = {"min_age": 18, "max_age": 200, "severity": "아무거나", "disability_types": ["지적장애", "외계인"],
           "employment_required": ["취업 중", "사장님"], "unknown_key": 1, "checks": ["소득 확인"]}
    assert col.validate_criteria(raw) == {"min_age": 18, "disability_types": ["지적장애"],
                                          "employment_required": ["취업 중"], "checks": ["소득 확인"]}


def test_llm_refine_used_when_valid(monkeypatch):
    monkeypatch.setattr(ai, "ai_available", lambda: True)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ('결과: {"min_age": 19, "registered": "required"}', "Hugging Face"))
    crit, prov = col.refine_with_llm("x", "만 19세 이상 등록 장애인", {"min_age": 18})
    assert crit == {"min_age": 19, "registered": "required"} and prov == "Hugging Face"
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ("JSON 아님", "Hugging Face"))
    assert col.refine_with_llm("x", "본문", {"min_age": 18}) == ({"min_age": 18}, None)


def test_catalog_merges_curated_first(tmp_path):
    out = tmp_path / "collected.json"
    out.write_text(json.dumps(_collected(), ensure_ascii=False), encoding="utf-8")
    progs, info = load_catalog(True, collected_path=out)
    assert info["curated"] == 5 and info["collected_used"] == 4 and len(progs) == 9
    progs2, info2 = load_catalog(False, collected_path=out)
    assert len(progs2) == 5 and info2["collected_used"] == 0


def test_unverified_never_priority(tmp_path):
    out = tmp_path / "collected.json"
    out.write_text(json.dumps(_collected(), ensure_ascii=False), encoding="utf-8")
    agent = RecommenderAgent(load_catalog(True, collected_path=out)[0])
    recs = {r.program_id: r for r in agent.recommend(DAUGHTER)}
    # S002: 18~64세 발달장애 → 조건은 모두 맞지만 검수 전이라 '추가 정보 필요'
    assert recs["bokjiro_S002"].status == el.MORE_INFO and el.UNVERIFIED_NOTE in recs["bokjiro_S002"].checks
    assert recs["bokjiro_S006"].status == el.NO_MATCH            # 취업 중이어야 함
    assert recs["disability_pension"].status == el.PRIORITY      # 수작업 제도는 그대로
    order = [r.program_id for r in agent.recommend(DAUGHTER)]
    assert order.index("disability_pension") < order.index("bokjiro_S002")


def test_recommender_answer_uses_relevant_programs(monkeypatch):
    agent, _ = RecommenderAgent.from_files(include_collected=False)
    assert agent.relevant("근로지원인은 언제 신청해요?", 2)[0]["id"] == "work_assistant"
    seen = {}
    monkeypatch.setattr(ai, "answer_question", lambda q, p, progs: (seen.setdefault("n", [x["id"] for x in progs]), False))
    agent.answer("장애인연금 신청", DAUGHTER, top_k=3)
    assert seen["n"][0] == "disability_pension" and len(seen["n"]) == 3
