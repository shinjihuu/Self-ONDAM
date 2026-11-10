"""Hugging Face 연결 점검 — 토큰 권한, 사용 가능한 모델, 모델별 실제 응답을 확인한다.

실행: HF_TOKEN=hf_... python scripts/ai_check.py
토큰 값은 출력하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("HF_TOKEN", "")
ROUTER = "https://router.huggingface.co/v1"

# 작은 모델(sLLM) 위주 + 한국어가 되는 중형 모델
CANDIDATES = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "meta-llama/Llama-3.2-3B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen3-4B-Instruct-2507",
    "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "google/gemma-3-12b-it",
    "google/gemma-3-27b-it",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "microsoft/Phi-3.5-mini-instruct",
    "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct",
    "openai/gpt-oss-20b",
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
]


def req(url: str, body: dict | None = None, timeout: int = 60) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                               headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def req_with(url: str, key: str, timeout: int = 30) -> tuple[int, str]:
    r = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def check_other_services() -> None:
    """Gemini·Groq·OpenAI 키가 있으면 자립ON과 같은 방식(core.ai)으로 실제 호출해 본다."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from core import ai
    for p in ai.providers():
        if p["name"] == "Hugging Face":
            continue
        print(f"\n== {p['name']} ==")
        if p["base_url"]:
            st_, body = req_with(p["base_url"].rstrip("/") + "/models", p["api_key"])
            if st_ == 200:
                ids = [d.get("id", "") for d in json.loads(body).get("data", [])]
                chat = [i for i in ids if not any(k in i for k in ("embed", "image", "tts", "audio", "veo", "imagen", "aqa", "live"))]
                print(f"사용 가능한 모델 {len(ids)}개 중 대화형 일부: {chat[:40]}")
            else:
                print(f"모델 목록 실패 HTTP {st_}: {body[:200]}")
        for m in p["models"]:
            try:
                out = ai._call({**p, "model": m}, "장애인연금이 뭔지 한 문장으로 쉽게 설명해 주세요.", 80, system="한국어로 짧게 답해.")
                print(f"✅ {m}: {out[:90]}")
            except Exception as e:
                print(f"❌ {m}: {type(e).__name__}: {str(e)[:200]}")


def check_app_explanation() -> None:
    """앱과 똑같이 ‘김OO 님 · 장애인연금’ 추천 설명을 생성해 본다."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from core import ai
    from core.agents.recommender import RecommenderAgent
    if not ai.ai_available():
        return
    agent, _ = RecommenderAgent.from_files(include_collected=False)
    root = os.path.join(os.path.dirname(__file__), "..")
    profile = json.load(open(os.path.join(root, "data", "personas.json"), encoding="utf-8"))["personas"][0]["profile"]
    rec = next(r for r in agent.recommend(profile) if r.program_id == "day_activity")
    text, by = agent.explain(profile, rec)
    print(f"\n== 앱 추천 설명 예시 (주간활동서비스) · 응답: {by or '규칙 기반'} ==\n{text}")
    if not by:
        print(f"마지막 오류: {ai.LAST_ERROR}")
    for q in ("발달장애인 자녀 상속은 어떻게 준비해요?", "딸이 취업하면 장애인연금은 얼마가 돼요?"):
        ans, by = agent.answer(q, profile)
        print(f"\n== 질문: {q} · 응답: {by or '규칙 기반'} ==\n{ans}")


def main() -> int:
    check_other_services()
    check_app_explanation()
    if not TOKEN:
        print("\nHF_TOKEN이 비어 있어 Hugging Face 점검은 건너뛰어요.")
        return 0
    print(f"토큰 형식: {'hf_로 시작' if TOKEN.startswith('hf_') else '⚠️ hf_로 시작하지 않음'} · {len(TOKEN)}자")

    print("\n== 1. 토큰 정보 (whoami) ==")
    st, body = req("https://huggingface.co/api/whoami-v2")
    if st == 200:
        w = json.loads(body)
        auth = w.get("auth", {}).get("accessToken", {})
        print(f"계정: {w.get('name')} · PRO: {w.get('isPro')} · 결제 가능(canPay): {w.get('canPay')}")
        print(f"토큰 이름: {auth.get('displayName')} · 역할: {auth.get('role')}")
        scopes = auth.get("fineGrained", {}).get("scoped", []) + [{"permissions": auth.get("fineGrained", {}).get("global", [])}]
        perms = sorted({p for s in scopes for p in s.get("permissions", [])})
        print(f"권한: {perms or '(fine-grained 아님)'}")
        if auth.get("role") == "fineGrained" and "inference.serverless.write" not in perms:
            print("⚠️ 'Make calls to Inference Providers' 권한(inference.serverless.write)이 없어요.")
    else:
        print(f"whoami 실패 HTTP {st}: {body[:300]}")

    print("\n== 2. 라우터에서 사용 가능한 모델 (일부) ==")
    st, body = req(f"{ROUTER}/models")
    available = set()
    if st == 200:
        models = json.loads(body).get("data", [])
        available = {m.get("id") for m in models}
        print(f"총 {len(models)}개")
        for m in models:
            mid = m.get("id", "")
            if any(k in mid.lower() for k in ("8b", "7b", "4b", "3b", "12b", "20b", "exaone", "gemma", "qwen3")):
                provs = [p.get("provider") for p in m.get("providers", [])][:6]
                print(f"  {mid}  {provs}")
    else:
        print(f"모델 목록 실패 HTTP {st}: {body[:300]}")

    print("\n== 3. 모델별 실제 호출 ==")
    tried = CANDIDATES + [m for m in sorted(available) if m not in CANDIDATES and any(
        k in m.lower() for k in ("8b-instruct", "7b-instruct", "4b-instruct", "exaone"))][:6]
    ok = []
    for mid in tried:
        t0 = time.time()
        st, body = req(f"{ROUTER}/chat/completions", {
            "model": mid, "max_tokens": 60, "temperature": 0.2,
            "messages": [{"role": "user", "content": "장애인연금이 뭔지 한 문장으로 쉽게 설명해 주세요."}]})
        dt = time.time() - t0
        if st == 200:
            try:
                msg = json.loads(body)["choices"][0]["message"].get("content") or ""
            except Exception:
                msg = body[:120]
            ok.append(mid)
            print(f"✅ {mid} ({dt:.1f}s): {msg.strip()[:90]}")
        else:
            print(f"❌ {mid} HTTP {st}: {body.strip()[:220]}")
    print(f"\n성공한 모델: {ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
