"""자립ON — 발달장애인 맞춤형 AI 자립설계 길잡이 (AFPK 영 플래너 챌린지 MVP)"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import ai, eligibility as el, finance as fin, household as hh, ui
from core.ui import COLORS, SERIES, esc

st.set_page_config(page_title="자립ON · AI 자립설계 길잡이", page_icon="🌱", layout="wide",
                   initial_sidebar_state="auto")

DATA = Path(__file__).parent / "data"
PROGRAMS_DB = json.loads((DATA / "programs.json").read_text(encoding="utf-8"))
PROGRAMS = {p["id"]: p for p in PROGRAMS_DB["programs"]}
PERSONAS = {p["id"]: p for p in json.loads((DATA / "personas.json").read_text(encoding="utf-8"))["personas"]}

PAGES = ["① 나의 자립 진단", "② AI 맞춤 지원", "③ 미래 자립 시뮬레이터"]
REGIONS = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
           "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
           "경상북도", "경상남도", "제주특별자치도"]
DISABILITY_TYPES = ["지적장애", "자폐성장애", "지체장애", "뇌병변장애", "시각장애", "청각장애", "언어장애", "정신장애", "기타"]
EMPLOYMENT = ["구직 중 (취업 준비)", "미취업", "직업훈련 중", "취업 중", "학생"]
CARE = ["필요 없음", "일부 필요", "많이 필요"]
TODAY = date(2026, 11, 1)  # 시뮬레이션 기준월 (보고서 기준일 2026.10.31 다음 달)


def man(x: float) -> str:
    return fin.won(x)


# ─────────────────────────── 상태 ───────────────────────────
def load_persona(pid: str) -> None:
    p = PERSONAS[pid]
    st.session_state.persona_id = pid
    st.session_state.profile = copy.deepcopy(p["profile"])
    st.session_state.sim = copy.deepcopy(p["sim_defaults"])
    st.session_state.household = p.get("household")
    for k in list(st.session_state.keys()):
        if k.startswith(("sel_", "sim_", "qa_")):
            del st.session_state[k]
    st.session_state.qa_history = []
    st.session_state.selected = None


def get_selected(p: dict) -> dict:
    """시뮬레이터에 담은 제도 (페이지 이동 후에도 유지)."""
    if st.session_state.get("selected") is None:
        st.session_state.selected = {r.program_id: r.status != el.NO_MATCH for r in el.recommend(p)}
    return st.session_state.selected


def _toggle_sel(pid: str) -> None:
    st.session_state.selected[pid] = st.session_state[f"sel_{pid}"]


def go_page(i: int) -> None:
    st.session_state.page = PAGES[i]


if "profile" not in st.session_state:
    load_persona("afpk_daughter")
    st.session_state.page = PAGES[0]
    st.session_state.large_text = False

profile: dict = st.session_state.profile


# ─────────────────────────── 사이드바 ───────────────────────────
with st.sidebar:
    st.markdown('<div class="brand">자립ON 🌱<small>발달장애인 맞춤형 AI 자립설계 길잡이</small></div>',
                unsafe_allow_html=True)
    st.write("")
    st.radio("메뉴", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    st.markdown("**👪 사례 불러오기**")
    pid = st.selectbox("사례", list(PERSONAS), format_func=lambda k: PERSONAS[k]["label"],
                       index=list(PERSONAS).index(st.session_state.persona_id), label_visibility="collapsed")
    st.caption(PERSONAS[pid]["description"])
    st.button("이 사례로 시작하기", on_click=load_persona, args=(pid,), width="stretch")
    st.divider()
    st.toggle("🔍 큰 글씨로 보기", key="large_text")
    if ai.ai_available():
        st.markdown(ui.badge("AI 연결됨 · " + ai.provider_label(), "ok"), unsafe_allow_html=True)
        if len(ai.providers()) > 1:
            st.caption("OpenAI가 응답하지 않으면 Hugging Face 무료 sLLM으로 자동 전환돼요.")
    else:
        st.markdown(ui.badge("AI 미연결 · 규칙 기반 설명", "more"), unsafe_allow_html=True)
        st.caption("Secrets에 `OPENAI_API_KEY`(유료) 또는 `HF_TOKEN`(무료)을 넣으면 AI 설명이 켜져요.")
    st.divider()
    st.caption("ⓘ 이 서비스는 지원제도 **확인 우선순위**를 안내할 뿐, 수급 여부를 확정하지 않아요. "
               "주민등록번호·계좌번호 등 민감정보는 입력받지 않아요.")

ui.inject_css(st.session_state.large_text)
page_idx = PAGES.index(st.session_state.page)


# ═══════════════════════════ ① 나의 자립 진단 ═══════════════════════════
def page_diagnosis() -> None:
    ui.hero("STEP 1 · 현재 상태 진단", "나의 자립, 지금 어디쯤일까요?",
            "기본정보와 돈의 흐름, 자립 목표를 입력하면 맞춤 지원제도와 미래 현금흐름을 함께 살펴볼 수 있어요.")
    ui.stepper(0)

    hh_data = st.session_state.household
    tabs = st.tabs(["🌱 딸의 자립 진단", "🏠 우리 가족 재무상태 (AFPK 3단계 분석)"] if hh_data else ["🌱 자립 진단"])

    with tabs[0]:
        diagnosis_form()
    if hh_data:
        with tabs[1]:
            household_view(hh_data)


def diagnosis_form() -> None:
    p = profile
    with st.form("diag"):
        c1, c2 = st.columns(2, gap="medium")
        with c1, st.container(border=True):
            st.markdown('<div class="card-title"><div class="ico soft-peach">🙂</div>기본정보</div>', unsafe_allow_html=True)
            a, b = st.columns(2)
            name = a.text_input("이름(별칭)", p["name"])
            age = b.number_input("나이 (만)", 0, 100, p["age"])
            region = st.selectbox("거주지역", REGIONS, REGIONS.index(p["region"]))
            a, b = st.columns(2)
            dtype = a.selectbox("장애 유형", DISABILITY_TYPES, DISABILITY_TYPES.index(p["disability_type"]))
            severity = b.selectbox("장애 정도", ["심한 장애", "심하지 않은 장애"],
                                   0 if p["severity"] == "심한 장애" else 1)
            registered = st.toggle("장애인 등록 완료", p["registered"])
        with c2, st.container(border=True):
            st.markdown('<div class="card-title"><div class="ico soft-lav">🧩</div>비재무정보</div>', unsafe_allow_html=True)
            a, b = st.columns(2)
            employment = a.selectbox("취업 상태", EMPLOYMENT, EMPLOYMENT.index(p["employment"]))
            care = b.selectbox("일상생활 돌봄 필요", CARE, CARE.index(p["care_need"]))
            using = st.multiselect("현재 이용 중인 지원제도", list(PROGRAMS),
                                   [x for x in p["using_programs"] if x in PROGRAMS],
                                   format_func=lambda k: PROGRAMS[k]["name"])
            job_goal = st.text_input("진로·취업 목표", p.get("job_goal", ""), placeholder="예: 요양보호사 자격 취득 후 취업")

        with st.container(border=True):
            st.markdown('<div class="card-title"><div class="ico soft-mint">💵</div>재무정보 '
                        '<span style="font-weight:500;font-size:.85rem;color:#8C7B73">· 본인 기준 월 금액(원)</span></div>',
                        unsafe_allow_html=True)
            a, b = st.columns(2)
            inc_df = a.data_editor(
                pd.DataFrame(p["income_items"]), num_rows="dynamic", width="stretch", key="ed_inc",
                column_config={"name": st.column_config.TextColumn("월 수입 항목", width="medium"),
                               "amount": st.column_config.NumberColumn("금액(원)", min_value=0, step=10000, format="%d"),
                               "source": st.column_config.TextColumn("근거", width="small")})
            exp_cols = {"name": st.column_config.TextColumn("월 지출 항목", width="medium"),
                        "amount": st.column_config.NumberColumn("금액(원)", min_value=0, step=10000, format="%d"),
                        "source": st.column_config.TextColumn("근거", width="small"),
                        "ends_on_job": st.column_config.CheckboxColumn("취업 시 종료")}
            exp_init = pd.DataFrame(p["expense_items"])
            if "ends_on_job" not in exp_init:
                exp_init["ends_on_job"] = False
            exp_init["ends_on_job"] = exp_init["ends_on_job"].fillna(False).astype(bool)
            exp_df = b.data_editor(exp_init, num_rows="dynamic", width="stretch", key="ed_exp",
                                   column_config=exp_cols)
            a, b = st.columns(2)
            savings = a.number_input("본인 명의 보유 저축액(원)", 0, 10**10, p["savings"], step=100000)
            fam = b.number_input("가족이 매달 모아주는 자립자금(원)", 0, 10**8, p.get("family_monthly_saving", 0), step=10000,
                                 help="AFPK 사례: 현금흐름표 ‘자녀 자립자금 적립’ 연 240만 원 = 월 20만 원")

        with st.container(border=True):
            st.markdown('<div class="card-title"><div class="ico soft-butter">🎯</div>재무목표</div>', unsafe_allow_html=True)
            a, b, c, d = st.columns(4)
            goal_year = a.number_input("자립 목표 연도", 2026, 2070, p["goal_year"])
            goal_amount = b.number_input("자립 초기자금 목표(원)", 0, 10**10, p["goal_amount"], step=1_000_000)
            wish = c.number_input("월 저축 희망액(원)", 0, 10**8, p["monthly_saving_wish"], step=10000)
            pls = d.number_input("자립 후 가족 생활지원(월, 원)", 0, 10**8, p.get("parent_living_support", 0), step=10000)

        submitted = st.form_submit_button("💾 저장하고 다시 분석하기", type="primary", width="stretch")

    if submitted:
        inc_df = inc_df.dropna(subset=["name"]).fillna({"amount": 0, "source": ""})
        exp_df = exp_df.dropna(subset=["name"]).fillna({"amount": 0, "source": "", "ends_on_job": False})
        p.update(dict(
            name=name, age=int(age), region=region, disability_type=dtype, severity=severity,
            registered=registered, employment=employment, care_need=care, using_programs=using, job_goal=job_goal,
            income_items=inc_df.to_dict("records"), expense_items=exp_df.to_dict("records"),
            monthly_income=int(inc_df["amount"].sum()), monthly_expense=int(exp_df["amount"].sum()),
            savings=int(savings), family_monthly_saving=int(fam), goal_year=int(goal_year),
            goal_amount=int(goal_amount), monthly_saving_wish=int(wish), parent_living_support=int(pls),
        ))
        for k in [k for k in st.session_state if k.startswith(("sel_", "sim_"))]:
            del st.session_state[k]
        st.session_state.selected = None
        st.toast("저장했어요! 분석 결과가 새로 바뀌었어요 🌷")

    # 진단 요약
    ui.section("진단 요약", "coral", "입력한 정보를 바탕으로 계산했어요")
    surplus = p["monthly_income"] - p["monthly_expense"]
    months_left = fin.months_between(TODAY.year, TODAY.month, p["goal_year"], 1)
    recs = el.recommend(p)
    n_pri = sum(r.status == el.PRIORITY for r in recs)
    ui.tiles([
        ("월 수입", man(p["monthly_income"]), " · ".join(i["name"].split(" (")[0] for i in p["income_items"]) or "-", "peach"),
        ("월 지출", man(p["monthly_expense"]), f"{len(p['expense_items'])}개 항목", "lav"),
        ("매달 남는 돈", man(surplus), "수입 − 지출", "mint" if surplus >= 0 else "peach"),
        ("자립 목표까지", f"{months_left // 12}년 {months_left % 12}개월", f"{p['goal_year']}년 · 목표 {man(p['goal_amount'])}", "butter"),
        ("먼저 확인할 지원", f"{n_pri}개", "AI 맞춤 지원에서 확인", "sky"),
    ])
    if surplus <= 50_000 and p["employment"] != "취업 중":
        ui.note(f"💡 지금은 장애인연금 등으로 생활비를 겨우 충당하는 수준이에요. "
                f"<b>{p.get('job_goal') or '취업'}</b> 이후 근로소득이 생기면 저축 여력이 크게 달라져요. "
                "보고서에서는 취업 시기·소득이 불확실해 근로소득을 반영하지 않았지만, 자립ON에서는 "
                "<b>‘취업 가정’ 시나리오</b>로 따로 비교해 볼 수 있어요.", "warm")
    c1, c2 = st.columns([3, 1])
    c2.button("AI 맞춤 지원 보기 →", type="primary", on_click=go_page, args=(1,), width="stretch")


def household_view(h: dict) -> None:
    res = hh.analyze(h)
    st.markdown(f'<div class="note lav">🏠 자립ON은 가족 재무설계의 <b>1순위 목표 ‘자녀 자립지원자금 마련’</b>을 딸의 입장에서 '
                f'시뮬레이션해요. 아래는 보고서의 가계 재무상태({h["base_date"]} 기준, 단위: 만 원)를 원자료에서 다시 계산한 결과예요.</div>',
                unsafe_allow_html=True)
    ui.tiles([
        ("총자산", f"{res['total_assets']:,.0f}만", "주택 · 자동차 · 금융자산", "peach"),
        ("총부채", f"{res['total_debt']:,.0f}만", "주택담보대출 · 자동차 할부", "lav"),
        ("순자산", f"{res['net_worth']:,.0f}만", "총자산 − 총부채", "mint"),
        ("연 소득 / 연 저축", f"{res['income']:,.0f} / {res['saving']:,.0f}만", f"저축률 {res['saving']/res['income']*100:.1f}%", "butter"),
    ])

    ui.section("가족 생애 타임라인", "lav_dark")
    items = "".join(
        f'<div style="flex:1;min-width:130px;text-align:center;position:relative">'
        f'<div style="width:46px;height:46px;margin:0 auto;border-radius:50%;background:{bg};display:flex;'
        f'align-items:center;justify-content:center;font-weight:800;color:{fg};font-size:.85rem;'
        f'border:3px solid #fff;box-shadow:0 4px 12px -6px rgba(0,0,0,.25)">{t["year"][2:]}′</div>'
        f'<div style="font-weight:800;margin-top:8px">{esc(t["title"])}</div>'
        f'<div style="font-size:.8rem;color:#8C7B73">{t["year"]} · {esc(t["desc"])}</div></div>'
        for t, (bg, fg) in zip(h["timeline"], [(COLORS["peach"], COLORS["coral_dark"]), (COLORS["sky"], COLORS["sky_dark"]),
                                               (COLORS["lavender"], COLORS["lav_dark"]), (COLORS["butter"], COLORS["butter_dark"]),
                                               (COLORS["mint"], COLORS["mint_dark"]), ("#EFE7E2", COLORS["muted"])]))
    st.markdown(f'<div class="card"><div style="position:relative"><div style="position:absolute;top:23px;left:6%;right:6%;'
                f'height:3px;background:linear-gradient(90deg,{COLORS["peach"]},{COLORS["mint"]});border-radius:3px"></div>'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;position:relative">{items}</div></div></div>',
                unsafe_allow_html=True)

    ui.section("재무목표 및 우선순위", "coral")
    rows = "".join(
        f'<tr><td>{ui.badge(g["rank"], "cash" if i == 0 else "no")}</td><td>{g["term"]}</td><td><b>{esc(g["goal"])}</b></td>'
        f'<td>{g["when"]}</td><td style="color:#6B5A52">{esc(g["detail"])}</td></tr>' for i, g in enumerate(h["goals"]))
    st.markdown(f'<div class="card"><table style="width:100%;border-collapse:collapse;font-size:.92rem">'
                f'<thead><tr style="color:#8C7B73;text-align:left"><th>우선순위</th><th>기간</th><th>재무목표</th><th>시기</th><th>세부사항</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>'.replace("<td>", '<td style="padding:9px 6px;border-top:1px solid #F4E9E1">'),
                unsafe_allow_html=True)

    ui.section("재무비율 분석", "mint_dark", "연령대별 권고 기준 충족 여부")
    rrows = ""
    for r in res["ratios"]:
        st_b = ui.badge("충족", "pri") if r.ok else (ui.badge("점검", "more") if r.ok is False else ui.badge("참고", "no"))
        rrows += (f'<tr><td style="color:#8C7B73">{r.group}</td><td><b>{r.name}</b></td>'
                  f'<td style="font-size:1.05rem;font-weight:800;color:{COLORS["coral_dark"]}">{hh.fmt_ratio(r)}</td>'
                  f'<td>{r.guide}</td><td>{r.age_guide}</td><td>{st_b}</td>'
                  f'<td style="font-size:.78rem;color:#8C7B73">{esc(r.formula)}</td></tr>')
    st.markdown(f'<div class="card" style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.9rem;min-width:760px">'
                f'<thead><tr style="color:#8C7B73;text-align:left"><th>구분</th><th>지표</th><th>가계</th><th>가이드라인</th>'
                f'<th>연령대 제안</th><th>평가</th><th>산식 (만 원)</th></tr></thead><tbody>{rrows}</tbody></table></div>'
                .replace("<td", '<td style="padding:8px 6px;border-top:1px solid #F4E9E1"').replace('style="padding:8px 6px;border-top:1px solid #F4E9E1" style="', 'style="padding:8px 6px;border-top:1px solid #F4E9E1;'),
                unsafe_allow_html=True)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        a = h["assets"]
        labels = list(a["cash"]) + list(a["savings"]) + list(a["use"])
        vals = list(a["cash"].values()) + list(a["savings"].values()) + list(a["use"].values())
        fig = go.Figure(go.Pie(labels=labels, values=vals, hole=.6, sort=False,
                               marker=dict(colors=["#BFE3D0", "#A8D5E2", "#C9B6E4", "#F7B9A1", "#FFE1A8"],
                                           line=dict(color="#fff", width=2)),
                               textinfo="percent", textposition="inside", insidetextorientation="horizontal",
                               hovertemplate="%{label}: %{value:,}만 원<extra></extra>"))
        fig.add_annotation(text=f"<b>{res['total_assets']/10000:.1f}억</b><br><span style='font-size:11px'>총자산</span>",
                           showarrow=False, font=dict(size=18))
        st.markdown("**자산 구성** · 주택 집중도 " + f"{res['house_concentration']:.1f}%")
        fig = ui.plotly_layout(fig, 300)
        fig.update_layout(legend=dict(orientation="v", x=1.0, y=0.5, xanchor="left", yanchor="middle"), uniformtext_minsize=11, uniformtext_mode="hide")
        st.plotly_chart(fig, width="stretch")
    with c2:
        exp = {**h["fixed"], **h["variable"]}
        top = sorted(exp.items(), key=lambda x: -x[1])[:8]
        fig = go.Figure(go.Bar(x=[v for _, v in top][::-1], y=[k for k, _ in top][::-1], orientation="h",
                               marker=dict(color=COLORS["peach"], line=dict(color=COLORS["coral"], width=1)),
                               text=[f"{v:,}만" for _, v in top][::-1], textposition="outside",
                               hovertemplate="%{y}: %{x:,}만 원<extra></extra>"))
        st.markdown(f"**연간 지출 상위 항목** · 총지출 {res['spend']:,.0f}만 원")
        fig = ui.plotly_layout(fig, 300, legend=False)
        fig.update_xaxes(visible=False, range=[0, top[0][1] * 1.25])
        st.plotly_chart(fig, width="stretch")

    ui.section("핵심 진단", "butter_dark")
    ui.note(f"📌 <b>소득 의존도 {res['income_dependence']:.1f}%</b> — 가계 소득 대부분이 아버지 근로소득이라 "
            "2031년 6월 퇴직 후 2035년 연금 개시까지 48개월의 소득 공백이 생겨요.", "warm")
    ui.note(f"📌 <b>비상예비자금 {res['ratios'][2].value:.1f}개월분</b> — 50대 권고(5개월)까지 약 "
            f"<b>{res['emergency_gap_5m']:,.0f}만 원</b>이 더 필요해요. 대체 돌봄 비용에 대비해 은퇴자금과 분리해 관리해요.", "warm")
    ui.note("📌 <b>딸의 근로소득은 보고서 계획에 미반영</b> — 취업 시기·소득이 불확실하기 때문이에요. "
            "자립ON의 ‘미래 자립 시뮬레이터’에서 취업 가정 시 자립자금 목표 달성 가능성을 별도로 보여줘요.", "mint")

    ui.section("SWOT", "lav_dark")
    sw = h["swot"]
    cfg = [("S", "강점 Strength", "soft-mint"), ("W", "약점 Weakness", "soft-peach"),
           ("O", "기회 Opportunity", "soft-sky"), ("T", "위협 Threat", "soft-lav")]
    cols = st.columns(2, gap="medium")
    for i, (k, t, cls) in enumerate(cfg):
        lis = "".join(f"<li>{esc(x)}</li>" for x in sw[k])
        cols[i % 2].markdown(f'<div class="card {cls}"><h4>{t}</h4><ul class="chk {"x" if k in "WT" else ""}">{lis}</ul></div>',
                             unsafe_allow_html=True)


# ═══════════════════════════ ② AI 맞춤 지원 ═══════════════════════════
@st.cache_data(show_spinner=False)
def cached_explain(profile_json: str, program_id: str, rec_json: str) -> tuple[str, bool]:
    return ai.explain_recommendation(json.loads(profile_json), PROGRAMS[program_id],
                                     SimpleNamespace(**json.loads(rec_json)))


def page_support() -> None:
    p = profile
    ui.hero("STEP 2 · AI 맞춤 지원 추천", f"{esc(p['name'])} 님께 맞는 지원을 찾았어요",
            "자격 조건은 규칙으로 꼼꼼히 확인하고, AI가 추천 이유와 다음 할 일을 쉬운 말로 알려드려요.")
    ui.stepper(1)

    recs = el.recommend(p)
    sel = get_selected(p)
    chips = " ".join(ui.badge(x, "no") for x in
                     [f"만 {p['age']}세", p["region"], p["disability_type"], p["severity"], p["employment"], f"돌봄 {p['care_need']}"])
    st.markdown(f'<div style="margin:-6px 0 10px">{chips}</div>', unsafe_allow_html=True)
    cnt = {s: sum(r.status == s for r in recs) for s in el.STATUS_ORDER}
    ui.tiles([
        ("✅ 우선 확인", f"{cnt[el.PRIORITY]}개", "조건이 잘 맞아 먼저 알아볼 제도", "mint"),
        ("🔎 추가 정보 필요", f"{cnt[el.MORE_INFO]}개", "심사·조사 등 확인이 더 필요", "butter"),
        ("💤 현재 조건과 맞지 않음", f"{cnt[el.NO_MATCH]}개", "상황이 바뀌면 다시 확인", "lav"),
    ])

    flt = st.radio("보기", ["전체", "재무적 지원", "비재무적 지원"], horizontal=True, label_visibility="collapsed")
    pjson = json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)

    for r in recs:
        prog = PROGRAMS[r.program_id]
        if flt != "전체" and prog["category"] != flt:
            continue
        with st.container(border=True):
            tlabel, tkind = ui.TYPE_BADGE[prog["support_type"]]
            badges = ui.badge(r.status, ui.STATUS_BADGE[r.status]) + ui.badge(tlabel, tkind)
            if r.in_use:
                badges += ui.badge("이용 중", "ok")
            st.markdown(f'<div class="card-title" style="flex-wrap:wrap"><div class="ico soft-peach">{prog["icon"]}</div>'
                        f'{esc(prog["name"])} <span style="margin-left:6px">{badges}</span>'
                        f'<span style="margin-left:auto;font-size:.8rem;color:#8C7B73;font-weight:500">{esc(prog["agency"])}</span></div>',
                        unsafe_allow_html=True)
            left, right = st.columns([1.35, 1], gap="large")
            with left:
                with st.spinner("AI가 추천 이유를 정리하고 있어요..."):
                    text, by_ai = cached_explain(pjson, r.program_id, json.dumps(r.__dict__, ensure_ascii=False))
                ui.ai_box(text, by_ai)
                st.markdown(f"<div style='margin-top:12px'><b>📦 지원 내용</b></div><ul class='chk x'>"
                            + "".join(f"<li>{esc(b)}</li>" for b in prog["benefits"]) + "</ul>", unsafe_allow_html=True)
                st.markdown(f'<div class="note lav" style="font-size:.85rem">🧮 <b>현금흐름 반영 방식</b> · {esc(prog["cashflow_rule"])}</div>',
                            unsafe_allow_html=True)
            with right:
                if r.reasons:
                    st.markdown("<b>맞는 조건</b><ul class='chk'>" + "".join(f"<li>{esc(x)}</li>" for x in r.reasons) + "</ul>",
                                unsafe_allow_html=True)
                if r.checks:
                    st.markdown("<b>추가로 확인할 점</b><ul class='chk q'>" + "".join(f"<li>{esc(x)}</li>" for x in r.checks)
                                + "</ul>", unsafe_allow_html=True)
                if r.future:
                    ui.note("🔮 " + esc(r.future), "mint")
                links = " · ".join(f'<a href="{l["url"]}" target="_blank">{esc(l["label"])} ↗</a>' for l in prog["links"])
                st.markdown(f"<div style='font-size:.86rem;line-height:1.8'><b>신청</b> {esc(prog['apply'])}<br>"
                            f"<b>문의</b> {esc(prog['contact'])}<br>{links}</div>", unsafe_allow_html=True)
            st.checkbox("🧮 시뮬레이터에 담기", key=f"sel_{r.program_id}", value=sel.get(r.program_id, False),
                        on_change=_toggle_sel, args=(r.program_id,))

    selected = [pid for pid in PROGRAMS if sel.get(pid)]
    warns = el.overlap_warnings(p, selected)
    if warns:
        ui.section("함께 이용할 때 주의할 점", "butter_dark")
        for w in warns:
            ui.note("⚠️ " + esc(w), "warm")
    ui.note("ⓘ " + esc(PROGRAMS_DB["meta"]["notice"]), "lav")

    ui.section("AI 길잡이에게 물어보기", "lav_dark", "공식 안내 자료 범위 안에서 답해요")
    hist = st.session_state.setdefault("qa_history", [])
    for q, a, by_ai in hist[-6:]:
        with st.chat_message("user", avatar="🙋"):
            st.write(q)
        with st.chat_message("assistant", avatar="🌱"):
            st.markdown(a)
            if not by_ai:
                st.caption("규칙 기반 답변 (AI 연결 시 더 자세히 답해요)")
    ex = ["장애인연금은 취업하면 어떻게 돼요?", "주간활동서비스 신청은 어디서 해요?", "근로지원인은 언제 신청할 수 있어요?"]
    ec = st.columns(3)
    preset = None
    for i, e in enumerate(ex):
        if ec[i].button(e, key=f"qa_ex_{i}", width="stretch"):
            preset = e
    with st.form("qa", clear_on_submit=True):
        a, b = st.columns([5, 1])
        q = a.text_input("질문", placeholder="궁금한 점을 쉬운 말로 물어보세요", label_visibility="collapsed")
        ask = b.form_submit_button("물어보기", type="primary", width="stretch")
    question = preset or (q if ask and q.strip() else None)
    if question:
        with st.spinner("공식 자료를 찾아보고 있어요..."):
            ans, by_ai = ai.answer_question(question, p, list(PROGRAMS.values()))
        hist.append((question, ans, by_ai))
        st.rerun()

    st.write("")
    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button("← 진단으로", on_click=go_page, args=(0,), width="stretch")
    c3.button("미래 자립 시뮬레이터 →", type="primary", on_click=go_page, args=(2,), width="stretch")


# ═══════════════════════════ ③ 미래 자립 시뮬레이터 ═══════════════════════════
def page_simulator() -> None:
    p, sd = profile, st.session_state.sim
    ui.hero("STEP 3 · 미래 자립 시뮬레이터", "지원을 받으면, 나의 내일은 얼마나 달라질까요?",
            "지원 적용 전후 현금흐름을 비교하고, 남는 돈을 예금·적금으로 모았을 때 2037년 자립 목표에 얼마나 가까워지는지 확인해요.")
    ui.stepper(2)

    with st.expander("📐 자립ON 계산 원칙 4가지 (꼭 읽어주세요)"):
        st.markdown("""
1. **지원 대상 여부 ≠ 실제 수급 확정** — 수급이 확인되지 않은 지원금은 ‘가정 시나리오’로만 계산해요.
2. **현금지원 ≠ 서비스 지원** — 활동지원·주간활동·근로지원인의 금전적 가치는 수입이 아니에요. 실제로 줄어든 본인 부담 비용만 지출 감소로 반영해요.
3. **저축 원금의 이동 ≠ 자산 증가** — 예·적금에 넣은 돈은 이미 내 돈이에요. 새로 늘어나는 건 이자뿐이에요.
4. **변경 가능성 표시** — 장기 예측은 지원금이 계속 지급된다는 가정이에요. 소득이 바뀌면 수급이 달라질 수 있어요.
""")

    sel = get_selected(p)
    selected = [pid for pid in PROGRAMS if sel.get(pid)]

    # ── ① 시나리오 설정 ──
    ui.section("① 시나리오 설정", "coral", f"기준월 {TODAY.year}.{TODAY.month:02d}")
    supports: list[fin.SupportItem] = []
    assumed_names: list[str] = []
    with st.container(border=True):
        years = st.segmented_control("분석 기간", [1, 3, 5], default=5, format_func=lambda y: f"{y}년", key="sim_years") or 5
        months = years * 12
        st.markdown("**선택한 지원제도** <span style='color:#8C7B73;font-size:.85rem'>(② AI 맞춤 지원에서 담은 제도)</span>",
                    unsafe_allow_html=True)
        if not selected:
            ui.note("아직 담은 지원제도가 없어요. ② AI 맞춤 지원에서 ‘시뮬레이터에 담기’를 눌러 보세요.", "warm")
        for pid in selected:
            prog = PROGRAMS[pid]
            in_use = pid in p["using_programs"]
            tlabel, tkind = ui.TYPE_BADGE[prog["support_type"]]
            head = f'{prog["icon"]} <b>{esc(prog["name"])}</b> {ui.badge(tlabel, tkind)}' + (ui.badge("이용 중", "ok") if in_use else "")
            with st.container(border=True):
                st.markdown(head, unsafe_allow_html=True)
                if prog["support_type"] == "cash":
                    if in_use:
                        st.caption("✔ 수급 중인 금액이 이미 ‘월 수입’에 반영되어 있어요. (중복으로 더하지 않아요)")
                        if st.checkbox("⚠️ 수급이 중단되는 경우도 보기 (소득인정액 변화 등)", key=f"sim_stop_{pid}"):
                            amt = next((i["amount"] for i in p["income_items"] if prog["name"] in i["name"]), prog["default_amount"])
                            off = st.slider("몇 개월 뒤 중단된다고 가정할까요?", 0, months, min(24, months), key=f"sim_stopoff_{pid}")
                            supports.append(fin.SupportItem(prog["name"] + " 중단", "cash", -int(amt), off))
                            assumed_names.append(f"{prog['name']} {off}개월 후 중단")
                    else:
                        a, b, c = st.columns(3)
                        amt = a.number_input("가정한 월 지원액(원)", 0, 2_000_000, prog["default_amount"], 10000, key=f"sim_amt_{pid}")
                        off = b.number_input("몇 개월 뒤부터", 0, months, 3, key=f"sim_off_{pid}",
                                             help="신청·심사 기간을 고려해 지급 시작 시점을 정해요")
                        dur = c.selectbox("지급 기간", ["계속 지급 가정", "12개월", "24개월", "36개월"], key=f"sim_dur_{pid}")
                        conf = st.checkbox("수급이 확정되었어요", key=f"sim_conf_{pid}")
                        supports.append(fin.SupportItem(prog["name"], "cash", int(amt), int(off),
                                                        None if dur.startswith("계속") else int(dur[:2]), conf))
                        if not conf:
                            assumed_names.append(prog["name"])
                            st.markdown(ui.badge("가정 시나리오 · 실제 지급액 아님", "assume"), unsafe_allow_html=True)
                elif prog["support_type"] == "care":
                    st.caption("현금 수입으로 계산하지 않아요. " + ("본인부담금은 이미 월 지출에 반영되어 있어요. " if in_use else "")
                               + "이 서비스 덕분에 **직접 내던 돌봄 비용이 줄어드는 경우에만** 입력하세요.")
                    red = st.number_input("실제로 줄어드는 월 돌봄 비용(원)", 0, 3_000_000, 0, 10000, key=f"sim_red_{pid}")
                    if red:
                        supports.append(fin.SupportItem(prog["name"], "expense", int(red)))
                else:
                    st.caption("취업지원·근로지원인은 수입이 아니에요. 아래 **취업 가정**에서 예상 급여를 따로 입력해요.")

        if st.toggle("➕ 가상 현금지원 시나리오 추가 (기획서 예시: 월 35만 원)", key="sim_virtual"):
            a, b = st.columns(2)
            vamt = a.number_input("가상 월 현금지원액(원)", 0, 2_000_000, 350_000, 10000, key="sim_vamt")
            voff = b.number_input("몇 개월 뒤부터", 0, months, 0, key="sim_voff")
            supports.append(fin.SupportItem("가상 현금지원", "cash", int(vamt), int(voff)))
            assumed_names.append("가상 현금지원")

        st.markdown("---")
        has_job_default = sd.get("job_start_year") is not None
        job = None
        if st.toggle("💼 취업 가정 반영하기", value=has_job_default, key="sim_job_on",
                     help="취업지원 효과가 아니라, 취업했을 때를 가정한 별도 시나리오예요"):
            a, b, c, d, e = st.columns(5)
            jy = a.number_input("취업 연도", TODAY.year, 2040, sd.get("job_start_year") or TODAY.year + 1, key="sim_jy")
            jm = b.number_input("취업 월", 1, 12, sd.get("job_start_month") or 3, key="sim_jm")
            sal = c.number_input("예상 월 급여(세후, 원)", 0, 10_000_000, sd.get("expected_salary") or 1_200_000, 50_000, key="sim_sal")
            ext = d.number_input("늘어나는 지출(원)", 0, 3_000_000, sd.get("job_extra_expense") or 0, 10_000, key="sim_ext",
                                 help="출퇴근 교통비·식비 등")
            ended_default = int(sum(i["amount"] for i in p["expense_items"] if i.get("ends_on_job")))
            end = e.number_input("끝나는 지출(원)", 0, 3_000_000, ended_default, 10_000, key="sim_end",
                                 help="취업하면 더 이상 내지 않는 비용 (예: 직업훈련비)")
            joff = fin.months_between(TODAY.year, TODAY.month, int(jy), int(jm))
            job = fin.JobAssumption(joff, int(sal), int(ext), int(end))
            if "disability_pension" in p["using_programs"]:
                ui.note("⚠️ 취업 후 근로소득이 생기면 장애인연금 소득인정액이 달라져요. 근로소득은 공제 후 반영되지만, "
                        "수급 변화를 보려면 위 ‘수급이 중단되는 경우도 보기’를 함께 켜 보세요.", "warm")

    df = fin.project_cashflow(TODAY.year, TODAY.month, months, p["monthly_income"], p["monthly_expense"], supports, job)
    steady_after = max([s.start_offset for s in supports if s.amount > 0] + [0])
    steady_after = min(steady_after, months - 1)
    before_m = int(df["before_surplus"].iloc[0])
    after_m = int(df["after_surplus"].iloc[steady_after])
    job_m = int(df["job_surplus"].iloc[min(job.start_offset, months - 1)]) if job else None
    if job and job.start_offset >= months:
        job_m = None

    # ── ② 지원 전후 현금흐름 ──
    ui.section("② 지원 적용 전후 현금흐름", "coral", "매달 남는 돈 = 수입 − 지출")
    first_year_gain = int(df["after_surplus"].iloc[:12].sum() - df["before_surplus"].iloc[:12].sum())
    tiles = [
        ("현재 월 잉여자금", man(before_m), "지금 상태 그대로", "lav"),
        ("지원 적용 후 월 잉여자금", man(after_m), f"{'+' if after_m >= before_m else ''}{man(after_m - before_m)}", "peach"),
    ]
    if job_m is not None:
        tiles.append(("취업 후 월 잉여자금", man(job_m), f"{TODAY.year + (TODAY.month - 1 + job.start_offset)//12}년부터 · 가정", "mint"))
    tiles.append(("1년간 지원으로 더 생기는 돈", ("+" if first_year_gain >= 0 else "") + man(first_year_gain), "첫 12개월 · 취업 효과 제외", "butter"))
    ui.tiles(tiles)
    if assumed_names:
        st.markdown(ui.badge("가정 포함", "assume") + f"<span style='font-size:.85rem;color:#8C7B73'> {esc(', '.join(assumed_names))} — 실제 수급·지급액이 아닌 가정값이에요.</span>",
                    unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1.6], gap="medium")
    with c1, st.container(border=True):
        st.markdown("**월 잉여자금 비교**")
        names = ["지원 전", "지원 후"] + (["취업 후"] if job_m is not None else [])
        vals = [before_m, after_m] + ([job_m] if job_m is not None else [])
        cols = [SERIES["before"], SERIES["after"], SERIES["job"]][:len(vals)]
        fig = go.Figure(go.Bar(x=names, y=vals, marker=dict(color=cols, cornerradius=12),
                               text=[man(v) for v in vals], textposition="outside",
                               hovertemplate="%{x}: %{y:,}원<extra></extra>"))
        fig = ui.plotly_layout(fig, 320, legend=False)
        fig.update_yaxes(tickformat=",.0f", ticksuffix="원", range=[min(0, min(vals)) * 1.2, max(vals + [1]) * 1.25])
        st.plotly_chart(fig, width="stretch")
    with c2, st.container(border=True):
        st.markdown(f"**누적 잉여자금 추이** ({years}년)")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date"], y=df["before_cum"], name="지원 전", line=dict(color=SERIES["before"], width=3, dash="dot")))
        fig.add_trace(go.Scatter(x=df["date"], y=df["after_cum"], name="지원 후", line=dict(color=SERIES["after"], width=3)))
        if job:
            fig.add_trace(go.Scatter(x=df["date"], y=df["job_cum"], name="지원 + 취업 가정", line=dict(color=SERIES["job"], width=3),
                                     fill="tonexty", fillcolor="rgba(111,183,154,.12)"))
        fig = ui.plotly_layout(fig, 320)
        fig.update_traces(hovertemplate="%{x|%Y.%m} · %{y:,.0f}원")
        fig.update_yaxes(tickformat=",.0f")
        fig.update_xaxes(tickformat="%Y.%m")
        st.plotly_chart(fig, width="stretch")

    ht = fin.horizon_totals(df, tuple(y for y in (1, 3, 5) if y <= years))
    tbl = pd.DataFrame([{"기간": f"{h['years']}년", "지원 전": man(h["before"]), "지원 후": man(h["after"]),
                         "지원 효과": ("+" if h["after"] >= h["before"] else "") + man(h["after"] - h["before"]),
                         **({"지원 + 취업 가정": man(h["job"])} if job else {})} for h in ht])
    st.dataframe(tbl, hide_index=True, width="stretch")
    with st.expander("📅 연도별 현금흐름 자세히 보기"):
        ys = fin.yearly_summary(df)
        st.dataframe(pd.DataFrame({
            "연도": ys["year"].astype(str) + "년", "개월": ys["months"],
            "지원 전 잉여": ys["before_surplus"].map(man), "지원 후 잉여": ys["after_surplus"].map(man),
            "현금지원 합계": ys["cash_support"].map(man), "돌봄비 절감 합계": ys["expense_saving"].map(man),
            **({"지원+취업 잉여": ys["job_surplus"].map(man)} if job else {})}), hide_index=True, width="stretch")

    # ── ③ 예금·적금 운용 ──
    ui.section("③ 예금·적금 운용 시뮬레이션", "mint_dark", "매달 남는 돈 → 적금 · 이미 가진 목돈 → 예금")
    capacity = max(job_m if job_m is not None else after_m, after_m, 0)
    with st.container(border=True):
        a, b, c, d = st.columns([1.4, 1, 1, 1])
        max_save = max(capacity, 10_000)
        default_save = min(p["monthly_saving_wish"], capacity)
        save = a.slider("매달 저축할 금액 (원)", 0, int(max_save), int(default_save), 10_000, key="sim_save",
                        help=f"월 잉여자금({man(capacity)}) 범위 안에서 정해요")
        a.caption(f"👉 매달 **{man(save)}** 저축 · 잉여자금의 {save / capacity * 100 if capacity else 0:.0f}%")
        period = b.selectbox("적금·예금 기간", [12, 24, 36], index=0, format_func=lambda m: f"{m}개월", key="sim_period")
        sav_rate = c.number_input("적금 금리(연 %, 가정)", 0.0, 10.0, 3.0, 0.1, key="sim_sr") / 100
        dep_rate = d.number_input("예금 금리(연 %, 가정)", 0.0, 10.0, 2.8, 0.1, key="sim_dr") / 100
        a, b = st.columns([1.4, 3])
        lump = a.number_input("예금에 넣을 목돈(원)", 0, 10**10, p["savings"], 100_000, key="sim_lump",
                              help="이미 가진 돈만 넣어요. 앞으로 받을 지원금을 미리 목돈처럼 계산하지 않아요")
        b.markdown(f"<div class='note mint' style='margin-top:26px'>💡 금리는 가정값이에요. 실제 은행별 최신 금리는 "
                   f"<a href='https://finlife.fss.or.kr' target='_blank'>금융감독원 금융상품 한눈에 ↗</a>에서 비교해 보세요.</div>",
                   unsafe_allow_html=True)
        if p["monthly_saving_wish"] > capacity:
            ui.note(f"⚠️ 희망 저축액 {man(p['monthly_saving_wish'])}이 예상 월 잉여자금 {man(capacity)}보다 많아요. "
                    "남는 돈 범위 안에서 저축액을 정했어요.", "warm")

    plans = fin.compare_plans(int(save), int(lump), int(period), sav_rate, dep_rate)
    c1, c2 = st.columns([1.7, 1], gap="medium")
    with c1, st.container(border=True):
        st.markdown(f"**운용방안 비교** · {period}개월 후")
        best = max((x.net_interest for x in plans), default=0)
        td = "padding:8px 6px;border-top:1px solid #F4E9E1;text-align:right"
        rows = ""
        for x in plans:
            star = " 🌟" if x.net_interest == best and best > 0 else ""
            rows += (f"<tr><td style='{td};text-align:left'><b>{esc(x.product)}</b>{star}"
                     f"<div style='font-size:.75rem;color:#8C7B73'>{esc(x.note)}</div></td>"
                     f"<td style='{td}'>{x.principal:,}</td><td style='{td}'>{x.gross_interest:,}</td>"
                     f"<td style='{td}'>{x.tax:,}</td>"
                     f"<td style='{td};color:{COLORS['mint_dark']};font-weight:800'>+{x.net_interest:,}</td>"
                     f"<td style='{td};font-weight:800'>{x.maturity:,}</td></tr>")
        st.markdown(f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:.88rem;min-width:480px'>"
                    f"<thead><tr style='color:#8C7B73;text-align:right'><th style='text-align:left'>방안</th><th>원금</th><th>세전이자</th>"
                    f"<th>세금(15.4%)</th><th>세후이자</th><th>만기금액</th></tr></thead><tbody>{rows}</tbody></table></div>",
                    unsafe_allow_html=True)
        st.caption("단리 기준 · 적금 이자 = 월납입액 × 연이율/12 × n(n+1)/2 · 비과세종합저축은 별도 상품이 아니라 "
                   "요건(장애인 등)을 충족한 저축에 적용되는 세제 혜택이며, 1인당 원금 5,000만 원 한도로 가정 (적용기한 연장 여부 확인 필요)")
    with c2, st.container(border=True):
        st.markdown("**원금(내 돈) vs 이자(새로 생긴 돈)**")
        fig = go.Figure()
        short = [x.product.replace(" (일반과세)", "<br>일반").replace(" (비과세 가정)", "<br>비과세") for x in plans]
        fig.add_trace(go.Bar(x=short, y=[x.principal for x in plans], name="원금 (이미 내 돈)", marker=dict(color=COLORS["peach"], cornerradius=8)))
        fig.add_trace(go.Bar(x=short, y=[x.net_interest for x in plans], name="세후 이자 (순자산 증가)", marker=dict(color=COLORS["coral"], cornerradius=8)))
        fig = ui.plotly_layout(fig, 330)
        fig.update_layout(barmode="stack")
        fig.update_traces(hovertemplate="%{x}: %{y:,}원")
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig, width="stretch")
    inst = next((x for x in plans if x.product == "정기적금 (비과세 가정)"), None)
    inst_g = next((x for x in plans if x.product == "정기적금 (일반과세)"), None)
    if inst and inst_g and save > 0:
        ui.note(f"🧺 적금에 {period}개월 동안 넣는 <b>{man(inst.principal)}</b>은 이미 내 잉여자금이 옮겨간 것이에요. "
                f"순자산을 새로 늘리는 건 이자 <b>{inst_g.net_interest:,}원</b>(일반과세)이고, 비과세 요건을 충족하면 "
                f"<b>{inst.net_interest - inst_g.net_interest:,}원</b>을 더 받을 수 있어요.", "mint")

    # ── ④ 자립 목표 ──
    goal_off = fin.months_between(TODAY.year, TODAY.month, p["goal_year"], 1)
    ui.section(f"④ {p['goal_year']}년 자립 초기자금 목표", "butter_dark", f"{goal_off}개월 · 목표 {man(p['goal_amount'])}")
    with st.container(border=True):
        a, b, c = st.columns(3)
        inc_self = a.toggle("본인 저축 포함 (취업 후 남는 돈에서)", value=True, key="sim_goal_self")
        tax_free = b.toggle("비과세 요건 충족 가정", value=False, key="sim_goal_tf")
        goal_rate = c.number_input("장기 적립 금리(연 %, 가정)", 0.0, 10.0, 3.0, 0.1, key="sim_gr") / 100
    long_df = fin.project_cashflow(TODAY.year, TODAY.month, max(goal_off, 1), p["monthly_income"], p["monthly_expense"], supports, job)
    surplus_col = "job_surplus" if job else "after_surplus"
    fam_list = [p.get("family_monthly_saving", 0)] * goal_off
    self_list = [min(int(save), max(0, int(s))) if inc_self else 0 for s in long_df[surplus_col].tolist()[:goal_off]]
    contrib = [f + s for f, s in zip(fam_list, self_list)]
    gp = fin.goal_projection(p["savings"], contrib, goal_off, goal_rate, tax_free)
    gp["family_cum"] = [0] + list(pd.Series(fam_list).cumsum())
    gp["self_cum"] = p["savings"] + pd.Series([0] + self_list).cumsum()
    gp["label"] = [pd.Timestamp(year=fin._month_label(TODAY.year, TODAY.month, m)[0],
                                month=fin._month_label(TODAY.year, TODAY.month, m)[1], day=1) for m in gp["offset"]]
    final = gp.iloc[-1]
    # 목표 달성에 필요한 본인 월 저축액 (취업 후 저축 가능한 달 기준, 선형)
    base_only = fin.goal_projection(p["savings"], fam_list, goal_off, goal_rate, tax_free).iloc[-1]["balance"]
    can_months = [1 if (s > 0) else 0 for s in long_df[surplus_col].tolist()[:goal_off]]
    unit = fin.goal_projection(0, can_months, goal_off, goal_rate, tax_free).iloc[-1]["balance"]
    need_self = max(0, int(round((p["goal_amount"] - base_only) / unit, -3))) if unit > 0 else None
    gap = final["balance"] - p["goal_amount"]
    ui.tiles([
        (f"{p['goal_year']}년 예상 적립액", man(final["balance"]), "가족 적립 + 본인 저축 + 이자", "butter"),
        ("목표 대비", ("+" if gap >= 0 else "") + man(gap), "🎉 목표 달성 예상" if gap >= 0 else "조금 더 필요해요", "mint" if gap >= 0 else "peach"),
        ("가족 적립만 했을 때", man(base_only), f"월 {man(p.get('family_monthly_saving', 0))} 적립 기준", "lav"),
        ("목표에 필요한 본인 월 저축", man(need_self) if need_self is not None else "-", "취업 후 저축 가능한 달 기준", "sky"),
    ])
    with st.container(border=True):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=gp["label"], y=gp["family_cum"], name="가족 적립 원금", stackgroup="one",
                                 line=dict(width=0), fillcolor="rgba(201,182,228,.75)"))
        fig.add_trace(go.Scatter(x=gp["label"], y=gp["self_cum"], name="본인 저축 원금", stackgroup="one",
                                 line=dict(width=0), fillcolor="rgba(247,185,161,.8)"))
        fig.add_trace(go.Scatter(x=gp["label"], y=gp["interest"], name="이자 (새로 생긴 돈)", stackgroup="one",
                                 line=dict(width=0), fillcolor="rgba(111,183,154,.85)"))
        fig.add_hline(y=p["goal_amount"], line=dict(color=COLORS["coral_dark"], dash="dash", width=2),
                      annotation_text=f"목표 {man(p['goal_amount'])}", annotation_position="top left",
                      annotation_font=dict(color=COLORS["coral_dark"]))
        if job and job.start_offset < goal_off:
            fig.add_vline(x=gp["label"].iloc[job.start_offset], line=dict(color=SERIES["job"], dash="dot"))
            fig.add_annotation(x=gp["label"].iloc[job.start_offset], y=final["balance"], text=" 💼 취업 가정",
                               showarrow=False, font=dict(color=COLORS["mint_dark"]), xanchor="left", yanchor="top")
        fig = ui.plotly_layout(fig, 360)
        fig.update_traces(hovertemplate="%{x|%Y.%m} · %{y:,.0f}원")
        fig.update_yaxes(tickformat=",.0f")
        fig.update_xaxes(tickformat="%Y")
        st.plotly_chart(fig, width="stretch")
        st.caption("장기 적립은 만기 재예치를 월 단위 세후 복리로 근사했어요. 본인 저축은 매달 잉여자금이 있는 달에만, "
                   "설정한 저축액 한도 안에서 넣는다고 가정해요.")
    if gap < 0 and need_self:
        ui.note(f"💡 가족 적립만으로는 {man(p['goal_amount'] - base_only)}이 부족해요. 취업 후 매달 약 <b>{man(need_self)}</b>씩 "
                f"본인이 함께 모으면 {p['goal_year']}년 목표에 닿을 수 있어요.", "warm")

    # ── ⑤ 자립 이후 생활 ──
    pls = p.get("parent_living_support", 0)
    yrs = p.get("parent_support_years", 0)
    ui.section(f"⑤ 자립 이후 한 달 살림 ({p['goal_year']}~{p['goal_year'] + max(yrs, 1) - 1})", "lav_dark", "독립 생활 시 월 수지 가정")
    with st.container(border=True):
        a, b, c, d = st.columns(4)
        living = a.number_input("독립 생활비(월, 원)", 0, 10_000_000, sd.get("independent_living_cost", 1_500_000), 50_000, key="sim_live",
                                help="주거·식비·공과금·활동지원 본인부담 등")
        sal_after = b.number_input("근로소득(월, 원, 가정)", 0, 10_000_000, job.salary if job else 0, 50_000, key="sim_sal2")
        pension_amt = next((i["amount"] for i in p["income_items"] if "장애인연금" in i["name"]), 0)
        keep_p = c.toggle("장애인연금 계속 수급 가정", value=pension_amt > 0, key="sim_keep_p")
        pls_in = d.number_input("가족 생활지원(월, 원)", 0, 10_000_000, pls, 10_000, key="sim_pls")
    inc_parts = {"근로소득(가정)": sal_after, "장애인연금": pension_amt if keep_p else 0, "가족 생활지원": pls_in}
    total_in = sum(inc_parts.values())
    c1, c2 = st.columns([1.4, 1], gap="medium")
    with c1, st.container(border=True):
        fig = go.Figure()
        palette = [SERIES["job"], COLORS["coral"], "#C9B6E4"]
        for (k, v), col in zip(inc_parts.items(), palette):
            fig.add_trace(go.Bar(x=["들어오는 돈"], y=[v], name=k, marker=dict(color=col), text=man(v) if v else "", textposition="inside"))
        fig.add_trace(go.Bar(x=["나가는 돈"], y=[living], name="독립 생활비", marker=dict(color="#E3D3C8"), text=man(living), textposition="inside"))
        fig = ui.plotly_layout(fig, 320)
        fig.update_layout(barmode="stack")
        fig.update_traces(hovertemplate="%{y:,}원")
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig, width="stretch")
    with c2:
        diff = total_in - living
        ui.tiles([("자립 후 매달 남는 돈", man(diff), "들어오는 돈 − 독립 생활비", "mint" if diff >= 0 else "peach"),
                  ("가족 생활지원 총액", man(pls_in * 12 * yrs), f"월 {man(pls_in)} × {yrs}년 (부모 측 별도 준비)", "lav")])
        if pls_in and diff - pls_in < 0:
            ui.note(f"가족 생활지원이 없다면 매달 {man(-(diff - pls_in))}이 부족해요. 생활지원 종료 시점"
                    f"({p['goal_year'] + yrs}년) 이전에 근로소득 유지와 저축으로 대비가 필요해요.", "warm")
        st.caption("가족 생활지원 8,400만 원은 부모의 은퇴생활자금(2순위)과 함께 부모 재무계획에서 별도로 검토해요.")

    # ── ⑥ AI 설명 · 모니터링 ──
    ui.section("⑥ AI 길잡이의 쉬운 설명", "coral")
    summary = dict(before_monthly=before_m, after_monthly=after_m, job_monthly=job_m, assumptions=assumed_names,
                   monthly_saving=int(save), goal_year=p["goal_year"], goal_amount=p["goal_amount"],
                   goal_balance=int(final["balance"]), goal_interest=int(final["interest"]),
                   family_only_balance=int(base_only), need_self_monthly=need_self,
                   after_independence_monthly=int(diff))
    if st.button("✨ 결과를 쉬운 말로 설명해 주세요", type="primary"):
        with st.spinner("결과를 쉽게 풀어 쓰고 있어요..."):
            st.session_state.sim_ai = ai.explain_simulation(summary)
    if "sim_ai" in st.session_state:
        ui.ai_box(*st.session_state.sim_ai)

    ui.section("정기 점검 체크리스트 (재무설계 6단계 · 모니터링)", "mint_dark")
    checks = [
        ("매년 1월", "장애인연금 기준액·선정기준액 고시 확인, 소득인정액 변화 점검"),
        ("취업 시", "주간활동서비스 이용 제한 여부 확인 → 근로지원인 신청 검토"),
        ("취업 후 6개월", "실제 급여·지출로 시뮬레이션 다시 하기, 저축액 조정"),
        ("적금 만기마다", "만기금을 자립자금 계좌로 재예치, 비과세 한도(5,000만 원) 확인"),
        ("2031년", "아버지 퇴직 — 가족 적립(월 20만 원) 지속 가능 여부 재점검"),
    ]
    st.markdown('<div class="card">' + "".join(
        f'<div style="display:flex;gap:14px;padding:8px 0;border-bottom:1px dashed #F1E2D6">'
        f'<span class="badge b-care" style="min-width:96px;text-align:center">{w}</span><span>{esc(t)}</span></div>'
        for w, t in checks) + "</div>", unsafe_allow_html=True)

    report = make_report(p, summary, plans, period, supports)
    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button("← AI 맞춤 지원", on_click=go_page, args=(1,), width="stretch")
    c3.download_button("📄 내 자립설계 요약 받기", report, file_name="자립ON_자립설계_요약.md", mime="text/markdown",
                       type="primary", width="stretch")


def make_report(p: dict, s: dict, plans, period: int, supports) -> str:
    lines = [f"# 자립ON 자립설계 요약 — {p['name']} 님", f"기준월: {TODAY.year}.{TODAY.month:02d}", "",
             "## 현재 상태", f"- 월 수입 {man(p['monthly_income'])} / 월 지출 {man(p['monthly_expense'])}",
             f"- 이용 중 제도: {', '.join(PROGRAMS[x]['name'] for x in p['using_programs']) or '없음'}", "",
             "## 추천 지원제도"]
    for r in el.recommend(p):
        lines.append(f"- [{r.status}] {PROGRAMS[r.program_id]['name']} — {PROGRAMS[r.program_id]['apply']}")
    lines += ["", "## 현금흐름", f"- 현재 월 잉여 {man(s['before_monthly'])} → 지원 후 {man(s['after_monthly'])}"
              + (f" → 취업 후(가정) {man(s['job_monthly'])}" if s["job_monthly"] is not None else ""),
              f"- 가정 항목: {', '.join(s['assumptions']) or '없음'}", "", f"## 예·적금 ({period}개월)"]
    for x in plans:
        lines.append(f"- {x.product}: 원금 {x.principal:,}원, 세후이자 {x.net_interest:,}원, 만기 {x.maturity:,}원")
    lines += ["", f"## {s['goal_year']}년 자립 목표", f"- 목표 {man(s['goal_amount'])} / 예상 {man(s['goal_balance'])}",
              f"- 필요 본인 월 저축(취업 후): {man(s['need_self_monthly']) if s['need_self_monthly'] is not None else '-'}",
              "", "> 본 결과는 가정에 기반한 시뮬레이션이며 수급 여부를 확정하지 않습니다. 공식 기관에서 확인하세요."]
    return "\n".join(lines)


# ─────────────────────────── 라우팅 ───────────────────────────
[page_diagnosis, page_support, page_simulator][page_idx]()
st.markdown('<div class="footer">자립ON · AFPK 영 플래너 챌린지 MVP · 지원제도 정보는 공식 기관 안내를 바탕으로 정리했으며 '
            '수급 여부를 확정하지 않습니다 · 🌱</div>', unsafe_allow_html=True)
