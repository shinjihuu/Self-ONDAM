"""수집 에이전트 — 공식 공공데이터에서 장애인 대상 지원제도를 모아 구조화한다.

흐름
  1. 수집(fetch)   공공데이터포털 · 한국사회보장정보원 「중앙부처복지서비스」 목록·상세 API 호출
  2. 선별(filter)  장애인 대상 제도만 남기고, 수작업 정리 제도(programs.json)와 겹치는 것은 제외
  3. 분류(classify) 제공유형·본문으로 현금지원 / 돌봄 / 고용 / 금융·자산형성 구분 → 재무·비재무 분류
  4. 구조화(extract) 대상·선정기준 문장에서 나이·장애유형·장애정도·취업상태 조건을 규칙으로 추출하고,
                    AI(OpenAI → Hugging Face)가 있으면 한 번 더 다듬는다 (AI 결과는 검증 후 반영)
  5. 저장(save)    data/programs_collected.json — 모든 제도는 '검수 전'(verified=False)으로 저장

실행
  python -m core.agents.collector --limit 40          # 실제 API (DATA_GO_KR_KEY 필요)
  python -m core.agents.collector --from-dir DIR       # 저장해 둔 API 응답(XML)으로 실행
  python -m core.agents.collector --no-llm             # AI 다듬기 생략

API 필드명은 공공데이터포털 명세(중앙부처복지서비스 V001)를 따른다. 명세가 바뀌면 FIELD_* 상수만 고치면 된다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURATED_PATH = ROOT / "data" / "programs.json"
OUTPUT_PATH = ROOT / "data" / "programs_collected.json"

API_BASE = os.environ.get("WELFARE_API_BASE",
                          "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001")
LIST_URL = f"{API_BASE}/NationalWelfarelistV001"
DETAIL_URL = f"{API_BASE}/NationalWelfaredetailedV001"
SOURCE_NAME = "공공데이터포털 · 한국사회보장정보원 중앙부처복지서비스"
BOKJIRO_DETAIL = "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId={}"

FIELD_LIST_ITEM = "servList"
FIELD_TEXT_TARGET = ("tgtrDtlCn", "slctCritCn")          # 지원대상 · 선정기준
FIELD_TEXT_BENEFIT = ("alwServCn",)                        # 지원내용
JOB_SEEKING = ["구직 중 (취업 준비)", "미취업", "직업훈련 중"]
ALL_TYPES = ["지적장애", "자폐성장애", "지체장애", "뇌병변장애", "시각장애", "청각장애", "언어장애", "정신장애"]


# ─────────────────────────── 1. 수집 ───────────────────────────
def _service_key() -> str | None:
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("DATA_GO_KR_KEY")
        except Exception:
            key = None
    return key


def _get(url: str, params: dict, retries: int = 2) -> str:
    q = urllib.parse.urlencode(params)
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=20) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # 네트워크 일시 오류 → 재시도
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"API 호출 실패: {last}")


def _elem_to_dict(el: ET.Element) -> dict:
    """XML 요소 → dict. 자식이 있는 반복 요소(…List)는 리스트로 모은다."""
    out: dict = {}
    for ch in el:
        if len(ch):
            out.setdefault(ch.tag, []).append({g.tag: (g.text or "").strip() for g in ch})
        else:
            out[ch.tag] = (ch.text or "").strip()
    return out


def parse_list(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    code = root.findtext(".//resultCode")
    if code not in (None, "0", "00", "000"):
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMessage')}")
    return [_elem_to_dict(e) for e in root.iter(FIELD_LIST_ITEM)]


def parse_detail(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    node = root.find(".//wantedDtl")
    return _elem_to_dict(node if node is not None else root)


def fetch_from_api(query: str, limit: int) -> tuple[list[dict], dict[str, dict]]:
    key = _service_key()
    if not key:
        raise SystemExit("DATA_GO_KR_KEY가 없습니다. 공공데이터포털에서 「한국사회보장정보원_중앙부처복지서비스」 "
                         "활용신청 후 일반 인증키(Decoding)를 환경변수 DATA_GO_KR_KEY로 넣어 주세요.")
    items, page = [], 1
    while len(items) < limit:
        xml = _get(LIST_URL, {"serviceKey": key, "callTp": "L", "pageNo": page, "numOfRows": 50,
                              "srchKeyCode": "003", "searchWrd": query})
        batch = parse_list(xml)
        if not batch:
            break
        items += batch
        page += 1
    items = items[:limit]
    details = {}
    for it in items:
        sid = it.get("servId")
        if sid:
            details[sid] = parse_detail(_get(DETAIL_URL, {"serviceKey": key, "callTp": "D", "servId": sid}))
    return items, details


def fetch_from_dir(d: Path) -> tuple[list[dict], dict[str, dict]]:
    items = parse_list((d / "list.xml").read_text(encoding="utf-8"))
    details = {}
    for it in items:
        f = d / f"detail_{it.get('servId')}.xml"
        if f.exists():
            details[it["servId"]] = parse_detail(f.read_text(encoding="utf-8"))
    return items, details


# ─────────────────────────── 2~4. 선별 · 분류 · 구조화 ───────────────────────────
def _norm(name: str) -> str:
    return re.sub(r"\s|지원사업|서비스|사업|\(.*?\)", "", name)


def _join(d: dict, keys) -> str:
    return "\n".join(d.get(k, "") for k in keys if d.get(k))


def _lines(text: str, n: int = 4) -> list[str]:
    parts = [re.sub(r"^[\s\-·•○●▶※\d.)]+", "", x).strip() for x in re.split(r"[\n\r]+|(?<=다\.)\s+", text or "")]
    return [p for p in parts if len(p) >= 4][:n]


def is_disability_target(item: dict, detail: dict) -> bool:
    text = " ".join([item.get("servNm", ""), item.get("servDgst", ""), item.get("trgterIndvdlArray", ""),
                     _join(detail, FIELD_TEXT_TARGET)])
    return "장애" in text


def classify(item: dict, detail: dict) -> str:
    """support_type: cash | care | employment | finance"""
    name = item.get("servNm", "")
    kind = item.get("srvPvsnNm", "") + " " + detail.get("srvPvsnNm", "")
    body = name + " " + item.get("servDgst", "") + " " + _join(detail, FIELD_TEXT_BENEFIT)
    if re.search(r"저축|통장|자산형성|적금|대출|융자|이자", name + item.get("servDgst", "")):
        return "finance"
    if re.search(r"취업|고용|일자리|직업|근로|출퇴근|훈련", name):
        return "employment"
    if "현금" in kind or re.search(r"수당|연금|급여|장려금|지원금", name):
        return "cash"
    if re.search(r"활동지원|돌봄|주간|방과후|보호|요양|재활|바우처", body):
        return "care"
    if re.search(r"취업|고용|일자리|직업", body):
        return "employment"
    return "care"


TYPE_META = {
    "cash": ("재무적 지원", "💰", "수급이 확인된 금액 또는 ‘가정한 지원액’만 월 수입에 더합니다."),
    "finance": ("재무적 지원", "🏦", "지원금이 아니라 저축 매칭·이자·세제 효과로만 반영합니다."),
    "care": ("비재무적 지원", "🤝", "현금 수입으로 반영하지 않습니다. 실제로 줄어드는 본인 비용만 지출 감소로 반영합니다."),
    "employment": ("비재무적 지원", "💼", "직접 수입으로 반영하지 않습니다. 취업 후 급여는 별도로 가정합니다."),
}


def extract_criteria(target_text: str) -> dict:
    """대상·선정기준 문장에서 판정 조건을 규칙으로 추출한다."""
    t = target_text or ""
    c: dict = {}
    m = re.search(r"만?\s*(\d{1,2})\s*세\s*(?:이상)?\s*[~∼\-–]\s*(?:만\s*)?(\d{1,2})\s*세\s*(미만)?", t)
    if m:
        c["min_age"] = int(m.group(1))
        c["max_age"] = int(m.group(2)) - (1 if m.group(3) else 0)
    else:
        if (m := re.search(r"만\s*(\d{1,2})\s*세\s*이상", t)):
            c["min_age"] = int(m.group(1))
        if (m := re.search(r"(?:만\s*)?(\d{1,2})\s*세\s*(미만|이하)", t)):
            c["max_age"] = int(m.group(1)) - (1 if m.group(2) == "미만" else 0)
    if re.search(r"중증|심한\s*장애", t) and not re.search(r"경증|심하지\s*않은", t):
        c["severity"] = "심한 장애"
    types = []
    if "발달장애" in t:
        types += ["지적장애", "자폐성장애"]
    for ty in ALL_TYPES:
        if ty in t and ty not in types:
            types.append(ty)
    if types and len(types) < len(ALL_TYPES):
        c["disability_types"] = types
    if re.search(r"등록\s*장애인|장애인\s*등록|장애인복지법", t):
        c["registered"] = "required"
    if re.search(r"근로자|재직|(?:취업|근로)\s*(?:중|한|하는)", t):
        c["employment_required"] = ["취업 중"]
    elif re.search(r"구직|미취업|취업\s*희망|취업을\s*원하는", t):
        c["employment_priority"] = JOB_SEEKING
    checks = []
    if (m := re.search(r"기준\s*중위\s*소득\s*(\d+)\s*%", t)):
        checks.append(f"가구 소득이 기준 중위소득 {m.group(1)}% 이하인지 확인하세요.")
    if re.search(r"기초생활\s*수급|차상위", t):
        checks.append("기초생활수급자·차상위계층 여부를 확인하세요.")
    if checks:
        c["checks"] = checks
    return c


ALLOWED_KEYS = {"min_age", "max_age", "severity", "disability_types", "registered", "employment_required",
                "employment_priority", "employment_restricted", "care_need_required", "checks"}
EMPLOYMENT_VALUES = {"구직 중 (취업 준비)", "미취업", "직업훈련 중", "취업 중", "학생"}

LLM_SYSTEM = ("너는 한국 복지제도 공고문에서 자격조건을 JSON으로 뽑는 도우미야. "
              "문장에 명시된 조건만 뽑고, 추측하지 마. JSON 객체 하나만 출력해.")


def validate_criteria(raw: dict) -> dict:
    """AI가 만든 조건을 허용된 키·값만 남겨 검증한다."""
    out: dict = {}
    for k, v in (raw or {}).items():
        if k not in ALLOWED_KEYS or v in (None, "", [], False):
            continue
        if k in ("min_age", "max_age"):
            if isinstance(v, (int, float)) and 0 <= v <= 120:
                out[k] = int(v)
        elif k == "severity":
            if v == "심한 장애":
                out[k] = v
        elif k == "registered":
            if v in ("required", "preferred"):
                out[k] = v
        elif k == "disability_types":
            vals = [x for x in v if x in ALL_TYPES] if isinstance(v, list) else []
            if vals:
                out[k] = vals
        elif k in ("employment_required", "employment_priority", "employment_restricted"):
            vals = [x for x in v if x in EMPLOYMENT_VALUES] if isinstance(v, list) else []
            if vals:
                out[k] = vals
        elif k == "care_need_required":
            out[k] = bool(v)
        elif k == "checks":
            out[k] = [str(x)[:120] for x in v][:4] if isinstance(v, list) else []
    if "min_age" in out and "max_age" in out and out["min_age"] > out["max_age"]:
        out.pop("max_age")
    return out


def refine_with_llm(name: str, target_text: str, heuristic: dict) -> tuple[dict, str | None]:
    """AI로 조건을 다듬는다. 실패하거나 AI가 없으면 규칙 추출 결과를 그대로 쓴다."""
    from core import ai
    if not ai.ai_available() or not target_text:
        return heuristic, None
    prompt = f"""제도명: {name}
대상·선정기준 원문:
{target_text[:1500]}

규칙으로 1차 추출한 조건: {json.dumps(heuristic, ensure_ascii=False)}

다음 키만 쓸 수 있어 (해당 없으면 생략):
min_age(int), max_age(int, 포함), severity("심한 장애"), disability_types({ALL_TYPES} 중 일부),
registered("required"|"preferred"), employment_required / employment_priority / employment_restricted
({sorted(EMPLOYMENT_VALUES)} 중 일부), care_need_required(bool), checks(추가 확인사항 문장 리스트, 최대 3개)
원문에 근거해 1차 결과를 고친 최종 JSON만 출력해."""
    out, provider = ai.complete(prompt, LLM_SYSTEM, 500)
    if not out:
        return heuristic, None
    m = re.search(r"\{.*\}", out, re.S)
    try:
        refined = validate_criteria(json.loads(m.group(0))) if m else None
    except Exception:
        refined = None
    if not refined:
        return heuristic, None
    return refined, provider


def normalize(item: dict, detail: dict, fetched_at: str, use_llm: bool) -> dict:
    sid = item.get("servId", "")
    name = item.get("servNm") or detail.get("servNm", "")
    stype = classify(item, detail)
    category, icon, rule = TYPE_META[stype]
    target = _join(detail, FIELD_TEXT_TARGET) or item.get("servDgst", "")
    criteria = extract_criteria(target)
    extractor = "rules"
    if use_llm:
        criteria, provider = refine_with_llm(name, target, criteria)
        if provider:
            extractor = f"rules+llm:{provider}"
    apply = "; ".join(x.get("servSeDetailNm", "") for x in detail.get("applmetList", []) if x.get("servSeDetailNm"))
    contact = "; ".join(f"{x.get('servSeDetailNm', '')} {x.get('servSeDetailLink', '')}".strip()
                        for x in detail.get("inqplCtadrList", []))
    link = item.get("servDtlLink") or BOKJIRO_DETAIL.format(sid)
    agency = " · ".join(x for x in [item.get("jurMnofNm"), item.get("jurOrgNm")] if x)
    return {
        "id": f"bokjiro_{sid}",
        "name": name,
        "category": category,
        "support_type": stype,
        "icon": icon,
        "agency": agency or "중앙부처",
        "summary": item.get("servDgst") or (_lines(target, 1) or [""])[0],
        "benefits": _lines(_join(detail, FIELD_TEXT_BENEFIT)) or [item.get("servDgst", "")],
        "requirements": _lines(target),
        "cautions": ["자동 수집된 정보예요. 지원 내용과 금액은 공식 안내에서 확인하세요."],
        "cashflow_rule": rule,
        "default_amount": 0,
        "apply": apply or "복지로 상세 안내 참고",
        "contact": contact or item.get("rprsCtadr") or "보건복지상담센터 ☎ 129",
        "links": [{"label": "복지로 상세 안내", "url": link}],
        "criteria": criteria,
        "source": {"type": "collected", "name": SOURCE_NAME, "serv_id": sid, "fetched_at": fetched_at,
                   "verified": False, "extractor": extractor},
    }


# ─────────────────────────── 5. 실행 · 저장 ───────────────────────────
def collect(items: list[dict], details: dict[str, dict], use_llm: bool = True) -> dict:
    curated = json.loads(CURATED_PATH.read_text(encoding="utf-8"))["programs"]
    curated_names = {_norm(p["name"]) for p in curated}
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")
    programs, dup, off_target, seen = [], 0, 0, set()
    for it in items:
        d = details.get(it.get("servId"), {})
        name = it.get("servNm", "")
        if not is_disability_target(it, d):
            off_target += 1
            continue
        key = _norm(name)
        if key in curated_names or key in seen:
            dup += 1
            continue
        seen.add(key)
        programs.append(normalize(it, d, fetched_at, use_llm))
    types = {}
    for p in programs:
        types[p["support_type"]] = types.get(p["support_type"], 0) + 1
    return {
        "meta": {"collected_at": fetched_at, "source": SOURCE_NAME, "fetched": len(items), "kept": len(programs),
                 "skipped_duplicates": dup, "skipped_off_target": off_target, "by_type": types,
                 "notice": "자동 수집된 제도는 검수 전이며, 추천 에이전트는 이 제도들을 ‘우선 확인’으로 올리지 않습니다."},
        "programs": programs,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="자립ON 지원제도 수집 에이전트")
    ap.add_argument("--query", default="장애인")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--from-dir", type=Path, help="저장해 둔 API 응답(list.xml, detail_<servId>.xml) 폴더")
    ap.add_argument("--no-llm", action="store_true", help="AI 다듬기 생략")
    ap.add_argument("--out", type=Path, default=OUTPUT_PATH)
    a = ap.parse_args(argv)
    items, details = fetch_from_dir(a.from_dir) if a.from_dir else fetch_from_api(a.query, a.limit)
    result = collect(items, details, use_llm=not a.no_llm)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m = result["meta"]
    print(f"[수집 에이전트] 가져옴 {m['fetched']} · 저장 {m['kept']} · 중복 제외 {m['skipped_duplicates']} · "
          f"대상 아님 {m['skipped_off_target']} · 유형 {m['by_type']} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
