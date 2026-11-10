"""조건 기반 추천 규칙 — 수급 '확정'이 아닌 '확인 우선순위'만 판단한다."""
from __future__ import annotations

from dataclasses import dataclass, field

PRIORITY = "우선 확인"
MORE_INFO = "추가 정보 필요"
NO_MATCH = "현재 조건과 맞지 않음"
STATUS_ORDER = {PRIORITY: 0, MORE_INFO: 1, NO_MATCH: 2}

DEVELOPMENTAL = {"지적장애", "자폐성장애"}
EMPLOYED = {"취업 중"}
JOB_SEEKING = {"구직 중 (취업 준비)", "미취업", "직업훈련 중"}

# 참고용: 장애인연금 단독가구 선정기준액 (2025년 고시 228만 원). 매년 변경 → 공식 확인 필요.
PENSION_THRESHOLD_REF = 2_280_000
PENSION_THRESHOLD_NOTE = "2025년 단독가구 선정기준액 228만 원(참고값, 매년 변경)"


@dataclass
class Recommendation:
    program_id: str
    status: str
    reasons: list[str] = field(default_factory=list)   # 충족한 조건
    checks: list[str] = field(default_factory=list)    # 추가로 확인할 조건
    future: str = ""                                    # 앞으로 달라질 수 있는 점
    in_use: bool = False


def _base(p: dict, pid: str) -> Recommendation:
    return Recommendation(pid, PRIORITY, in_use=pid in p.get("using_programs", []))


def check_pension(p: dict) -> Recommendation:
    r = _base(p, "disability_pension")
    if not p["registered"]:
        r.status = NO_MATCH
        r.checks.append("장애인 등록이 먼저 필요합니다.")
        return r
    if p["age"] < 18:
        r.status = NO_MATCH
        r.checks.append("만 18세 이상부터 신청할 수 있습니다.")
        r.future = f"{18 - p['age']}년 뒤 다시 확인해 보세요."
        return r
    if p["severity"] != "심한 장애":
        r.status = NO_MATCH
        r.checks.append("‘장애의 정도가 심한 장애인’(중증)이 대상입니다.")
        return r
    r.reasons += ["만 18세 이상", "등록된 심한 장애"]
    if p["monthly_income"] <= PENSION_THRESHOLD_REF:
        r.reasons.append(f"월 소득이 참고 선정기준액 이하 ({PENSION_THRESHOLD_NOTE})")
        r.checks.append("재산을 포함한 ‘소득인정액’ 심사가 필요합니다 (보유 저축액도 반영).")
    else:
        r.status = MORE_INFO
        r.checks.append("월 소득이 참고 선정기준액보다 높아 소득인정액 심사 결과를 확인해야 합니다. "
                        "(근로소득은 공제 후 반영되므로 실제로는 낮게 계산될 수 있습니다)")
    if p["employment"] in JOB_SEEKING:
        r.future = "취업 후 근로소득이 생기면 소득인정액이 달라져 수급 여부가 바뀔 수 있습니다."
    return r


def check_activity(p: dict) -> Recommendation:
    r = _base(p, "activity_support")
    if not p["registered"]:
        r.status = NO_MATCH
        r.checks.append("장애인 등록이 먼저 필요합니다.")
        return r
    if not (6 <= p["age"] < 65):
        r.status = NO_MATCH
        r.checks.append("만 6세 이상 ~ 65세 미만이 대상입니다.")
        return r
    r.reasons += ["만 6세 이상 ~ 65세 미만", "등록 장애인"]
    if p["care_need"] == "필요 없음":
        r.status = MORE_INFO
        r.checks.append("일상생활 지원 필요도가 낮게 입력되어 있어, 종합조사 결과 대상이 되지 않을 수 있습니다.")
    else:
        r.reasons.append(f"돌봄 필요: {p['care_need']}")
        r.checks.append("국민연금공단 ‘서비스지원 종합조사’ 결과로 이용 시간이 정해집니다.")
    r.checks.append("소득 수준에 따른 본인부담금을 확인하세요.")
    return r


def check_day_activity(p: dict) -> Recommendation:
    r = _base(p, "day_activity")
    if p["disability_type"] not in DEVELOPMENTAL:
        r.status = NO_MATCH
        r.checks.append("지적·자폐성 장애(발달장애)인이 대상입니다.")
        return r
    if not (18 <= p["age"] <= 64):
        r.status = NO_MATCH
        r.checks.append("만 18세 ~ 64세가 대상입니다.")
        return r
    if not p["registered"]:
        r.status = NO_MATCH
        r.checks.append("장애인 등록이 먼저 필요합니다.")
        return r
    r.reasons += ["발달장애(지적·자폐성)", "만 18세 ~ 64세"]
    if p["employment"] in EMPLOYED or p["employment"] == "직업훈련 중":
        r.status = MORE_INFO
        r.checks.append("취업·직업훈련 중인 경우 이용이 제한되거나 조정될 수 있습니다. "
                        f"{p['region']} 기준을 행정복지센터에 확인하세요.")
    else:
        r.reasons.append("낮 시간 활동 지원이 필요한 미취업 상태")
        r.future = "취업하면 이용이 제한될 수 있어, 취업 시점에 맞춰 서비스 전환을 계획하세요."
    if p["care_need"] != "필요 없음":
        r.reasons.append("보호자 돌봄 부담 완화에 도움")
    r.checks.append("활동지원서비스와 함께 이용 시 활동지원 시간이 일부 차감될 수 있습니다.")
    return r


def check_kead(p: dict) -> Recommendation:
    r = _base(p, "kead_employment")
    if not p["registered"]:
        r.status = MORE_INFO
        r.checks.append("대부분의 프로그램은 장애인 등록이 필요합니다.")
        return r
    if p["age"] < 15:
        r.status = NO_MATCH
        r.checks.append("구직 연령(만 15세 이상) 이후 이용할 수 있습니다.")
        return r
    if p["employment"] in JOB_SEEKING:
        r.reasons += ["등록 장애인", f"현재 상태: {p['employment']}"]
        r.checks.append("직업능력평가 후 맞는 프로그램(지원고용·맞춤훈련 등)이 정해집니다.")
    elif p["employment"] in EMPLOYED:
        r.status = MORE_INFO
        r.reasons.append("등록 장애인")
        r.checks.append("이미 취업 중이라면 고용 유지·직무 적응 지원 위주로 확인하세요.")
    else:
        r.status = MORE_INFO
        r.checks.append("학업 중이라면 졸업 전 진로 연계 프로그램을 확인하세요.")
    return r


def check_work_assistant(p: dict) -> Recommendation:
    r = _base(p, "work_assistant")
    if p["employment"] not in EMPLOYED:
        r.status = NO_MATCH
        r.checks.append("취업 중인 중증장애인 근로자가 대상입니다.")
        if p["severity"] == "심한 장애":
            r.future = "취업 후에는 ‘우선 확인’ 대상이 될 수 있어요. 취업 시점에 다시 확인하세요."
        return r
    if p["severity"] != "심한 장애":
        r.status = NO_MATCH
        r.checks.append("중증(심한 장애) 근로자가 대상입니다.")
        return r
    r.reasons += ["취업 중", "심한 장애"]
    r.checks.append("핵심 업무는 본인이 할 수 있고, 부수 업무에 지원이 필요한지 확인합니다.")
    return r


RULES = [check_pension, check_activity, check_day_activity, check_kead, check_work_assistant]


def recommend(profile: dict) -> list[Recommendation]:
    recs = [rule(profile) for rule in RULES]
    return sorted(recs, key=lambda r: STATUS_ORDER[r.status])


def overlap_warnings(profile: dict, selected_ids: list[str]) -> list[str]:
    """지원제도 간 중복·변경 가능성 안내."""
    w = []
    s = set(selected_ids)
    if {"day_activity", "activity_support"} <= s:
        w.append("주간활동서비스와 활동지원서비스를 함께 이용하면 활동지원 시간이 일부 차감될 수 있어요.")
    if "day_activity" in s and profile["employment"] in EMPLOYED | {"직업훈련 중"}:
        w.append("취업·직업훈련 중에는 주간활동서비스 이용이 제한될 수 있어요.")
    if "disability_pension" in s:
        w.append("장애인연금은 소득인정액에 따라 금액이 달라지거나 중단될 수 있어요. 장기 예측은 ‘계속 지급’을 가정한 결과예요.")
    return w
