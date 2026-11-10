"""2026년 기준 현금성 지원 금액 계산 — 해당 여부와 '월 예상 지원액'을 규칙으로 계산한다.

모든 기준값은 PARAMS_2026에 모아 두었고, 출처를 함께 적었다. 매년 1월 고시가 바뀌면 이 값만 고치면 된다.
계산 결과는 '예상액'이며 실제 수급액은 소득·재산 조사로 결정된다.

출처
  · 보건복지부 보도자료 「2026년 1월부터 장애인연금 월 최대 43만 9,700원 지급」
  · 찾기쉬운 생활법령정보 「장애인연금법에 따른 장애인연금」 (2026.9.15. 기준)
  · 보건복지부 장애인연금 개요 (소득인정액 산정: 근로소득 공제, 재산 환산)
  · 보건복지부 장애인활동지원 서비스이용 안내 (본인부담금)
  · 장애수당: 지자체(인천시·강원도) 안내 및 보도 (월 6만 원, 보장시설 수급자 3만 원)
"""
from __future__ import annotations

from dataclasses import dataclass, field

PARAMS_2026 = {
    "year": 2026,
    "pension": {
        "basic_max": 349_700,                 # 기초급여 (18~64세)
        "basic_min": 20_000,                  # 감액 후 최소 지급액
        "couple_reduction": 0.2,              # 부부 모두 수급 시 기초급여 20% 감액
        "threshold_single": 1_400_000,        # 선정기준액: 배우자 없음
        "threshold_couple": 2_240_000,        # 선정기준액: 배우자 있음
        "additional_18_64": {                 # 부가급여 (18~64세)
            "생계·의료급여 수급자": 90_000,
            "주거·교육급여 수급자": 80_000,
            "차상위계층": 80_000,
            "일반 (차상위 초과)": 30_000,
        },
        "earned_income_deduction": 950_000,   # 상시근로소득 기본공제 (1인당 월)
        "earned_income_extra_rate": 0.30,     # 기본공제 후 추가 공제율
        "basic_property": {"대도시": 135_000_000, "중소도시": 85_000_000, "농어촌": 72_500_000},
        "financial_deduction": 20_000_000,    # 금융재산 공제 (가구별)
        "property_rate_year": 0.04,           # 재산의 소득환산율 (연)
    },
    "allowance": {                            # 장애수당 (경증, 18세 이상)
        "amount": 60_000,
        "amount_facility": 30_000,
        "eligible_levels": ("생계·의료급여 수급자", "주거·교육급여 수급자", "차상위계층"),
    },
    "activity_copay": {                       # 장애인활동지원 본인부담금
        "exempt": ("생계·의료급여 수급자",),
        "flat": {"주거·교육급여 수급자": 20_000, "차상위계층": 20_000},
        "rates": {"중위소득 70% 이하": 0.04, "중위소득 70~120%": 0.06,
                  "중위소득 120~180%": 0.08, "중위소득 180% 초과": 0.10},
        "cap": 216_200,
    },
}

INCOME_LEVELS = list(PARAMS_2026["pension"]["additional_18_64"])      # 소득 구분 (가구 기준)
MEDIAN_BANDS = list(PARAMS_2026["activity_copay"]["rates"])           # 활동지원 일반가구 구간
METRO = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시")
INCOME_KINDS = ["근로소득", "사업·기타소득", "장애인연금·수당 (소득 미산정)"]


def area_type(region: str) -> str:
    """기본재산액 지역 구분 (군 지역은 화면에서 직접 고를 수 있다)."""
    if region in METRO:
        return "대도시"
    if region == "세종특별자치시":
        return "중소도시"
    return "중소도시"


@dataclass
class Estimate:
    program_id: str
    eligible: bool | None          # True 해당 · False 해당 안 됨 · None 판단 불가(정보 부족)
    monthly: int                   # 월 예상 지원액(원) — 현금 지원
    label: str                     # 한 줄 요약
    breakdown: list[tuple[str, int]] = field(default_factory=list)   # (항목, 금액)
    steps: list[str] = field(default_factory=list)                    # 계산 과정 (쉬운 말)
    notes: list[str] = field(default_factory=list)                    # 주의사항


def _income_by_kind(p: dict) -> tuple[int, int]:
    """(월 근로소득, 월 기타소득) — 장애인연금·수당은 소득인정액에 넣지 않는다."""
    earned = other = 0
    for it in p.get("income_items", []):
        kind = it.get("kind") or ("장애인연금·수당 (소득 미산정)" if any(k in it.get("name", "") for k in ("장애인연금", "장애수당"))
                                  else "근로소득")
        amt = int(it.get("amount") or 0)
        if kind == "근로소득":
            earned += amt
        elif kind == "사업·기타소득":
            other += amt
    return earned, other


def recognized_income(p: dict, earned_override: int | None = None) -> tuple[int, list[str]]:
    """장애인연금 소득인정액 (본인 기준, 월). 배우자가 있으면 배우자 소득을 '기타소득'으로 입력받는다."""
    P = PARAMS_2026["pension"]
    earned, other = _income_by_kind(p)
    if earned_override is not None:
        earned = earned_override
    other += int(p.get("spouse_income", 0) or 0)
    earned_eval = max(0, earned - P["earned_income_deduction"]) * (1 - P["earned_income_extra_rate"])
    income_eval = earned_eval + other
    area = p.get("area_type") or area_type(p.get("region", ""))
    general = max(0, int(p.get("property_general", 0) or 0) - P["basic_property"][area])
    fin = max(0, int(p.get("savings", 0) or 0) - P["financial_deduction"])
    prop = max(0, general + fin - int(p.get("debt", 0) or 0)) * P["property_rate_year"] / 12
    total = int(income_eval + prop)
    steps = [
        f"근로소득 월 {earned:,}원 → 95만 원 공제 후 30% 추가 공제 = {int(earned_eval):,}원",
        f"기타소득(배우자 포함) {other:,}원",
        f"재산 환산: (일반재산 공제 후 {general:,}원 + 금융재산 2,000만 원 공제 후 {fin:,}원 − 부채) × 연 4% ÷ 12 = {int(prop):,}원",
        f"소득인정액 = {total:,}원",
    ]
    return total, steps


def pension_estimate(p: dict, earned_override: int | None = None) -> Estimate:
    P = PARAMS_2026["pension"]
    pid = "disability_pension"
    if not p.get("registered"):
        return Estimate(pid, False, 0, "장애인 등록 후 신청할 수 있어요")
    if p.get("severity") != "심한 장애":
        return Estimate(pid, False, 0, "중증(심한 장애)만 대상이에요 · 경증은 장애수당을 확인하세요")
    if p.get("age", 0) < 18:
        return Estimate(pid, False, 0, "만 18세부터 신청할 수 있어요")
    if p.get("age", 0) >= 65:
        return Estimate(pid, None, 0, "65세 이상은 기초급여가 기초연금으로 바뀌어요 · 별도 확인 필요",
                        notes=["65세 이상은 부가급여만 장애인연금에서 지급돼요."])
    couple = bool(p.get("has_spouse"))
    threshold = P["threshold_couple"] if couple else P["threshold_single"]
    ri, steps = recognized_income(p, earned_override)
    level = p.get("income_level") or INCOME_LEVELS[-1]
    if ri > threshold:
        steps.append(f"선정기준액 {threshold:,}원보다 높아 대상이 아니에요")
        return Estimate(pid, False, 0, f"소득인정액 {ri:,}원 > 선정기준 {threshold:,}원", steps=steps)
    basic = P["basic_max"]
    if couple and p.get("spouse_receives_pension"):
        basic = int(basic * (1 - P["couple_reduction"]))
        steps.append("부부가 모두 받으면 기초급여 20% 감액")
    if ri + basic > threshold:                         # 소득 역전 방지 감액
        basic = max(P["basic_min"], threshold - ri)
        steps.append(f"소득인정액 + 기초급여가 선정기준을 넘지 않도록 기초급여를 {basic:,}원으로 감액")
    add = P["additional_18_64"][level]
    total = basic + add
    steps.append(f"기초급여 {basic:,}원 + 부가급여({level}) {add:,}원 = 월 {total:,}원")
    notes = []
    if level == "생계·의료급여 수급자":
        notes.append("생계급여를 받는 경우 기초급여가 소득으로 반영되어 생계급여가 줄어들 수 있어요.")
    return Estimate(pid, True, total, f"월 {total:,}원 예상 (기초 {basic:,} + 부가 {add:,})",
                    [("기초급여", basic), (f"부가급여 · {level}", add)], steps, notes)


def allowance_estimate(p: dict) -> Estimate:
    A = PARAMS_2026["allowance"]
    pid = "disability_allowance"
    if not p.get("registered"):
        return Estimate(pid, False, 0, "장애인 등록 후 신청할 수 있어요")
    if p.get("severity") == "심한 장애":
        return Estimate(pid, False, 0, "중증은 장애인연금 대상이에요 (중복 수급 불가)")
    if p.get("age", 0) < 18:
        return Estimate(pid, False, 0, "18세 미만은 장애아동수당을 확인하세요")
    level = p.get("income_level") or INCOME_LEVELS[-1]
    if level not in A["eligible_levels"]:
        return Estimate(pid, False, 0, "기초생활수급자·차상위계층만 대상이에요")
    amt = A["amount_facility"] if p.get("in_facility") else A["amount"]
    return Estimate(pid, True, amt, f"월 {amt:,}원 ({level})", [("장애수당", amt)],
                    [f"만 18세 이상 경증 등록장애인 · {level} → 월 {amt:,}원"])


def activity_copay(p: dict, monthly_benefit: int | None = None) -> Estimate:
    """활동지원 본인부담금 (월). monthly_benefit = 결정된 월 활동지원급여액(바우처)."""
    C = PARAMS_2026["activity_copay"]
    pid = "activity_support"
    level = p.get("income_level") or INCOME_LEVELS[-1]
    benefit = int(monthly_benefit if monthly_benefit is not None else p.get("activity_benefit", 0) or 0)
    if level in C["exempt"]:
        return Estimate(pid, True, 0, "본인부담금 면제 (생계·의료급여 수급자)", steps=["생계·의료급여 수급자는 면제"])
    if level in C["flat"]:
        amt = C["flat"][level]
        return Estimate(pid, True, amt, f"본인부담금 월 {amt:,}원 (정액)", steps=[f"{level} → 월 {amt:,}원 정액"])
    band = p.get("median_band") or MEDIAN_BANDS[1]
    rate = C["rates"][band]
    if not benefit:
        return Estimate(pid, None, 0, f"월 급여액을 넣으면 본인부담금을 계산해요 ({band} {rate:.0%}, 상한 {C['cap']:,}원)")
    amt = min(C["cap"], int(benefit * rate // 100 * 100))
    return Estimate(pid, True, amt, f"본인부담금 월 {amt:,}원 ({band} {rate:.0%})",
                    steps=[f"월 급여액 {benefit:,}원 × {rate:.0%} = {int(benefit * rate):,}원 → 상한 {C['cap']:,}원 적용 → {amt:,}원"])


def estimate_for(program_id: str, p: dict) -> Estimate | None:
    if program_id == "disability_pension":
        return pension_estimate(p)
    if program_id == "disability_allowance":
        return allowance_estimate(p)
    if program_id == "activity_support":
        return activity_copay(p)
    return None
