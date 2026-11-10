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
