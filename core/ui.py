"""파스텔톤 UI 헬퍼 — CSS, 카드, 배지, 통계 타일, Plotly 테마."""
from __future__ import annotations

import html

import streamlit as st

COLORS = {
    "cream": "#FFF8F1",
    "peach": "#FFD8C7",
    "coral": "#F08A6C",
    "coral_dark": "#D2694B",
    "mint": "#CDEBDD",
    "mint_dark": "#4E9C7D",
    "lavender": "#E6DDF5",
    "lav_dark": "#7E6BB0",
    "butter": "#FFF0C7",
    "butter_dark": "#B98A1E",
    "sky": "#DCEBF8",
    "sky_dark": "#4C83B5",
    "text": "#4A3B35",
    "muted": "#8C7B73",
    "line": "#F1E2D6",
    "gray": "#CBBCB3",
}

SERIES = {"before": "#C9B8AE", "after": COLORS["coral"], "job": "#6FB79A"}


def inject_css(large_text: bool = False) -> None:
    scale = 1.12 if large_text else 1.0
    c = COLORS
    st.markdown(f"""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
@import url('https://fonts.googleapis.com/css2?family=Jua&display=swap');

:root {{ --fs: {scale}; }}
html, body, [class*="css"], .stMarkdown, .stText, input, textarea, select, button, label {{
  font-family: 'Pretendard', -apple-system, 'Apple SD Gothic Neo', sans-serif !important;
}}
.stApp {{
  background:
    radial-gradient(1200px 400px at 100% -10%, #FFE9DD 0%, transparent 60%),
    radial-gradient(900px 380px at -10% 10%, #F1EAFB 0%, transparent 55%),
    {c['cream']};
}}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
.stMarkdown p, .stMarkdown li {{ font-size: calc(1rem * var(--fs)); line-height: 1.7; }}
h1, h2, h3 {{ color: {c['text']}; letter-spacing: -0.02em; }}

/* 사이드바 */
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #FFF1E7 0%, #FBF4FF 100%);
  border-right: 1px solid {c['line']};
}}
section[data-testid="stSidebar"] .stRadio label p {{ font-size: calc(1rem * var(--fs)); }}

/* 브랜드 */
.brand {{ font-family: 'Jua', sans-serif; font-size: 2rem; color: {c['coral_dark']}; line-height: 1; }}
.brand small {{ font-family: 'Pretendard'; font-size: .78rem; color: {c['muted']}; display:block; margin-top:.35rem; }}

/* 히어로 */
.hero {{
  background: linear-gradient(120deg, #FFE3D6 0%, #FFF0C7 55%, #E3F3EA 100%);
  border-radius: 28px; padding: 28px 32px; margin-bottom: 18px;
  border: 1px solid #FBE0D2; box-shadow: 0 10px 30px -18px rgba(210,105,75,.45);
  position: relative; overflow: hidden;
}}
.hero:after {{ content: "🌱"; position:absolute; right: 26px; top: 14px; font-size: 64px; opacity: .9; }}
.hero .eyebrow {{ font-size: .85rem; color: {c['coral_dark']}; font-weight: 700; letter-spacing: .02em; }}
.hero h1 {{ font-family: 'Jua', sans-serif; font-weight: 400; font-size: calc(2.1rem * var(--fs)); margin: .2rem 0 .3rem; }}
.hero p {{ margin: 0; color: #6B5A52; font-size: calc(1.02rem * var(--fs)); max-width: 760px; }}

/* 단계 표시 */
.stepper {{ display:flex; gap:10px; margin: 0 0 22px; flex-wrap: wrap; }}
.step {{ flex:1; min-width: 180px; background: #ffffffaa; border:1.5px solid {c['line']}; border-radius: 18px;
        padding: 12px 16px; display:flex; align-items:center; gap:12px; color:{c['muted']}; }}
.step .num {{ width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center;
             background:{c['line']}; font-weight:800; color:{c['muted']}; flex-shrink:0; }}
.step b {{ display:block; color:{c['text']}; font-size: .98rem; }}
.step span {{ font-size:.8rem; }}
.step.on {{ background:#fff; border-color:{c['coral']}; box-shadow: 0 6px 18px -10px rgba(240,138,108,.7); }}
.step.on .num {{ background:{c['coral']}; color:#fff; }}
.step.done .num {{ background:{c['mint']}; color:{c['mint_dark']}; }}

/* 카드 */
.card {{ background:#fff; border:1px solid {c['line']}; border-radius: 22px; padding: 20px 22px;
        box-shadow: 0 8px 24px -20px rgba(74,59,53,.5); margin-bottom: 14px; }}
.card h4 {{ margin: 0 0 .5rem; font-size: 1.08rem; color:{c['text']}; }}
.card-title {{ display:flex; align-items:center; gap:10px; font-weight:800; font-size:1.12rem; margin-bottom:.4rem; }}
.card-title .ico {{ width:38px; height:38px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:1.3rem; }}
.soft-peach {{ background:#FFF1EA; }} .soft-mint {{ background:#EEF8F3; }} .soft-lav {{ background:#F4EFFB; }}
.soft-butter {{ background:#FFF8E1; }} .soft-sky {{ background:#EEF5FC; }}

/* 섹션 제목 */
.sec {{ display:flex; align-items:center; gap:10px; margin: 26px 0 12px; }}
.sec .dot {{ width:12px; height:12px; border-radius:50%; }}
.sec h3 {{ margin:0; font-size: calc(1.3rem * var(--fs)); font-weight:800; }}
.sec p {{ margin:0 0 0 auto; color:{c['muted']}; font-size:.88rem; }}

/* 통계 타일 */
.tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr)); gap:12px; margin: 6px 0 14px; }}
.tile {{ border-radius: 20px; padding: 16px 18px; border:1px solid {c['line']}; background:#fff; }}
.tile .lab {{ font-size:.84rem; color:{c['muted']}; font-weight:600; }}
.tile .val {{ font-size: calc(1.65rem * var(--fs)); font-weight:800; margin-top:4px; letter-spacing:-.02em; }}
.tile .sub {{ font-size:.8rem; color:{c['muted']}; margin-top:2px; }}
.tile.peach {{ background:#FFF1EA; border-color:#FBD9C9; }} .tile.peach .val {{ color:{c['coral_dark']}; }}
.tile.mint {{ background:#EEF8F3; border-color:#CDEBDD; }} .tile.mint .val {{ color:{c['mint_dark']}; }}
.tile.lav {{ background:#F4EFFB; border-color:#E2D8F3; }} .tile.lav .val {{ color:{c['lav_dark']}; }}
.tile.butter {{ background:#FFF8E1; border-color:#F7E6B2; }} .tile.butter .val {{ color:{c['butter_dark']}; }}
.tile.sky {{ background:#EEF5FC; border-color:#D5E5F4; }} .tile.sky .val {{ color:{c['sky_dark']}; }}

/* 배지 */
.badge {{ display:inline-block; padding: 3px 11px; border-radius: 999px; font-size:.78rem; font-weight:700; margin-right:4px; white-space:nowrap; }}
.b-pri {{ background:{c['mint']}; color:#2F7A5D; }}
.b-more {{ background:{c['butter']}; color:#9A7110; }}
.b-no {{ background:#EFE7E2; color:#8C7B73; }}
.b-cash {{ background:{c['peach']}; color:{c['coral_dark']}; }}
.b-care {{ background:{c['lavender']}; color:{c['lav_dark']}; }}
.b-job {{ background:{c['sky']}; color:{c['sky_dark']}; }}
.b-assume {{ background:#FFE8EC; color:#C0536B; }}
.b-ok {{ background:{c['mint']}; color:#2F7A5D; }}

/* 리스트 */
.chk {{ list-style:none; padding-left:0; margin:.2rem 0; }}
.chk li {{ padding-left: 1.5rem; position:relative; margin:.25rem 0; font-size: calc(.95rem * var(--fs)); }}
.chk li:before {{ content:"✓"; position:absolute; left:0; color:{c['mint_dark']}; font-weight:800; }}
.chk.q li:before {{ content:"?"; color:{c['butter_dark']}; }}
.chk.x li:before {{ content:"·"; color:{c['muted']}; }}

/* 알림 박스 */
.note {{ border-radius: 16px; padding: 12px 16px; font-size: calc(.92rem * var(--fs)); margin: 8px 0; line-height:1.6; }}
.note.warm {{ background:#FFF4E8; border:1px dashed #F5C9A8; color:#7A5440; }}
.note.mint {{ background:#EEF8F3; border:1px dashed #A9D8C1; color:#2F6B54; }}
.note.lav {{ background:#F4EFFB; border:1px dashed #CDBDEB; color:#5E4C8E; }}
.ai-box {{ background: linear-gradient(135deg,#FFF6F0,#F7F1FF); border:1px solid #F1DDEF; border-radius:18px;
          padding: 14px 18px; font-size: calc(.97rem * var(--fs)); line-height:1.75; }}
.ai-box .who {{ font-weight:800; color:{c['lav_dark']}; font-size:.84rem; margin-bottom:4px; }}

/* 위젯 */
.stButton > button, .stFormSubmitButton > button, .stLinkButton > a {{
  border-radius: 14px !important; font-weight: 700 !important; padding: .55rem 1.1rem !important;
  border: 1.5px solid {c['line']} !important;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: linear-gradient(135deg, #F49B7F, {c['coral']}) !important; border: none !important; color: #fff !important;
  box-shadow: 0 8px 18px -10px rgba(240,138,108,.9);
}}
div[data-testid="stForm"] {{ border: none; padding: 0; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 22px !important; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div > div > .card-anchor) {{ background:#fff; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ background:#fff; border-radius: 12px 12px 0 0; padding: 8px 16px; }}
div[data-baseweb="input"], div[data-baseweb="select"] > div {{ border-radius: 12px !important; }}
[data-testid="stExpander"] {{ background:#fff; border-radius: 16px; }}
@media (max-width: 640px) {{
  .hero {{ padding: 22px 20px; }} .hero:after {{ display:none; }}
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
  .step {{ min-width: 100%; }}
}}
.footer {{ text-align:center; color:{c['muted']}; font-size:.8rem; margin: 40px 0 10px; }}
a {{ color: {c['coral_dark']}; }}
</style>
""", unsafe_allow_html=True)


def esc(s: str) -> str:
    return html.escape(str(s))


def hero(eyebrow: str, title: str, desc: str) -> None:
    st.markdown(f'<div class="hero"><div class="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{desc}</p></div>',
                unsafe_allow_html=True)


def stepper(active: int) -> None:
    steps = [("나의 자립 진단", "현재 상황 입력"), ("AI 맞춤 지원", "지원제도 탐색"), ("미래 자립 시뮬레이터", "현금흐름 · 저축")]
    parts = []
    for i, (t, s) in enumerate(steps):
        cls = "on" if i == active else ("done" if i < active else "")
        num = "✓" if i < active else str(i + 1)
        parts.append(f'<div class="step {cls}"><div class="num">{num}</div><div><b>{t}</b><span>{s}</span></div></div>')
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def section(title: str, color: str = "coral", hint: str = "") -> None:
    col = COLORS.get(color, color)
    st.markdown(f'<div class="sec"><div class="dot" style="background:{col}"></div><h3>{title}</h3>'
                f'{f"<p>{hint}</p>" if hint else ""}</div>', unsafe_allow_html=True)


def tiles(items: list[tuple[str, str, str, str]]) -> None:
    """items: (label, value, sub, tone)"""
    html_items = "".join(
        f'<div class="tile {tone}"><div class="lab">{lab}</div><div class="val">{val}</div>'
        f'<div class="sub">{sub}</div></div>' for lab, val, sub, tone in items)
    st.markdown(f'<div class="tiles">{html_items}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str) -> str:
    return f'<span class="badge b-{kind}">{esc(text)}</span>'


STATUS_BADGE = {"우선 확인": "pri", "추가 정보 필요": "more", "현재 조건과 맞지 않음": "no"}
TYPE_BADGE = {"cash": ("현금지원", "cash"), "care": ("돌봄·활동 서비스", "care"), "employment": ("고용 서비스", "job")}


def note(text: str, tone: str = "warm") -> None:
    st.markdown(f'<div class="note {tone}">{text}</div>', unsafe_allow_html=True)


def ai_box(text: str, by_ai) -> None:
    """by_ai: 응답한 AI 이름(str) 또는 False(규칙 기반)."""
    import re
    if by_ai:
        who = "🤖 AI 길잡이" + (f" · {esc(by_ai)}" if isinstance(by_ai, str) else "")
    else:
        who = "🌱 자립ON 길잡이 (규칙 기반 설명)"
    body = esc(text).replace("\n", "<br>")
    body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
    st.markdown(f'<div class="ai-box"><div class="who">{who}</div>{body}</div>', unsafe_allow_html=True)


def plotly_layout(fig, height: int = 340, legend: bool = True):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Pretendard, sans-serif", color=COLORS["text"], size=13),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="white", bordercolor=COLORS["line"], font_family="Pretendard"),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, linecolor=COLORS["line"], tickfont=dict(color=COLORS["muted"]))
    fig.update_yaxes(gridcolor="#F4E9E1", zeroline=True, zerolinecolor="#E9D9CD", tickfont=dict(color=COLORS["muted"]))
    return fig
