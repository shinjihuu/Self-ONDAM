"""가족 재무상태 분석 (AFPK 3단계) — 원자료(만 원)에서 재무비율을 직접 계산."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Ratio:
    group: str
    name: str
    value: float          # %, 또는 배수
    unit: str             # "%" | "배"
    guide: str
    age_guide: str
    ok: bool | None       # 연령대 기준 충족 여부 (None = 평가 없음)
    formula: str


def _sum(d: dict) -> float:
    return float(sum(d.values()))


def analyze(h: dict) -> dict:
    a = h["assets"]
    cash, sav, use = _sum(a["cash"]), _sum(a["savings"]), _sum(a["use"])
    total_assets = cash + sav + use
    total_debt = _sum(h["debts"])
    net_worth = total_assets - total_debt
    income = _sum(h["income"])
    fixed, var = _sum(h["fixed"]), _sum(h["variable"])
    spend = fixed + var
    saving = _sum(h["saving_flows"])
    non_cons = sum(h["fixed"][k] for k in h["non_consumption_keys"])
    loan_rep = sum(h["fixed"][k] for k in h["loan_repayment_keys"])
    consumption = spend - non_cons - loan_rep
    disposable = income - non_cons - h["loan_interest_assumed"]
    insurance = sum(h["fixed"][k] for k in h["insurance_keys"])
    monthly_spend = spend / 12
    house = h["assets"]["use"].get("거주아파트", 0)
    mortgage = h["debts"].get("주택담보대출", 0)
    mortgage_rep = h["fixed"].get("주택담보대출 원리금", 0)
    consumer_rep = h["fixed"].get("자동차 할부금 원리금", 0)
    main_income = max(h["income"].values())
    fin_assets = cash + sav

    def pct(x, y):
        return x / y * 100 if y else 0.0

    ratios = [
        Ratio("가계수지", "가계수지지표", pct(spend, income), "%", "70% 이하", "50대: 90% 이하",
              pct(spend, income) <= 90, f"(고정 {fixed:,.0f} + 변동 {var:,.0f}) ÷ 총소득 {income:,.0f}"),
        Ratio("소비성향", "평균소비성향(추정)", pct(consumption, disposable), "%", "-", "전국 평균 69.2% (2026.2Q)",
              None, f"소비지출 {consumption:,.0f} ÷ 가처분소득 {disposable:,.2f}"),
        Ratio("비상예비자금", "비상예비자금지표", cash / monthly_spend, "배", "2~6배", "50대: 5배 이상",
              cash / monthly_spend >= 5, f"보통예금 {cash:,.0f} ÷ 월지출 {monthly_spend:,.1f}"),
        Ratio("부채적정성", "총부채상환지표", pct(loan_rep, income), "%", "30% 이하", "65세 이상: 0%",
              pct(loan_rep, income) <= 30, f"총부채상환 {loan_rep:,.0f} ÷ {income:,.0f}"),
        Ratio("부채적정성", "소비생활부채상환지표", pct(consumer_rep, income), "%", "10% 이하", "40~50대: 10% 이하",
              pct(consumer_rep, income) <= 10, f"{consumer_rep:,.0f} ÷ {income:,.0f}"),
        Ratio("부채적정성", "거주주택마련부채상환지표", pct(mortgage_rep, income), "%", "20% 이하", "-",
              pct(mortgage_rep, income) <= 20, f"{mortgage_rep:,.0f} ÷ {income:,.0f}"),
        Ratio("부채적정성", "총부채부담지표", pct(total_debt, total_assets), "%", "40% 이하", "-",
              pct(total_debt, total_assets) <= 40, f"{total_debt:,.0f} ÷ 총자산 {total_assets:,.0f}"),
        Ratio("부채적정성", "거주주택마련부채부담지표", pct(mortgage, total_assets), "%", "30% 이하", "-",
              pct(mortgage, total_assets) <= 30, f"{mortgage:,.0f} ÷ {total_assets:,.0f}"),
        Ratio("위험대비", "보장성보험준비지표", pct(insurance, income), "%", "8~10%", "-",
              8 <= pct(insurance, income) <= 10, f"보험료 {insurance:,.0f} ÷ {income:,.0f}"),
        Ratio("저축·투자", "총저축성향지표", pct(saving, income), "%", "30% 이상", "50대: 10% 이상",
              pct(saving, income) >= 10, f"저축 {saving:,.0f} ÷ {income:,.0f}"),
        Ratio("저축·투자", "금융투자성향지표", 0.0, "%", "30% 이상", "50대: 20% 이상",
              False, f"투자 0 ÷ 저축 {saving:,.0f}"),
        Ratio("저축·투자", "금융자산비중지표", pct(fin_assets, total_assets), "%", "40% 이상", "-",
              pct(fin_assets, total_assets) >= 40, f"금융자산 {fin_assets:,.0f} ÷ {total_assets:,.0f}"),
    ]
    return {
        "total_assets": total_assets, "total_debt": total_debt, "net_worth": net_worth,
        "income": income, "spend": spend, "saving": saving, "fixed": fixed, "variable": var,
        "monthly_spend": monthly_spend,
        "emergency_gap_5m": max(0.0, 5 * monthly_spend - cash),
        "income_dependence": pct(main_income, income),
        "house_concentration": pct(house, total_assets),
        "ratios": ratios,
    }


def fmt_ratio(r: Ratio) -> str:
    """소수 첫째 자리 반올림 (보고서 표기와 동일)."""
    return f"{r.value:.1f}{r.unit}"
