"""맞춤형 추천 에이전트 — 제도 카탈로그를 사용자 상황에 맞게 판정·정렬·설명한다.

역할 분담
  · 판정  : eligibility.evaluate (구조화된 조건 → 우선 확인 / 추가 정보 필요 / 맞지 않음) — 결정적·검증 가능
  · 설명  : AI(OpenAI → Hugging Face → 규칙 문장)가 추천 이유와 다음 할 일을 쉬운 말로 작성
  · 질의응답: 카탈로그(공식 자료) 범위 안에서만 답변
안전장치
  · 수집 에이전트가 모은 '검수 전' 제도는 '우선 확인'으로 올리지 않는다.
  · AI는 자격을 판정하지 않는다. 판정은 항상 규칙 엔진 결과를 따른다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import ai, eligibility as el

ROOT = Path(__file__).resolve().parents[2]
CURATED_PATH = ROOT / "data" / "programs.json"
COLLECTED_PATH = ROOT / "data" / "programs_collected.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"meta": {}, "programs": []}


def _norm(name: str) -> str:
    return re.sub(r"\s|지원사업|서비스|사업|\(.*?\)", "", name)


def load_catalog(include_collected: bool = True,
                 curated_path: Path = CURATED_PATH, collected_path: Path = COLLECTED_PATH) -> tuple[list[dict], dict]:
    """수작업 정리 제도 + 수집 에이전트 결과를 합친다. 이름이 겹치면 수작업 정리본을 우선한다."""
    curated = _read(curated_path)
    collected = _read(collected_path)
    programs = list(curated["programs"])
    names = {_norm(p["name"]) for p in programs}
    added = 0
    if include_collected:
        for p in collected.get("programs", []):
            if _norm(p["name"]) not in names:
                programs.append(p)
                names.add(_norm(p["name"]))
                added += 1
    info = {
        "curated": len(curated["programs"]),
        "collected_available": len(collected.get("programs", [])),
        "collected_used": added,
        "collected_meta": collected.get("meta", {}),
        "notice": curated.get("meta", {}).get("notice", ""),
    }
    return programs, info


class RecommenderAgent:
    def __init__(self, programs: list[dict]):
        self.programs = programs
        self.by_id = {p["id"]: p for p in programs}

    @classmethod
    def from_files(cls, include_collected: bool = True) -> tuple["RecommenderAgent", dict]:
        programs, info = load_catalog(include_collected)
        return cls(programs), info

    # 1) 판정 + 정렬
    def recommend(self, profile: dict) -> list[el.Recommendation]:
        return el.recommend(profile, self.programs)

    # 2) 설명 (AI → 규칙 문장)
    def explain(self, profile: dict, rec: el.Recommendation) -> tuple[str, object]:
        return ai.explain_recommendation(profile, self.by_id[rec.program_id], rec)

    # 3) 질의응답 — 질문과 관련 있는 제도만 골라 근거로 넘긴다
    def answer(self, question: str, profile: dict, top_k: int = 6) -> tuple[str, object]:
        """질문과 관련된 제도 + 이 사용자의 판정·금액 결과를 함께 근거로 넘긴다."""
        recs = [r for r in self.recommend(profile) if r.verified]
        summary = [{"제도": self.by_id[r.program_id]["name"], "판정": r.status,
                    "월 예상 지원액": r.amount or None, "본인부담": r.copay or None, "금액 근거": r.amount_label or None}
                   for r in recs]
        return ai.answer_question(question, profile, self.relevant(question, top_k), summary)

    def relevant(self, question: str, top_k: int = 6) -> list[dict]:
        q = question.replace(" ", "")
        def score(p: dict) -> int:
            name = _norm(p["name"])
            s = 10 if name and name in q else 0
            s += sum(2 for w in re.findall(r"[가-힣]{2,}", p["name"]) if w in q)
            s += sum(1 for w in ("연금", "수당", "취업", "돌봄", "활동", "주간", "저축", "근로") if w in q and w in p["name"] + p["summary"])
            return s + (1 if p.get("source", {}).get("verified", True) else 0)
        return sorted(self.programs, key=score, reverse=True)[:top_k]

    def selected_warnings(self, profile: dict, selected_ids: list[str]) -> list[str]:
        w = el.overlap_warnings(profile, selected_ids)
        if any(not self.by_id[i].get("source", {}).get("verified", True) for i in selected_ids if i in self.by_id):
            w.append("검수 전(자동 수집) 제도가 포함되어 있어요. 지원액은 실제 금액이 아닌 가정값으로만 넣어 주세요.")
        return w
