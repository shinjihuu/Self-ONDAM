"""재무 계산 모듈 — 현금흐름·예금·적금·목표 시뮬레이션.

설계 원칙
1. 현금지원(cash)만 수입에 더한다. 돌봄·활동지원은 '실제로 줄어든 본인 비용'만 지출 감소로 반영한다.
2. 취업지원은 수입이 아니다. 취업 후 급여는 별도 가정(JobAssumption)으로 반영한다.
3. 예·적금 납입은 자산의 '이동'이다. 순자산을 새로 늘리는 것은 이자뿐이다.
4. 매월 생기는 잉여자금은 적금, 이미 가진 목돈은 예금으로 계산한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

INTEREST_TAX_RATE = 0.154          # 이자소득세 14% + 지방소득세 1.4%
TAX_FREE_LIMIT = 50_000_000        # 비과세종합저축 1인당 원금 한도


# ─────────────────────────── 현금흐름 ───────────────────────────
@dataclass
class SupportItem:
    """시뮬레이션에 반영할 지원 1건."""
    name: str
    kind: str                 # "cash" = 수입 증가, "expense" = 지출 감소
    amount: int               # 월 금액(원)
    start_offset: int = 0     # 시뮬레이션 시작 후 몇 개월째부터 (0 = 첫 달)
    duration: Optional[int] = None  # 지급 개월 수 (None = 기간 끝까지 계속 지급 가정)
    confirmed: bool = False   # 수급 확정 여부 (False = 가정 시나리오)

    def active(self, m: int) -> bool:
        if m < self.start_offset:
            return False
        return self.duration is None or m < self.start_offset + self.duration


@dataclass
class JobAssumption:
    """취업 가정 — 지원제도 효과가 아니라 별도 가정값."""
    start_offset: int         # 시뮬레이션 시작 후 몇 개월째 취업
    salary: int               # 월 실수령 예상 급여
    extra_expense: int = 0    # 취업으로 늘어나는 지출 (교통비·식비 등)
    ended_expense: int = 0    # 취업하면 끝나는 지출 (예: 직업훈련비)
    benefit_change: int = 0   # 취업으로 소득인정액이 바뀌어 달라지는 현금 지원 (예: 장애인연금 감액은 음수)


def _month_label(start_year: int, start_month: int, offset: int) -> tuple[int, int]:
    total = (start_month - 1) + offset
    return start_year + total // 12, total % 12 + 1


def project_cashflow(
    start_year: int,
    start_month: int,
    months: int,
    base_income: int,
    base_expense: int,
    supports: list[SupportItem] | None = None,
    job: JobAssumption | None = None,
) -> pd.DataFrame:
    """월별 현금흐름 표를 만든다.

    세 가지 시나리오:
      - before : 현재 상태 유지
      - after  : 선택한 지원 적용 (현금지원 → 수입, 돌봄비 절감 → 지출 감소)
      - job    : 지원 적용 + 취업 가정
    """
    supports = supports or []
    rows = []
    for m in range(months):
        y, mo = _month_label(start_year, start_month, m)
        cash = sum(s.amount for s in supports if s.kind == "cash" and s.active(m))
        saving = sum(s.amount for s in supports if s.kind == "expense" and s.active(m))
        saving = min(saving, base_expense)  # 지출보다 많이 줄어들 수는 없음

        before_in, before_out = base_income, base_expense
        after_in, after_out = base_income + cash, base_expense - saving

        job_in, job_out = after_in, after_out
        if job is not None and m >= job.start_offset:
            job_in += job.salary + job.benefit_change
            job_out += job.extra_expense - min(job.ended_expense, job_out)

        rows.append({
            "offset": m,
            "year": y,
            "month": mo,
            "label": f"{y}.{mo:02d}",
            "date": pd.Timestamp(year=y, month=mo, day=1),
            "before_income": before_in,
            "before_expense": before_out,
            "before_surplus": before_in - before_out,
            "cash_support": cash,
            "expense_saving": saving,
            "after_income": after_in,
            "after_expense": after_out,
            "after_surplus": after_in - after_out,
            "job_income": job_in,
            "job_expense": job_out,
            "job_surplus": job_in - job_out,
        })
    df = pd.DataFrame(rows)
    for key in ("before", "after", "job"):
        df[f"{key}_cum"] = df[f"{key}_surplus"].cumsum()
    return df


def yearly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """연도별 합계."""
    cols = ["before_surplus", "after_surplus", "job_surplus", "cash_support", "expense_saving"]
    out = df.groupby("year")[cols].sum().reset_index()
    out["months"] = df.groupby("year").size().values
    return out


def horizon_totals(df: pd.DataFrame, years: tuple[int, ...] = (1, 3, 5)) -> list[dict]:
    """1·3·5년 누적 잉여자금 비교."""
    res = []
    for y in years:
        n = min(len(df), y * 12)
        part = df.iloc[:n]
        res.append({
            "years": y,
            "months": n,
            "before": int(part["before_surplus"].sum()),
            "after": int(part["after_surplus"].sum()),
            "job": int(part["job_surplus"].sum()),
        })
    return res


# ─────────────────────────── 예금·적금 ───────────────────────────
def _tax(gross_interest: float, principal: float, tax_free: bool, tax_free_limit: float) -> float:
    """이자소득세. 비과세는 한도 이내 원금에 해당하는 이자만 면제."""
    if gross_interest <= 0:
        return 0.0
    if not tax_free:
        return gross_interest * INTEREST_TAX_RATE
    if principal <= 0:
        return 0.0
    taxable_ratio = max(0.0, principal - max(tax_free_limit, 0)) / principal
    return gross_interest * taxable_ratio * INTEREST_TAX_RATE


def _floor10(x: float) -> int:
    """원 단위 절사 (세금은 10원 미만 절사)."""
    return int(x // 10 * 10)


@dataclass
class SavingResult:
    product: str
    principal: int
    gross_interest: int
    tax: int
    net_interest: int
    maturity: int
    note: str = ""
    extra: dict = field(default_factory=dict)


def simple_saving(monthly: int, months: int) -> SavingResult:
    """단순 저축(이자 없음)."""
    p = monthly * months
    return SavingResult("단순 저축", p, 0, 0, 0, p, "매월 저축액 × 개월 수 (이자 없음)")


def installment_saving(monthly: int, months: int, annual_rate: float,
                       tax_free: bool = False, tax_free_limit: float = TAX_FREE_LIMIT) -> SavingResult:
    """정기적금(단리). k번째 달 납입금은 (months-k+1)개월 동안 이자가 붙는다.

    이자 = 월납입액 × 연이율/12 × n(n+1)/2
    """
    p = monthly * months
    gross = monthly * (annual_rate / 12) * months * (months + 1) / 2
    tax = _floor10(_tax(gross, p, tax_free, tax_free_limit))
    gross_i = int(gross)
    net = gross_i - tax
    name = "정기적금 (비과세 가정)" if tax_free else "정기적금 (일반과세)"
    return SavingResult(name, p, gross_i, tax, net, p + net, "매월 생기는 잉여자금을 넣는 방식")


def time_deposit(lump: int, months: int, annual_rate: float,
                 tax_free: bool = False, tax_free_limit: float = TAX_FREE_LIMIT) -> SavingResult:
    """정기예금(단리). 이자 = 원금 × 연이율 × 개월/12"""
    gross = lump * annual_rate * months / 12
    tax = _floor10(_tax(gross, lump, tax_free, tax_free_limit))
    gross_i = int(gross)
    net = gross_i - tax
    name = "정기예금 (비과세 가정)" if tax_free else "정기예금 (일반과세)"
    return SavingResult(name, lump, gross_i, tax, net, lump + net, "이미 가진 목돈을 맡기는 방식")


def compare_plans(monthly: int, lump: int, months: int, sav_rate: float, dep_rate: float) -> list[SavingResult]:
    """운용방안 비교표. 비과세 한도는 예금·적금 원금 합계 기준으로 나눠 적용."""
    inst_p = monthly * months
    # 비과세 한도를 목돈(예금) 먼저, 남는 한도를 적금에 배분
    dep_limit = min(lump, TAX_FREE_LIMIT)
    inst_limit = max(0, TAX_FREE_LIMIT - dep_limit)
    return [
        simple_saving(monthly, months),
        installment_saving(monthly, months, sav_rate, False),
        installment_saving(monthly, months, sav_rate, True, inst_limit),
        time_deposit(lump, months, dep_rate, False),
        time_deposit(lump, months, dep_rate, True, dep_limit),
    ] if lump > 0 else [
        simple_saving(monthly, months),
        installment_saving(monthly, months, sav_rate, False),
        installment_saving(monthly, months, sav_rate, True, min(inst_p, TAX_FREE_LIMIT)),
    ]


# ─────────────────────────── 자립 목표 ───────────────────────────
def goal_projection(lump: int, monthly: int | list[int], months: int, annual_rate: float,
                    tax_free: bool = False) -> pd.DataFrame:
    """장기 자립자금 적립 추이 (만기 재예치를 월 단위 세후 복리로 근사).

    monthly: 고정 월 저축액, 또는 월별 저축액 리스트(취업 전에는 0처럼 달라지는 경우).
    principal = 내가 넣은 돈 누계 (자산 이동), interest = 새로 생긴 돈(이자) 누계.
    """
    r = annual_rate * (1 if tax_free else (1 - INTEREST_TAX_RATE)) / 12
    contrib = monthly if isinstance(monthly, list) else [monthly] * months
    bal, principal = float(lump), float(lump)
    rows = [{"offset": 0, "principal": principal, "interest": 0.0, "balance": bal}]
    for m in range(1, months + 1):
        c = contrib[m - 1] if m - 1 < len(contrib) else 0
        bal = bal * (1 + r) + c
        principal += c
        rows.append({"offset": m, "principal": principal, "interest": bal - principal, "balance": bal})
    return pd.DataFrame(rows)


def grow_lump(lump: int, months: int, annual_rate: float, tax_free: bool = False) -> float:
    r = annual_rate * (1 if tax_free else (1 - INTEREST_TAX_RATE)) / 12
    return lump * (1 + r) ** months


def required_monthly(target: int, lump: int, months: int, annual_rate: float,
                     tax_free: bool = False) -> int:
    """목표금액 도달에 필요한 월 저축액 (goal_projection과 같은 가정)."""
    if months <= 0:
        return 0
    r = annual_rate * (1 if tax_free else (1 - INTEREST_TAX_RATE)) / 12
    if r == 0:
        need = (target - lump) / months
    else:
        g = (1 + r) ** months
        need = (target - lump * g) * r / (g - 1)
    return max(0, int(round(need, -3)))  # 천 원 단위


def months_between(y1: int, m1: int, y2: int, m2: int) -> int:
    return max(0, (y2 - y1) * 12 + (m2 - m1))


def won(x: float, unit: str = "만원") -> str:
    """금액 표기: 만 원 단위 (예: 1,234만 원)."""
    if unit == "만원":
        v = x / 10_000
        s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"
        return f"{s}만 원"
    return f"{x:,.0f}원"
