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
    assert info["curated"] == 6 and info["collected_used"] == 4 and len(progs) == 10
    progs2, info2 = load_catalog(False, collected_path=out)
    assert len(progs2) == 6 and info2["collected_used"] == 0


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
    def fake(q, p, progs, summary):
        seen["n"] = [x["id"] for x in progs]
        seen["s"] = summary
        return "", False
    monkeypatch.setattr(ai, "answer_question", fake)
    agent.answer("장애인연금 신청", DAUGHTER, top_k=3)
    assert seen["n"][0] == "disability_pension" and len(seen["n"]) == 3
    pen = next(x for x in seen["s"] if x["제도"] == "장애인연금")
    assert pen["월 예상 지원액"] == 379_700            # 이 사용자의 계산 결과가 AI 근거로 전달됨


def test_knowledge_retrieval_for_inheritance():
    hits = [it["topic"] for it in ai.relevant_knowledge("발달장애인 자녀 상속은 어떻게 이뤄져?")]
    assert any("상속공제" in h for h in hits) and any("신탁" in h for h in hits)
    text = ai._fallback_answer("발달장애인 자녀 상속은 어떻게 이뤄져?", [])
    assert "상속" in text and "☎" in text


def test_api_403_is_diagnosed_and_key_masked(monkeypatch):
    import io
    import urllib.error
    import pytest

    def fake(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"Forbidden"))
    monkeypatch.setattr(col.urllib.request, "urlopen", fake)
    monkeypatch.setattr(col.time, "sleep", lambda s: None)
    with pytest.raises(col.ApiError) as e:
        col._get("https://apis.data.go.kr/x", {"serviceKey": "SECRET123"})
    assert "403" in str(e.value) and "SECRET123" not in str(e.value)


def test_api_error_inside_200_response(monkeypatch):
    import io
    import pytest

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    body = b"<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg></OpenAPI_ServiceResponse>"
    monkeypatch.setattr(col.urllib.request, "urlopen", lambda req, timeout=0: R(body))
    with pytest.raises(col.ApiError) as e:
        col._get("https://apis.data.go.kr/x", {"serviceKey": "k"})
    assert "동기화" in str(e.value)


def test_main_keeps_existing_file_on_api_failure(monkeypatch, tmp_path):
    out = tmp_path / "c.json"
    out.write_text("기존", encoding="utf-8")
    monkeypatch.setattr(col, "fetch_from_odcloud", lambda: (_ for _ in ()).throw(col.ApiError("403")))
    assert col.main(["--out", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "기존"


# ── 복지서비스정보(odcloud) 형식 ──
ODC = ROOT / "tests" / "fixtures" / "odcloud_sample.json"


def test_odcloud_column_mapping():
    cols = ["서비스아이디", "서비스명", "서비스목적요약", "소관부처명", "지원유형", "지원대상", "선정기준",
            "지원내용", "신청방법", "전화문의", "상세조회URL"]
    m = col.map_columns(cols)
    assert m["servNm"] == "서비스명" and m["servId"] == "서비스아이디" and m["servDgst"] == "서비스목적요약"
    assert m["tgtrDtlCn"] == "지원대상" and m["alwServCn"] == "지원내용" and m["servDtlLink"] == "상세조회URL"


def test_odcloud_file_collect():
    items, details, meta = col.fetch_from_odcloud_file(ODC)
    res = col.collect(items, details, use_llm=False, source=meta["source"], max_keep=10)
    names = [p["name"] for p in res["programs"]]
    assert names == ["[샘플] 장애인 자립수당", "[샘플] 발달장애인 낮활동 바우처"]   # 연금(중복)·청년(대상 아님) 제외
    p = res["programs"][0]
    assert p["support_type"] == "cash" and p["criteria"]["min_age"] == 18
    assert p["apply"].startswith("주소지") and p["source"]["name"] == col.ODCLOUD_SOURCE


def test_odcloud_paging(monkeypatch):
    import json as _j
    rows = [{"서비스아이디": f"S{i}", "서비스명": f"[샘플] 장애인 서비스 {i}", "지원대상": "등록 장애인"} for i in range(1500)]
    calls = []

    def fake_get(url, params, retries=3):
        calls.append(params.get("page"))
        p, n = params["page"], params["perPage"]
        return _j.dumps({"totalCount": 1500, "data": rows[(p - 1) * n:p * n]}, ensure_ascii=False)
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    monkeypatch.setenv("ODCLOUD_UDDI", "uddi:test")
    monkeypatch.setattr(col, "_get", fake_get)
    items, details, meta = col.fetch_from_odcloud()
    assert len(items) == 1500 and calls == [1, 2] and meta["snapshot"] == "uddi:test"


def test_real_snapshot_names_filtered_and_classified():
    """2026-11 실제 수집에서 확인된 제도명으로 선별·분류 규칙을 검증."""
    keep = lambda n: col.is_disability_target({"servNm": n, "servDgst": "장애 관련"}, {})
    for n in ("실종아동 등 보호 및 지원", "선천성대사이상 검사 및 환아관리", "고엽제환자2세수당",
              "노숙자 등 알코올중독자 사례관리 사업", "산재근로자직업훈련"):
        assert not keep(n), n
    for n in ("장애인일자리지원", "발달장애인 공공후견지원 사업", "척수장애인재활훈련지원"):
        assert keep(n), n
    cls = lambda n: col.classify({"servNm": n}, {})
    assert cls("장애인자립자금대여") == "finance"
    assert cls("의료급여 장애인보조기기 지원") == "care"
    assert cls("장애인일자리지원") == "employment"


def test_child_programs_get_age_cap():
    p = col.normalize({"servId": "X", "servNm": "장애아보육료지원", "servDgst": "장애아동 보육료"}, {}, "t", False)
    assert p["criteria"]["max_age"] == 18
    r = el.evaluate(p, DAUGHTER)
    assert r.status == el.NO_MATCH          # 24세 딸에게는 '맞지 않음'
