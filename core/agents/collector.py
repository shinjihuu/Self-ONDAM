"""수집 에이전트 — 공식 공공데이터에서 장애인 대상 지원제도를 모아 구조화한다.

흐름
  1. 수집(fetch)   기본: 공공데이터포털 「한국사회보장정보원_복지서비스정보」(15083323, odcloud) 최신 스냅샷
                    대안: 「중앙부처복지서비스」 목록·상세 API (--source bokjiro)
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
import urllib.error
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

# 기본 소스: 「한국사회보장정보원_복지서비스정보」(15083323) — 파일데이터 기반 오픈API(odcloud), 연도별 스냅샷 제공
ODCLOUD_BASE = "https://api.odcloud.kr/api"
ODCLOUD_NS = os.environ.get("ODCLOUD_NAMESPACE", "15083323/v1")
ODCLOUD_UDDI = os.environ.get("ODCLOUD_UDDI", "uddi:e02ed092-d46d-4bf2-8e7e-c3441e950fef")   # 복지서비스정보_20260819
ODCLOUD_SWAGGER = "https://infuser.odcloud.kr/oas/docs?namespace={ns}"
ODCLOUD_SOURCE = "공공데이터포털 · 한국사회보장정보원 복지서비스정보"
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


TIMEOUT = int(os.environ.get("WELFARE_API_TIMEOUT", "60"))   # 해외에서 응답이 느릴 수 있어 넉넉하게
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JaripON-collector/1.0)", "Accept": "application/xml, text/xml, */*"}

# 공공데이터포털 오류 코드 → 쉬운 원인 설명
API_ERROR_HINTS = {
    "SERVICE_KEY_IS_NOT_REGISTERED": "인증키가 등록되지 않았어요. 활용신청 승인 후 키가 동기화되기까지 1~2시간 걸릴 수 있어요. "
                                     "‘일반 인증키(Decoding)’를 넣었는지도 확인하세요.",
    "등록되지 않은 인증키": "인증키가 이 데이터에 등록되지 않았어요. 활용신청 승인 후 1~2시간 기다려 주세요.",
    "Unauthorized": "인증키가 없거나 잘못됐어요. 이 API(중앙부처복지서비스)에 활용신청이 승인됐는지 마이페이지에서 확인하세요.",
    "BLACKLIST_IP": "호출한 서버 IP가 차단됐어요. 해외 IP(GitHub 서버)가 막힌 경우라 국내에서 실행해야 해요.",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS": "일일 호출 한도를 넘었어요. 내일 다시 실행하거나 --limit 값을 줄이세요.",
    "SERVICE_ACCESS_DENIED": "이 API에 대한 접근 권한이 없어요. 활용신청 상태를 확인하세요.",
    "NO_OPENAPI_SERVICE": "API 주소가 바뀌었어요. 공공데이터포털 명세의 요청주소로 WELFARE_API_BASE를 바꿔 주세요.",
}


class ApiError(RuntimeError):
    pass


def _diagnose(status: int | None, body: str) -> str:
    for code, hint in API_ERROR_HINTS.items():
        if code in body:
            return f"{code} — {hint}"
    if status == 403:
        return ("HTTP 403 (접근 거부). 흔한 원인: ① 활용신청 미승인·키 동기화 대기(승인 후 1~2시간) "
                "② 해외 IP 차단(GitHub 서버는 미국 IP) ③ 디코딩/인코딩 키 혼동")
    if status == 401:
        return "HTTP 401 — 인증키가 없거나 이 데이터에 활용신청이 승인되지 않았어요."
    if status == 404:
        return "HTTP 404 — API 주소가 바뀌었을 수 있어요. 공공데이터포털 명세의 요청주소를 확인하세요."
    return f"HTTP {status}"


def _get(url: str, params: dict, retries: int = 3) -> str:
    """API 호출. 4xx는 원인을 진단해 바로 알리고, 5xx·네트워크 오류만 재시도.
    해외 서버(GitHub Actions)에서는 https가 403으로 막히는 경우가 있어 http를 먼저 시도한다."""
    q = urllib.parse.urlencode(params)
    key = str(params.get("serviceKey", ""))
    mask = lambda s: s.replace(key, "***").replace(urllib.parse.quote(key, safe=""), "***") if key else s
    last = None
    for base in (url.replace("https://", "http://", 1), url):
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(f"{base}?{q}", headers=HEADERS)
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    text = r.read().decode("utf-8", errors="replace")
                for code, hint in API_ERROR_HINTS.items():   # 200 응답 안에 오류가 담겨 오는 경우
                    if len(text) < 3000 and code in text and "<servList>" not in text and "<servId>" not in text:
                        raise ApiError(f"{code} — {hint}\n응답 일부: {mask(text[:300])}")
                return text
            except ApiError:
                raise
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:400]
                last = ApiError(f"{_diagnose(e.code, body)}\n요청: {mask(base)}\n응답 일부: {mask(body) or '(본문 없음)'}")
                if e.code < 500:
                    break            # 4xx는 재시도해도 같으니 다음 주소(http)로
            except Exception as e:  # 네트워크 일시 오류 → 재시도
                last = ApiError(f"네트워크 오류: {e}")
            time.sleep(3 * (i + 1))
    raise last or ApiError("API 호출 실패")


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
            try:
                details[sid] = parse_detail(_get(DETAIL_URL, {"serviceKey": key, "callTp": "D", "servId": sid}, retries=1))
            except ApiError as e:   # 상세 조회 하나가 실패해도 목록 정보로 계속 진행
                print(f"[수집 에이전트] 상세 조회 건너뜀 {sid}: {str(e).splitlines()[0]}", file=sys.stderr)
    return items, details


def fetch_from_dir(d: Path) -> tuple[list[dict], dict[str, dict]]:
    items = parse_list((d / "list.xml").read_text(encoding="utf-8"))
    details = {}
    for it in items:
        f = d / f"detail_{it.get('servId')}.xml"
        if f.exists():
            details[it["servId"]] = parse_detail(f.read_text(encoding="utf-8"))
    return items, details


# ─────────────────────────── 1-b. 수집 (복지서비스정보 · odcloud) ───────────────────────────
# 열 이름은 스냅샷마다 조금씩 다를 수 있어, 키워드로 찾아 내부 필드에 연결한다.
COLUMN_KEYS = {
    "servId": ("서비스아이디", "서비스ID", "서비스번호"),
    "servNm": ("서비스명",),
    "servDgst": ("서비스목적요약", "서비스요약", "서비스목적", "요약"),
    "jurMnofNm": ("소관부처", "소관기관", "부처명", "기관명"),
    "srvPvsnNm": ("지원유형", "제공유형", "급여유형"),
    "servDtlLink": ("상세조회URL", "상세URL", "URL", "링크"),
    "tgtrDtlCn": ("지원대상",),
    "slctCritCn": ("선정기준",),
    "alwServCn": ("지원내용",),
    "apply": ("신청방법",),
    "contact": ("문의처", "전화문의", "문의"),
    "trgterIndvdlArray": ("대상자", "가구유형", "대상특성", "생애주기"),
}


def map_columns(columns) -> dict[str, str]:
    """{내부 필드: 실제 열 이름}"""
    cols = list(columns)
    norm = {c: re.sub(r"\s", "", c) for c in cols}
    out, used = {}, set()
    for field, keys in COLUMN_KEYS.items():
        for k in keys:
            hit = next((c for c in cols if c not in used and k in norm[c]), None)
            if hit:
                out[field] = hit
                used.add(hit)
                break
    return out


def row_to_item_detail(row: dict, cmap: dict) -> tuple[dict, dict]:
    g = lambda f: str(row.get(cmap.get(f, ""), "") or "").strip()
    item = {k: g(k) for k in ("servId", "servNm", "servDgst", "jurMnofNm", "srvPvsnNm", "servDtlLink", "trgterIndvdlArray")}
    if not item["servId"]:
        item["servId"] = re.sub(r"\W", "", item["servNm"])[:30]
    detail = {k: g(k) for k in ("tgtrDtlCn", "slctCritCn", "alwServCn")}
    if g("apply"):
        detail["applmetList"] = [{"servSeDetailNm": g("apply")[:200]}]
    if g("contact"):
        detail["inqplCtadrList"] = [{"servSeDetailNm": g("contact")[:200]}]
    return item, detail


def latest_uddi(ns: str = ODCLOUD_NS) -> str:
    """Swagger 문서에서 가장 최신 날짜의 스냅샷을 찾는다. 실패하면 기본값."""
    try:
        spec = json.loads(_get(ODCLOUD_SWAGGER.format(ns=ns), {}, retries=1))
        cands = []
        for path, ops in spec.get("paths", {}).items():
            text = json.dumps(ops, ensure_ascii=False)
            m = re.search(r"(20\d{6})", text)
            u = re.search(r"(uddi:[0-9a-f\-_]+)", path)
            if m and u:
                cands.append((m.group(1), u.group(1)))
        if cands:
            return max(cands)[1]
    except Exception as e:
        print(f"[수집 에이전트] 최신 스냅샷 자동 확인 실패, 기본값 사용: {str(e).splitlines()[0]}", file=sys.stderr)
    return ODCLOUD_UDDI


def fetch_from_odcloud(max_pages: int = 30) -> tuple[list[dict], dict[str, dict], dict]:
    key = _service_key()
    if not key:
        raise SystemExit("DATA_GO_KR_KEY가 없습니다.")
    uddi = os.environ.get("ODCLOUD_UDDI") or latest_uddi()
    url = f"{ODCLOUD_BASE}/{ODCLOUD_NS}/{uddi}"
    rows, page, total = [], 1, None
    while page <= max_pages:
        data = json.loads(_get(url, {"serviceKey": key, "page": page, "perPage": 1000, "returnType": "JSON"}))
        batch = data.get("data") or []
        total = data.get("totalCount", total)
        rows += batch
        if not batch or (total is not None and len(rows) >= int(total)):
            break
        page += 1
    if not rows:
        raise ApiError(f"데이터가 비어 있어요 (스냅샷 {uddi}).")
    cmap = map_columns(rows[0].keys())
    print(f"[수집 에이전트] 스냅샷 {uddi} · {len(rows)}행 · 열 {list(rows[0].keys())}", file=sys.stderr)
    print(f"[수집 에이전트] 열 연결 {cmap}", file=sys.stderr)
    if "servNm" not in cmap:
        raise ApiError(f"‘서비스명’ 열을 찾지 못했어요. 실제 열 이름: {list(rows[0].keys())} → COLUMN_KEYS를 고쳐 주세요.")
    items, details = [], {}
    for r in rows:
        it, d = row_to_item_detail(r, cmap)
        items.append(it)
        details[it["servId"]] = d
    return items, details, {"source": ODCLOUD_SOURCE, "snapshot": uddi, "columns": cmap}


def fetch_from_odcloud_file(path: Path) -> tuple[list[dict], dict[str, dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["data"]
    cmap = map_columns(rows[0].keys())
    items, details = [], {}
    for r in rows:
        it, d = row_to_item_detail(r, cmap)
        items.append(it)
        details[it["servId"]] = d
    return items, details, {"source": ODCLOUD_SOURCE, "snapshot": path.name, "columns": cmap}


# ─────────────────────────── 2~4. 선별 · 분류 · 구조화 ───────────────────────────
def _norm(name: str) -> str:
    return re.sub(r"\s|지원사업|서비스|사업|\(.*?\)", "", name)


def _join(d: dict, keys) -> str:
    return "\n".join(d.get(k, "") for k in keys if d.get(k))


def _lines(text: str, n: int = 4) -> list[str]:
    parts = [re.sub(r"^[\s\-·•○●▶※\d.)]+", "", x).strip() for x in re.split(r"[\n\r]+|(?<=다\.)\s+", text or "")]
    return [p for p in parts if len(p) >= 4][:n]


DISABILITY_NAME = r"장애|발달|척수|시각|청각|농아|보조기기"
NOT_TARGET_NAME = r"실종|노숙|알코올|고엽제|산재|선천성대사|난청검사"


def is_disability_target(item: dict, detail: dict) -> bool:
    """장애인 대상 제도인지. 요약에 '장애'가 스치듯 나오는 제도(실종아동, 산재 등)는 빼고,
    제도명 또는 지원대상 문장이 장애인을 직접 가리키는 경우만 남긴다."""
    name = item.get("servNm", "")
    if re.search(NOT_TARGET_NAME, name):
        return False
    if re.search(DISABILITY_NAME, name):
        return True
    target = _join(detail, FIELD_TEXT_TARGET) + " " + item.get("trgterIndvdlArray", "")
    return bool(re.search(r"장애인|장애아동|발달장애", target))


def classify(item: dict, detail: dict) -> str:
    """support_type: cash | care | employment | finance"""
    name = item.get("servNm", "")
    kind = item.get("srvPvsnNm", "") + " " + detail.get("srvPvsnNm", "")
    body = name + " " + item.get("servDgst", "") + " " + _join(detail, FIELD_TEXT_BENEFIT)
    if re.search(r"저축|통장|자산형성|적금|대출|대여|융자|이자", name + item.get("servDgst", "")):
        return "finance"
    if re.search(r"보조기기|검사|진단|검진|의료비|보장구", name):      # 현물·서비스 지원
        return "care"
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


_LLM_FAILS = 0


def refine_with_llm(name: str, target_text: str, heuristic: dict) -> tuple[dict, str | None]:
    """AI로 조건을 다듬는다. 실패하거나 AI가 없으면 규칙 추출 결과를 그대로 쓴다."""
    global _LLM_FAILS
    from core import ai
    if not ai.ai_available() or not target_text or _LLM_FAILS >= 3:   # 3번 연속 실패하면 규칙 추출만 사용
        return heuristic, None
    if ai.LAST_ERROR and "402" in ai.LAST_ERROR:   # 무료 크레딧 소진 → 더 호출하지 않음
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
        _LLM_FAILS += 1
        if _LLM_FAILS == 3:
            print(f"[수집 에이전트] AI 응답이 3번 연속 실패해 이후는 규칙 추출만 사용해요. 마지막 오류: {ai.LAST_ERROR}", file=sys.stderr)
        return heuristic, None
    _LLM_FAILS = 0
    m = re.search(r"\{.*\}", out, re.S)
    try:
        refined = validate_criteria(json.loads(m.group(0))) if m else None
    except Exception:
        refined = None
    if not refined:
        return heuristic, None
    return refined, provider


CHILD_NAME = r"아동|장애아|보육|특수학교|특수학급|청소년|영유아"


def normalize(item: dict, detail: dict, fetched_at: str, use_llm: bool, source: str = SOURCE_NAME) -> dict:
    sid = item.get("servId", "")
    name = item.get("servNm") or detail.get("servNm", "")
    stype = classify(item, detail)
    category, icon, rule = TYPE_META[stype]
    target = _join(detail, FIELD_TEXT_TARGET) or item.get("servDgst", "")
    criteria = extract_criteria(target)
    if re.search(CHILD_NAME, name) and "max_age" not in criteria:
        criteria["max_age"] = 18                        # 아동·청소년 대상 제도 (제도명 기준)
    extractor = "rules"
    if use_llm:
        criteria, provider = refine_with_llm(name, target, criteria)
        if provider:
            extractor = f"rules+llm:{provider}"
    apply = "; ".join(x.get("servSeDetailNm", "") for x in detail.get("applmetList", []) if x.get("servSeDetailNm"))
    contact = "; ".join(f"{x.get('servSeDetailNm', '')} {x.get('servSeDetailLink', '')}".strip()
                        for x in detail.get("inqplCtadrList", []))
    link = item.get("servDtlLink") or (BOKJIRO_DETAIL.format(sid) if re.fullmatch(r"WLF\w+", sid or "") else "https://www.bokjiro.go.kr")
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
        "source": {"type": "collected", "name": source, "serv_id": sid, "fetched_at": fetched_at,
                   "verified": False, "extractor": extractor},
    }


# ─────────────────────────── 5. 실행 · 저장 ───────────────────────────
def collect(items: list[dict], details: dict[str, dict], use_llm: bool = True,
            source: str = SOURCE_NAME, max_keep: int | None = None, extra_meta: dict | None = None) -> dict:
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
        if max_keep is not None and len(programs) >= max_keep:
            continue
        programs.append(normalize(it, d, fetched_at, use_llm, source))
    types = {}
    for p in programs:
        types[p["support_type"]] = types.get(p["support_type"], 0) + 1
    return {
        "meta": {"collected_at": fetched_at, "source": source, **(extra_meta or {}), "fetched": len(items), "kept": len(programs),
                 "skipped_duplicates": dup, "skipped_off_target": off_target, "by_type": types,
                 "notice": "자동 수집된 제도는 검수 전이며, 추천 에이전트는 이 제도들을 ‘우선 확인’으로 올리지 않습니다."},
        "programs": programs,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="자립ON 지원제도 수집 에이전트")
    ap.add_argument("--source", choices=["odcloud", "bokjiro"], default="odcloud",
                    help="odcloud = 복지서비스정보(15083323, 기본) · bokjiro = 중앙부처복지서비스 API")
    ap.add_argument("--query", default="장애인")
    ap.add_argument("--limit", type=int, default=100, help="저장할 장애인 대상 제도 최대 수")
    ap.add_argument("--from-file", type=Path, help="저장해 둔 odcloud 응답(JSON) 파일")
    ap.add_argument("--from-dir", type=Path, help="저장해 둔 API 응답(list.xml, detail_<servId>.xml) 폴더")
    ap.add_argument("--no-llm", action="store_true", help="AI 다듬기 생략")
    ap.add_argument("--out", type=Path, default=OUTPUT_PATH)
    a = ap.parse_args(argv)
    try:
        meta = {"source": SOURCE_NAME}
        if a.from_dir:
            items, details = fetch_from_dir(a.from_dir)
        elif a.from_file:
            items, details, meta = fetch_from_odcloud_file(a.from_file)
        elif a.source == "odcloud":
            items, details, meta = fetch_from_odcloud()
        else:
            items, details = fetch_from_api(a.query, a.limit)
    except ApiError as e:
        print(f"[수집 에이전트] ❌ 공공데이터 API 호출 실패 — 기존 데이터는 그대로 둡니다.\n{e}", file=sys.stderr)
        return 1
    src = meta.pop("source")
    meta.pop("columns", None)
    result = collect(items, details, use_llm=not a.no_llm, source=src, max_keep=a.limit, extra_meta=meta)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m = result["meta"]
    print(f"[수집 에이전트] 가져옴 {m['fetched']} · 저장 {m['kept']} · 중복 제외 {m['skipped_duplicates']} · "
          f"대상 아님 {m['skipped_off_target']} · 유형 {m['by_type']} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
