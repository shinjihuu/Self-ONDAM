"""조건 기반 판정 엔진 — 수급 '확정'이 아닌 '확인 우선순위'만 판단한다.

각 제도의 자격조건은 programs.json의 `criteria`(구조화된 조건)로 정의되고,
이 모듈은 어떤 제도든 같은 방식으로 판정한다. 수집 에이전트가 새로 모은 제도도 그대로 판정할 수 있다.

criteria 필드
  registered            "required"(미등록 → 맞지 않음) | "preferred"(미등록 → 추가 정보 필요)
  min_age / max_age     연령 범위 (만 나이, 포함)
  disability_types      대상 장애 유형 목록 (비어 있으면 제한 없음)
  severity              "심한 장애" 등 필수 장애 정도
  employment_required   이 취업 상태여야 대상 (아니면 맞지 않음)
  employment_priority   이 취업 상태면 우선 확인 (아니면 추가 정보 필요)
  employment_restricted 이 취업 상태면 이용 제한 가능 (추가 정보 필요)
  care_need_required    돌봄 필요가 '필요 없음'이면 추가 정보 필요
  income_max_ref        참고 소득기준 (초과 시 추가 정보 필요)
  checks                항상 안내할 확인사항
  future                {"job_seeking" | "not_employed" | "not_employed_severe": 안내 문구}
"""
from __future__ import annotations

from dataclasses import dataclass, field

PRIORITY = "우선 확인"
MORE_INFO = "추가 정보 필요"
NO_MATCH = "현재 조건과 맞지 않음"
STATUS_ORDER = {PRIORITY: 0, MORE_INFO: 1, NO_MATCH: 2}

EMPLOYED = {"취업 중"}
JOB_SEEKING = {"구직 중 (취업 준비)", "미취업", "직업훈련 중"}
UNVERIFIED_NOTE = "자동 수집된 제도예요. 신청 전 공식 안내에서 대상·조건을 꼭 확인하세요."


@dataclass
class Recommendation:
    program_id: str
    status: str
    reasons: list[str] = field(default_factory=list)   # 충족한 조건
    checks: list[str] = field(default_factory=list)    # 추가로 확인할 조건
    future: str = ""                                    # 앞으로 달라질 수 있는 점
    in_use: bool = False
    verified: bool = True                               # 수작업 검수 여부


def _age_text(lo, hi) -> str:
    if lo is not None and hi is not None:
        return f"만 {lo}세 ~ {hi}세"
    if lo is not None:
        return f"만 {lo}세 이상"
    return f"만 {hi}세 이하"


def evaluate(program: dict, p: dict) -> Recommendation:
    """제도 1개를 사용자 정보로 판정한다."""
    c = program.get("criteria") or {}
    verified = program.get("source", {}).get("verified", True)
    r = Recommendation(program["id"], PRIORITY, in_use=program["id"] in p.get("using_programs", []), verified=verified)
    fut = c.get("future", {})

    def stop(msg: str, future: str = "") -> Recommendation:
        r.status, r.future = NO_MATCH, future
        r.checks.append(msg)
        return r

    # 1) 장애인 등록
    reg = c.get("registered")
    if reg and not p["registered"]:
        if reg == "required":
            return stop("장애인 등록이 먼저 필요합니다.")
        r.status = MORE_INFO
        r.checks.append("대부분의 프로그램은 장애인 등록이 필요합니다.")
        return r

    # 2) 연령
    lo, hi = c.get("min_age"), c.get("max_age")
    if lo is not None and p["age"] < lo:
        return stop(f"{_age_text(lo, hi)}이 대상입니다.", f"{lo - p['age']}년 뒤 다시 확인해 보세요.")
    if hi is not None and p["age"] > hi:
        return stop(f"{_age_text(lo, hi)}이 대상입니다.")

    # 3) 장애 유형
    types = c.get("disability_types") or []
    if types and p["disability_type"] not in types:
        return stop(f"{'·'.join(t.replace('장애', '') for t in types)} 장애인이 대상입니다.")

    # 4) 필수 취업 상태
    req = c.get("employment_required") or []
    if req and p["employment"] not in req:
        future = fut.get("not_employed_severe", "") if p["severity"] == "심한 장애" else ""
        return stop(f"{'·'.join(req)}인 {'중증장애인 ' if c.get('severity') else ''}근로자가 대상입니다.", future)

    # 5) 장애 정도
    sev = c.get("severity")
    if sev and p["severity"] != sev:
        return stop(f"‘장애의 정도가 {sev.replace(' 장애', '')} 장애인’이 대상입니다.")

    # ── 기본 조건 충족 ──
    if lo is not None or hi is not None:
        r.reasons.append(_age_text(lo, hi))
    if types:
        r.reasons.append(f"{'·'.join(types)}")
    if sev:
        r.reasons.append(f"등록된 {sev}" if reg else sev)
    elif reg:
        r.reasons.append("등록 장애인")
    if req:
        r.reasons.append(f"현재 상태: {p['employment']}")

    # 6) 우선 대상 취업 상태
    pri = c.get("employment_priority") or []
    if pri:
        if p["employment"] in pri:
            r.reasons.append(f"현재 상태: {p['employment']}")
        else:
            r.status = MORE_INFO
            r.checks.append(c.get("other_status_note", {}).get(p["employment"], "현재 취업 상태로 이용 가능한 프로그램을 확인하세요."))

    # 7) 이용 제한 취업 상태
    res = c.get("employment_restricted") or []
    if res:
        if p["employment"] in res:
            r.status = MORE_INFO
            r.checks.append(c.get("restricted_note", "현재 취업 상태에서는 이용이 제한될 수 있습니다.").format(region=p["region"]))
        else:
            r.reasons.append("이용 제한 대상(취업·훈련 중)이 아님")
            r.future = fut.get("not_employed", "")

    # 8) 돌봄 필요
    if c.get("care_need_required"):
        if p["care_need"] == "필요 없음":
            r.status = MORE_INFO
            r.checks.append("일상생활 지원 필요도가 낮게 입력되어 있어, 조사 결과 대상이 되지 않을 수 있습니다.")
        else:
            r.reasons.append(f"돌봄 필요: {p['care_need']}")
    if c.get("care_bonus") and p["care_need"] != "필요 없음":
        r.reasons.append("보호자 돌봄 부담 완화에 도움")

    # 9) 참고 소득기준
    ref = c.get("income_max_ref")
    if ref:
        note = c.get("income_ref_note", f"참고 기준 {ref:,}원")
        if p["monthly_income"] <= ref:
            r.reasons.append(f"월 소득이 참고 선정기준액 이하 ({note})")
        else:
            r.status = MORE_INFO
            r.checks.append("월 소득이 참고 선정기준액보다 높아 소득 심사 결과를 확인해야 합니다. "
                            "(근로소득은 공제 후 반영되므로 실제로는 낮게 계산될 수 있습니다)")

    r.checks.extend(c.get("checks", []))
    if p["employment"] in JOB_SEEKING and fut.get("job_seeking"):
        r.future = fut["job_seeking"]

    # 10) 조건 정보가 없거나 검수 전인 제도는 '우선 확인'으로 올리지 않는다
    if not c:
        r.status = MORE_INFO
        r.checks.insert(0, "자격조건을 자동으로 읽지 못했어요. 공식 안내를 확인해 주세요.")
    if not verified:
        if r.status == PRIORITY:
            r.status = MORE_INFO
        r.checks.insert(0, UNVERIFIED_NOTE)
    return r


def _default_programs() -> list[dict]:
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "data" / "programs.json"
    return json.loads(path.read_text(encoding="utf-8"))["programs"]


def recommend(profile: dict, programs: list[dict] | None = None) -> list[Recommendation]:
    progs = programs if programs is not None else _default_programs()
    recs = [evaluate(pr, profile) for pr in progs]
    return sorted(recs, key=lambda r: (STATUS_ORDER[r.status], not r.verified))


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
