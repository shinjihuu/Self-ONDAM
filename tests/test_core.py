import json
from pathlib import Path

import pytest

from core import eligibility as el, finance as fin, household as hh

DATA = Path(__file__).resolve().parents[1] / "data"
PERSONAS = {p["id"]: p for p in json.loads((DATA / "personas.json").read_text(encoding="utf-8"))["personas"]}


# ── 기획서 예시: 월 소득 120 · 지출 100 · 가상 지원 35만 원 ──
def test_plan_example_cashflow():
    df = fin.project_cashflow(2026, 11, 12, 1_200_000, 1_000_000,
                              [fin.SupportItem("가상", "cash", 350_000)])
    assert df["before_surplus"].iloc[0] == 200_000
    assert df["after_surplus"].iloc[0] == 550_000
    assert df["after_surplus"].sum() - df["before_surplus"].sum() == 4_200_000  # +420만 원


def test_care_service_is_not_income():
    """돌봄 서비스는 수입이 아니라 지출 감소로만 반영된다."""
    df = fin.project_cashflow(2026, 11, 3, 1_000_000, 800_000,
                              [fin.SupportItem("활동지원", "expense", 100_000)])
    assert (df["after_income"] == 1_000_000).all()
    assert (df["after_expense"] == 700_000).all()


def test_support_timing_and_duration():
    df = fin.project_cashflow(2026, 11, 12, 0, 0, [fin.SupportItem("x", "cash", 100, start_offset=2, duration=3)])
    assert df["cash_support"].tolist() == [0, 0, 100, 100, 100] + [0] * 7
    assert df["label"].iloc[2] == "2027.01"


def test_job_assumption_ends_training_cost():
    df = fin.project_cashflow(2026, 11, 12, 379_000, 374_000, job=fin.JobAssumption(10, 1_200_000, 150_000, 150_000))
    assert df["job_surplus"].iloc[9] == 5_000
    assert df["job_surplus"].iloc[10] == 5_000 + 1_200_000
    assert (df["after_surplus"] == 5_000).all()  # 취업은 '지원 효과'에 섞이지 않음


# ── 예금·적금 ──
def test_installment_simple_interest():
    r = fin.installment_saving(100_000, 12, 0.03)
    assert r.principal == 1_200_000
    assert r.gross_interest == 19_500           # 100,000 × 0.0025 × 78
    assert r.tax == 3_000                       # 19,500 × 15.4% = 3,003 → 10원 절사
    assert r.maturity == 1_200_000 + 16_500


def test_tax_free_and_limit():
    assert fin.installment_saving(100_000, 12, 0.03, tax_free=True).tax == 0
    r = fin.time_deposit(100_000_000, 12, 0.03, tax_free=True)  # 한도 5,000만 원 초과분만 과세
    assert r.gross_interest == 3_000_000
    assert r.tax == fin._floor10(1_500_000 * 0.154)


def test_deposit_does_not_create_wealth():
    """원금은 이동일 뿐, 순자산 증가는 이자뿐."""
    r = fin.time_deposit(5_000_000, 12, 0.0)
    assert r.maturity == r.principal == 5_000_000


def test_goal_projection_and_required():
    gp = fin.goal_projection(0, 100_000, 12, 0.0)
    assert gp.iloc[-1]["balance"] == 1_200_000
    need = fin.required_monthly(12_000_000, 0, 120, 0.0)
    assert need == 100_000
    m = fin.required_monthly(30_000_000, 0, 120, 0.03)
    assert fin.goal_projection(0, m, 120, 0.03).iloc[-1]["balance"] == pytest.approx(30_000_000, rel=0.002)


# ── 가족 재무비율: 보고서 수치 재현 ──
@pytest.mark.parametrize("name,expected", [
    ("가계수지지표", "85.9%"), ("평균소비성향(추정)", "69.6%"), ("비상예비자금지표", "4.5배"),
    ("총부채상환지표", "15.7%"), ("소비생활부채상환지표", "6.7%"), ("거주주택마련부채상환지표", "9.0%"),
    ("총부채부담지표", "16.0%"), ("거주주택마련부채부담지표", "14.5%"), ("보장성보험준비지표", "7.9%"),
    ("총저축성향지표", "14.1%"), ("금융투자성향지표", "0.0%"), ("금융자산비중지표", "14.5%"),
])
def test_household_ratios_match_report(name, expected):
    res = hh.analyze(PERSONAS["afpk_daughter"]["household"])
    r = next(x for x in res["ratios"] if x.name == name)
    assert hh.fmt_ratio(r) == expected


def test_household_totals():
    res = hh.analyze(PERSONAS["afpk_daughter"]["household"])
    assert res["total_assets"] == 55_000 and res["total_debt"] == 8_800 and res["net_worth"] == 46_200
    assert res["fixed"] == 3_231 and res["variable"] == 2_132 and res["income"] == 6_243
    assert round(res["income_dependence"], 1) == 92.7
    assert round(res["house_concentration"], 1) == 81.8
    assert round(res["emergency_gap_5m"]) == 235


# ── 추천 규칙 ──
def test_afpk_daughter_recommendations():
    p = PERSONAS["afpk_daughter"]["profile"]
    st = {r.program_id: r for r in el.recommend(p)}
    assert st["disability_pension"].status == el.PRIORITY and st["disability_pension"].in_use
    assert st["day_activity"].status == el.PRIORITY
    assert st["kead_employment"].status == el.PRIORITY
    assert st["work_assistant"].status == el.NO_MATCH and st["work_assistant"].future


def test_day_activity_restricted_when_employed():
    p = dict(PERSONAS["afpk_daughter"]["profile"], employment="취업 중")
    r = next(x for x in el.recommend(p) if x.program_id == "day_activity")
    assert r.status == el.MORE_INFO
    assert next(x for x in el.recommend(p) if x.program_id == "work_assistant").status == el.PRIORITY


def test_profile_totals_consistent():
    for pr in PERSONAS.values():
        p = pr["profile"]
        assert p["monthly_income"] == sum(i["amount"] for i in p["income_items"])
        assert p["monthly_expense"] == sum(i["amount"] for i in p["expense_items"])


# ── AI 공급자 순서: OpenAI → Gemini → Groq → Hugging Face → 규칙 기반 ──
from core import ai

ALL_KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL",
            "GROQ_API_KEY", "GROQ_MODEL", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "HF_MODEL")


@pytest.fixture(autouse=False)
def clean_ai(monkeypatch):
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ai, "_WORKING", {})
    monkeypatch.setattr(ai, "_BAD", set())
    monkeypatch.setattr(ai, "_DISABLED", {})
    return monkeypatch


class _Err(Exception):
    def __init__(self, status, msg=""):
        super().__init__(msg or f"HTTP {status}")
        self.status_code = status


def test_provider_order(clean_ai):
    mp = clean_ai
    assert ai.providers() == [] and not ai.ai_available()
    mp.setenv("HF_TOKEN", "hf_x")
    ps = ai.providers()
    assert [p["name"] for p in ps] == ["Hugging Face"]
    assert ps[0]["base_url"] == ai.HF_BASE_URL and ps[0]["model"] == ai.DEFAULT_HF_MODEL
    mp.setenv("GROQ_API_KEY", "g")
    mp.setenv("GEMINI_API_KEY", "m")
    mp.setenv("OPENAI_API_KEY", "sk-x")
    assert [p["name"] for p in ai.providers()] == ["OpenAI", "Gemini", "Groq", "Hugging Face"]
    mp.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    assert next(p for p in ai.providers() if p["name"] == "Groq")["models"] == ["llama-3.1-8b-instant"]


def test_fallback_to_next_service(clean_ai):
    mp = clean_ai
    mp.setenv("OPENAI_API_KEY", "sk-x")
    mp.setenv("HF_TOKEN", "hf_x")
    calls = []

    def fake_call(p, prompt, max_tokens, **kw):
        calls.append(p["name"])
        if p["name"] == "OpenAI":
            raise _Err(429, "quota")
        return "허깅페이스 답변이에요."
    mp.setattr(ai, "_call", fake_call)
    text, by = ai.answer_question("장애인연금은?", {}, [])
    assert calls == ["OpenAI", "Hugging Face"]
    assert text == "허깅페이스 답변이에요." and by == "Hugging Face"


def test_rule_fallback_when_all_fail(clean_ai):
    mp = clean_ai
    mp.setenv("HF_TOKEN", "hf_x")
    mp.setattr(ai, "_call", lambda *a, **k: (_ for _ in ()).throw(_Err(500, "down")))
    progs = json.loads((DATA / "programs.json").read_text(encoding="utf-8"))["programs"]
    text, by = ai.answer_question("장애인연금 신청은 어디서 해요?", {}, progs)
    assert by is False and "장애인연금" in text


def test_unsupported_model_tries_next_and_remembers(clean_ai):
    mp = clean_ai
    mp.setenv("GROQ_API_KEY", "g")
    tried = []

    def fake_call(p, *a, **k):
        tried.append(p["model"])
        if p["model"] == "openai/gpt-oss-20b":
            raise _Err(400, "model_not_supported")
        return "답변"
    mp.setattr(ai, "_call", fake_call)
    assert ai._chat("q") == "답변"
    assert tried == ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]
    assert ai.providers()[0]["models"][0] == "llama-3.1-8b-instant"


def test_no_credit_disables_service_but_others_continue(clean_ai):
    """HF 402(크레딧 없음)는 HF만 끄고, 다른 모델을 헛되이 시도하지 않는다."""
    mp = clean_ai
    mp.setenv("GROQ_API_KEY", "g")
    mp.setenv("HF_TOKEN", "hf_x")
    tried = []

    def fake_call(p, *a, **k):
        tried.append(p["name"])
        if p["name"] == "Groq":
            raise _Err(429, "rate limit")
        raise _Err(402, "Purchase pre-paid credits")
    mp.setattr(ai, "_call", fake_call)
    assert ai._chat("q") is None
    assert tried == ["Groq", "Hugging Face"]               # HF는 모델 하나만 시도
    assert [p["name"] for p in ai.providers()] == ["Groq"]  # HF는 이번 실행에서 제외
    assert "credits" in ai._DISABLED["Hugging Face"]


# ── 2026년 금액 계산 ──
from core import benefits as bf


def _p(**kw):
    base = dict(registered=True, severity="심한 장애", age=24, region="인천광역시", income_items=[],
                savings=0, property_general=0, debt=0, income_level="일반 (차상위 초과)", has_spouse=False)
    base.update(kw)
    return base


def test_pension_2026_amounts_by_income_level():
    assert bf.pension_estimate(_p()).monthly == 349_700 + 30_000
    assert bf.pension_estimate(_p(income_level="차상위계층")).monthly == 349_700 + 80_000
    assert bf.pension_estimate(_p(income_level="생계·의료급여 수급자")).monthly == 349_700 + 90_000   # 최대 439,700원


def test_pension_earned_income_deduction():
    # 근로 120만 원 → (120만 − 95만) × 0.7 = 17.5만 원
    p = _p(income_items=[{"name": "급여", "amount": 1_200_000, "kind": "근로소득"}])
    ri, _ = bf.recognized_income(p)
    assert ri == 175_000
    assert bf.pension_estimate(p).monthly == 379_700


def test_pension_reduction_and_cutoff():
    # 근로 260만 원 → (260 − 95) × 0.7 = 115.5만 → 기초급여 = 140만 − 115.5만 = 24.5만
    p = _p(income_items=[{"name": "급여", "amount": 2_600_000, "kind": "근로소득"}])
    e = bf.pension_estimate(p)
    assert e.eligible and e.breakdown[0][1] == 245_000 and e.monthly == 275_000
    # 근로 300만 원 → 143.5만 > 140만 → 대상 아님
    assert bf.pension_estimate(_p(income_items=[{"name": "급여", "amount": 3_000_000, "kind": "근로소득"}])).eligible is False


def test_pension_property_and_parents_not_counted():
    # 금융재산 3,000만 원 → (3,000 − 2,000)만 × 4% ÷ 12 = 33,333원
    ri, _ = bf.recognized_income(_p(savings=30_000_000))
    assert ri == 33_333
    # 장애인연금 자체는 소득으로 보지 않음
    ri2, _ = bf.recognized_income(_p(income_items=[{"name": "장애인연금 (수급 중)", "amount": 379_700}]))
    assert ri2 == 0


def test_pension_not_for_mild_and_allowance_instead():
    mild = _p(severity="심하지 않은 장애", income_level="차상위계층")
    assert bf.pension_estimate(mild).eligible is False
    assert bf.allowance_estimate(mild).monthly == 60_000
    assert bf.allowance_estimate(_p(severity="심하지 않은 장애")).eligible is False      # 일반 소득은 대상 아님


def test_activity_copay_rules():
    assert bf.activity_copay(_p(income_level="생계·의료급여 수급자"), 2_000_000).monthly == 0
    assert bf.activity_copay(_p(income_level="차상위계층"), 2_000_000).monthly == 20_000
    assert bf.activity_copay(_p(median_band="중위소득 70~120%"), 2_070_000).monthly == 124_200   # 보고서 연 149만 원
    assert bf.activity_copay(_p(median_band="중위소득 180% 초과"), 5_000_000).monthly == 216_200  # 상한


def test_afpk_pension_matches_report():
    """보고서 현금흐름표 장애인연금 연 455만 원 ≈ 2026 기준 월 379,700원 × 12."""
    p = PERSONAS["afpk_daughter"]["profile"]
    e = bf.pension_estimate(p)
    assert e.monthly == 379_700 and abs(e.monthly * 12 - 4_550_000) < 10_000
