"""AI 설명 모듈 — OpenAI 키가 있으면 OpenAI, 없으면 Hugging Face 무료 sLLM, 둘 다 없으면 규칙 기반 문장.

AI 역할: 추천 이유·유의사항 설명, 공식 자료 기반 질의응답, 시뮬레이션 결과를 쉬운 말로 풀어주기.
AI가 하지 않는 일: 자격 판정, 금액 계산, 수급 확정 (모두 Python 규칙/계산이 담당).
"""
from __future__ import annotations

import json
import os
import re

SYSTEM_PROMPT = """너는 '자립ON'의 AI 길잡이야. 발달장애인과 보호자가 이해하기 쉽게 설명해.

지켜야 할 규칙:
1. 짧은 문장, 쉬운 낱말, 존댓말(~해요체)을 써. 한 문장에 한 가지 내용만.
2. 수급 여부나 금액을 '확정'하지 마. "자격이 돼요", "받을 수 있어요", "대상이에요"는 쓰지 말고
   "조건이 맞아 보여요", "확인해 볼 만해요", "심사가 필요해요"처럼 말해.
3. 제공된 [공식 자료]와 [계산 결과]에 있는 내용만 말해. 모르는 내용은 "공식 기관에 확인해 주세요"라고 안내해.
4. 돌봄·활동지원·근로지원인 같은 서비스를 현금 수입처럼 말하지 마.
5. 예금·적금에 넣은 돈은 '돈의 이동'이고, 새로 늘어나는 돈은 이자뿐이라는 점을 헷갈리지 않게 말해.
6. 숫자는 '만 원' 단위로 말해.
7. 반드시 한국어로만 답해. 한자·영어 문장을 섞지 마.
"""


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# OpenAI 호환 API를 제공하는 AI 서비스들. 키가 있는 서비스만, 아래 순서대로 시도한다.
# 각 서비스의 모델은 후보를 순서대로 시도하고 처음 성공한 모델을 계속 쓴다. (<NAME>_MODEL로 고정 가능)
# Hugging Face 후보는 2026-11 라우터 점검(scripts/ai_check.py)에서 제공자가 있는 것으로 확인된 모델이다.
PROVIDERS = [
    {"name": "OpenAI", "keys": ("OPENAI_API_KEY",), "base_url": None, "model_env": "OPENAI_MODEL",
     "models": [DEFAULT_OPENAI_MODEL]},
    {"name": "Gemini", "keys": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model_env": "GEMINI_MODEL",
     # 2026-11 점검: 키에 열린 모델 목록 기준 (2.5/2.0 flash는 404)
     # 3.5-flash·gemma-4는 짧은 토큰 한도에서 생각 과정이 섞여 나와 제외
     "models": ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]},
    {"name": "Groq", "keys": ("GROQ_API_KEY",), "base_url": "https://api.groq.com/openai/v1", "model_env": "GROQ_MODEL",
     "models": ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"]},
    {"name": "Hugging Face", "keys": ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"),
     "base_url": "https://router.huggingface.co/v1", "model_env": "HF_MODEL",
     "models": ["meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen3.5-9B", "google/gemma-4-26B-A4B-it", "openai/gpt-oss-20b"]},
]
HF_BASE_URL = PROVIDERS[3]["base_url"]
HF_CANDIDATES = PROVIDERS[3]["models"]
DEFAULT_HF_MODEL = HF_CANDIDATES[0]

_WORKING: dict[str, str] = {}          # 서비스별로 이번 실행에서 성공한 모델
_BAD: set[tuple[str, str]] = set()     # (서비스, 모델) 지원되지 않는 것으로 확인됨
_DISABLED: dict[str, str] = {}         # 키·크레딧 문제로 이번 실행에서 건너뛸 서비스 → 이유

LAST_PROVIDER: str | None = None   # 마지막으로 응답에 성공한 AI
LAST_ERROR: str | None = None      # 마지막 실패 원인 (진단용, 키는 포함하지 않음)


def _secret(*names: str, default: str | None = None) -> str | None:
    """st.secrets → 환경변수 순으로 첫 번째 값을 찾는다."""
    for n in names:
        try:
            import streamlit as st
            if n in st.secrets and st.secrets[n]:
                return str(st.secrets[n])
        except Exception:
            pass
        if os.environ.get(n):
            return os.environ[n]
    return default


def providers() -> list[dict]:
    """키가 있는 AI 서비스 목록 (OpenAI → Gemini → Groq → Hugging Face)."""
    out = []
    for cfg in PROVIDERS:
        key = _secret(*cfg["keys"])
        if not key or cfg["name"] in _DISABLED:
            continue
        fixed = _secret(cfg["model_env"])
        if fixed:
            models = [fixed]
        else:
            w = _WORKING.get(cfg["name"])
            models = ([w] if w else []) + [m for m in cfg["models"] if m != w and (cfg["name"], m) not in _BAD]
            models = models or [cfg["models"][0]]
        out.append({"name": cfg["name"], "api_key": key, "base_url": cfg["base_url"], "model": models[0], "models": models})
    return out


def ai_available() -> bool:
    return bool(providers())


def provider_label() -> str:
    """사이드바 표시용: 지금 우선 사용할 AI."""
    ps = providers()
    if not ps:
        return ""
    p = ps[0]
    if p["name"] not in _WORKING and len(p["models"]) > 1:
        return f"{p['name']} · 모델 자동 선택"
    return f"{p['name']} · {p['model'].split('/')[-1]}"


def _call(p: dict, user_prompt: str, max_tokens: int, system: str = SYSTEM_PROMPT) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=p["api_key"], base_url=p["base_url"], timeout=40, max_retries=1)
    resp = client.chat.completions.create(
        model=p["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_prompt}],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    text = re.sub(r"<(think|thought)>.*?</\1>", "", resp.choices[0].message.content or "", flags=re.S).strip()
    if text.startswith(("<think", "<thought")):     # 생각 과정만 나오고 끝난 경우
        raise ValueError("생각 과정만 출력됨")
    if not text:
        raise ValueError("빈 응답")
    return text


def _chat(user_prompt: str, max_tokens: int = 600, system: str = SYSTEM_PROMPT) -> str | None:
    """키가 있는 AI 서비스를 순서대로 시도. 모두 실패하면 None (규칙 기반 문장으로 대체).
    - 모델 미지원·빈 응답 → 같은 서비스의 다음 후보 모델
    - 키 오류(401/403)·크레딧 없음(402) → 이번 실행 동안 그 서비스를 건너뜀
    - 한도 초과(429)·네트워크 오류 → 다음 서비스로 (다음 요청에서 다시 시도)"""
    global LAST_PROVIDER, LAST_ERROR
    for p in providers():
        for m in p["models"]:
            try:
                text = _call({**p, "model": m}, user_prompt, max_tokens, system=system)
                LAST_PROVIDER = p["name"]
                _WORKING[p["name"]] = m
                return text
            except Exception as e:
                LAST_ERROR = f"{p['name']}({m}): {type(e).__name__}: {str(e)[:200]}"
                status = getattr(e, "status_code", None)
                if status in (401, 402, 403):
                    _DISABLED[p["name"]] = LAST_ERROR
                    break
                if status == 429 or any(k in type(e).__name__ for k in ("Connection", "Timeout")):
                    break
                _BAD.add((p["name"], m))
    return None


def complete(prompt: str, system: str, max_tokens: int = 700) -> tuple[str | None, str | None]:
    """에이전트용 범용 호출. (응답, 응답한 AI 이름)"""
    out = _chat(prompt, max_tokens, system=system)
    return out, (LAST_PROVIDER if out else None)


def _profile_brief(p: dict) -> str:
    keys = ["age", "region", "disability_type", "severity", "registered", "employment",
            "care_need", "monthly_income", "monthly_expense", "savings"]
    return json.dumps({k: p[k] for k in keys if k in p}, ensure_ascii=False)


# ─────────────────────────── 추천 설명 ───────────────────────────
def explain_recommendation(profile: dict, program: dict, rec) -> tuple[str, bool]:
    """(설명 문장, AI 생성 여부)"""
    prompt = f"""[사용자 정보] {_profile_brief(profile)}
[공식 자료] {json.dumps({k: program[k] for k in ('name','summary','benefits','requirements','cautions')}, ensure_ascii=False)}
[규칙 판정] 상태={rec.status}, 충족={rec.reasons}, 추가확인={rec.checks}, 향후={rec.future}

이 사람에게 '{program['name']}'을(를) 왜 살펴보면 좋은지(또는 왜 지금은 맞지 않는지) 3~4문장으로 쉽게 설명해 줘.
마지막 문장은 다음에 할 일 한 가지로 끝내."""
    out = _chat(prompt, 350)
    if out:
        return out, LAST_PROVIDER or "AI"
    return _fallback_recommendation(profile, program, rec), False


def _fallback_recommendation(profile: dict, program: dict, rec) -> str:
    name = profile.get("name") or "사용자"
    if getattr(rec, "in_use", False):
        msg = f"{name} 님은 이미 **{program['name']}**을(를) 이용하고 있어요."
        if rec.future:
            msg += f" {rec.future}"
        msg += " 기준이 매년 바뀌니, 해마다 조건과 금액을 다시 확인해 주세요."
        return msg
    if rec.status == "우선 확인":
        head = f"{name} 님의 상황에서 **{program['name']}**은(는) 먼저 확인해 볼 만해요."
    elif rec.status == "추가 정보 필요":
        head = f"**{program['name']}**은(는) 몇 가지를 더 확인하면 이용 여부를 알 수 있어요."
    else:
        head = f"**{program['name']}**은(는) 지금 입력한 조건과는 맞지 않아요."
    body = ""
    if rec.reasons:
        body += " " + ", ".join(rec.reasons) + " 조건이 맞아요."
    if rec.checks:
        body += " " + rec.checks[0]
    tail = f" 다음 할 일: {program['apply']}."
    if rec.status == "현재 조건과 맞지 않음":
        tail = f" {rec.future}" if rec.future else ""
    return head + body + tail


# ─────────────────────────── 시뮬레이션 설명 ───────────────────────────
def explain_simulation(summary: dict) -> tuple[str, bool]:
    prompt = f"""[계산 결과] {json.dumps(summary, ensure_ascii=False)}

위 현금흐름·저축 시뮬레이션 결과를 발달장애인과 보호자가 이해하도록 4~6문장으로 설명해 줘.
- 지원 전후 매달 남는 돈이 얼마나 달라지는지
- 저축하면 목표에 얼마나 가까워지는지
- '가정'에 기반한 결과라는 점과 확인할 점 1가지"""
    out = _chat(prompt, 450)
    if out:
        return out, LAST_PROVIDER or "AI"
    return _fallback_simulation(summary), False


def _fallback_simulation(s: dict) -> str:
    from core.finance import won as m
    lines = [
        f"지금은 한 달에 **{m(s['before_monthly'])}**이 남아요.",
        f"선택한 지원을 적용하면 한 달에 **{m(s['after_monthly'])}**이 남아요"
        + (f" (+{m(s['after_monthly'] - s['before_monthly'])})." if s['after_monthly'] > s['before_monthly'] else "."),
    ]
    if s.get("job_monthly") is not None and s["job_monthly"] != s["after_monthly"]:
        lines.append(f"취업을 가정하면 취업 후 한 달에 **{m(s['job_monthly'])}**이 남을 것으로 보여요.")
    if s.get("goal_amount"):
        reach = "도달할 수 있을 것으로 보여요" if s["goal_balance"] >= s["goal_amount"] else "조금 모자라요"
        lines.append(f"매달 {m(s['monthly_saving'])}씩 모으면 {s['goal_year']}년에 약 **{m(s['goal_balance'])}**이 되어 "
                     f"목표 {m(s['goal_amount'])}에 {reach}.")
        lines.append(f"이 중 이자로 새로 생기는 돈은 약 {m(s['goal_interest'])}이고, 나머지는 내가 모은 돈이에요.")
    lines.append("이 결과는 지원금이 계속 지급된다는 **가정**이에요. 실제 수급 여부와 금액은 공식 기관에서 확인해 주세요.")
    return " ".join(lines)


# ─────────────────────────── 질의응답 ───────────────────────────
def answer_question(question: str, profile: dict, programs: list[dict]) -> tuple[str, bool]:
    ctx = [{k: p[k] for k in ("name", "summary", "benefits", "requirements", "cautions", "apply", "contact")}
           for p in programs]
    prompt = f"""[사용자 정보] {_profile_brief(profile)}
[공식 자료] {json.dumps(ctx, ensure_ascii=False)}

질문: {question}

공식 자료 안에서만 답해 줘. 자료에 없으면 어디에 문의하면 되는지(연락처) 알려 줘. 5문장 이내."""
    out = _chat(prompt, 450)
    if out:
        return out, LAST_PROVIDER or "AI"
    return _fallback_answer(question, programs), False


def _fallback_answer(question: str, programs: list[dict]) -> str:
    q = question.replace(" ", "")
    for p in programs:
        key = p["name"].replace(" ", "")
        short = key.replace("장애인", "").replace("발달", "").replace("서비스", "").replace("지원사업", "")
        if key in q or (short and short in q):
            return (f"**{p['name']}** — {p['summary']}\n\n"
                    f"- 대상: {' / '.join(p['requirements'])}\n"
                    f"- 신청: {p['apply']}\n- 문의: {p['contact']}")
    return ("궁금한 제도 이름을 넣어 다시 물어봐 주세요. (예: ‘장애인연금 신청은 어디서 해요?’)\n\n"
            "자세한 상담은 보건복지상담센터 ☎ 129, 한국장애인고용공단 ☎ 1588-1519에서 받을 수 있어요.")
