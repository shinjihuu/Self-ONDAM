"""자립설계 요약 PDF — 한눈에 보는 파스텔톤 보고서 (fpdf2 + 나눔고딕).

build_pdf(data) → bytes. data는 app.py의 make_report_data()가 만든다.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

INK = (74, 59, 53)
MUTED = (140, 123, 115)
LINE = (241, 226, 214)
CORAL = (210, 105, 75)
PEACH = (255, 241, 234)
MINT = (238, 248, 243)
MINT_D = (78, 156, 125)
LAV = (244, 239, 251)
LAV_D = (126, 107, 176)
BUTTER = (255, 248, 225)
BUTTER_D = (185, 138, 30)
SKY = (238, 245, 252)
GRAY_BG = (243, 238, 234)

STATUS_STYLE = {
    "우선 확인": ((205, 235, 221), (47, 122, 93)),
    "추가 정보 필요": ((255, 240, 199), (154, 113, 16)),
    "현재 조건과 맞지 않음": ((239, 231, 226), MUTED),
}


def won(x: float) -> str:
    v = x / 10_000
    if abs(v) >= 100 or float(v).is_integer():
        return f"{v:,.0f}만 원"
    return f"{v:,.1f}만 원"


class Report(FPDF):
    def __init__(self, title: str):
        super().__init__("P", "mm", "A4")
        self.title_text = title
        self.add_font("N", "", str(FONT_DIR / "NanumGothic-Regular.ttf"))
        self.add_font("N", "B", str(FONT_DIR / "NanumGothic-Bold.ttf"))
        self.set_auto_page_break(True, margin=16)
        self.set_margins(14, 14, 14)

    def normalize_text(self, text):
        # 나눔고딕에 없는 기호를 비슷한 글자로 바꾼다
        for k, v in {"−": "-", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"'}.items():
            text = text.replace(k, v)
        return super().normalize_text(text)

    def footer(self):
        self.set_y(-11)
        self.set_font("N", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "자립ON · 가정에 기반한 시뮬레이션이며 수급 여부를 확정하지 않습니다. 신청 전 공식 기관에서 확인하세요.",
                  align="L")
        self.set_x(-30)
        self.cell(16, 5, f"{self.page_no()} / {{nb}}", align="R")

    # ── 그리기 도구 ──
    def box(self, x, y, w, h, fill, r=3):
        self.set_fill_color(*fill)
        self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=r)

    def text_at(self, x, y, txt, size=9, bold=False, color=INK, w=0, align="L", link=""):
        self.set_xy(x, y)
        self.set_font("N", "B" if bold else "", size)
        self.set_text_color(*color)
        self.cell(w, size * 0.45, txt, align=align, link=link)

    def section(self, title: str, color=CORAL, need: float = 30):
        if self.get_y() + need > self.h - 18:
            self.add_page()
        y = self.get_y() + 3
        self.set_fill_color(*color)
        self.ellipse(self.l_margin, y + 1.2, 2.6, 2.6, style="F")
        self.text_at(self.l_margin + 5, y, title, 11.5, True)
        self.set_y(y + 8)


def _tiles(pdf: Report, items: list[tuple[str, str, str, tuple]]):
    x0, y = pdf.l_margin, pdf.get_y()
    gap = 3
    w = (pdf.w - pdf.l_margin - pdf.r_margin - gap * (len(items) - 1)) / len(items)
    for i, (lab, val, sub, (bg, fg)) in enumerate(items):
        x = x0 + i * (w + gap)
        pdf.box(x, y, w, 21, bg)
        pdf.text_at(x + 3.5, y + 3, lab, 7.5, color=MUTED)
        pdf.text_at(x + 3.5, y + 8, val, 13, True, fg)
        pdf.text_at(x + 3.5, y + 15.3, sub, 6.8, color=MUTED, w=w - 6)
    pdf.set_y(y + 24)


def _programs(pdf: Report, rows: list[dict]):
    cols = [("판정", 24), ("제도", 50), ("월 지원액 · 본인부담", 46), ("신청 · 문의", 48), ("링크", 14)]
    x0 = pdf.l_margin
    y = pdf.get_y()
    pdf.set_draw_color(*LINE)
    x = x0
    for name, w in cols:
        pdf.text_at(x + 1, y, name, 7.5, True, MUTED, w=w)
        x += w
    y += 5
    pdf.line(x0, y, pdf.w - pdf.r_margin, y)
    for r in rows:
        pdf.set_font("N", "", 7.6)
        apply_lines = pdf.multi_cell(cols[3][1] - 2, 3.6, r["apply"], dry_run=True, output="LINES", align="L")
        amount_lines = pdf.multi_cell(cols[2][1] - 2, 3.6, r["amount_text"], dry_run=True, output="LINES", align="L")
        h = max(10, 3.6 * max(len(apply_lines), len(amount_lines), 2) + 3.5)
        if y + h > pdf.h - 18:
            pdf.add_page()
            y = pdf.get_y()
        bg, fg = STATUS_STYLE.get(r["status"], STATUS_STYLE["추가 정보 필요"])
        label = {"현재 조건과 맞지 않음": "해당 안 됨"}.get(r["status"], r["status"])
        pdf.box(x0 + 1, y + 2, cols[0][1] - 3, 5.2, bg, r=2.5)
        pdf.text_at(x0 + 1, y + 3.1, label, 6.8, True, fg, w=cols[0][1] - 3, align="C")
        x = x0 + cols[0][1]
        pdf.text_at(x + 1, y + 2, r["name"], 8.4, True, w=cols[1][1] - 2)
        pdf.text_at(x + 1, y + 6.2, r["category"] + (" · 이용 중" if r.get("in_use") else ""), 6.8, color=MUTED, w=cols[1][1] - 2)
        x += cols[1][1]
        pdf.set_xy(x + 1, y + 2)
        pdf.set_font("N", "B" if r.get("amount") else "", 7.6)
        pdf.set_text_color(*(MINT_D if r.get("amount") else INK))
        pdf.multi_cell(cols[2][1] - 2, 3.6, r["amount_text"], align="L")
        x += cols[2][1]
        pdf.set_xy(x + 1, y + 2)
        pdf.set_font("N", "", 7.6)
        pdf.set_text_color(*INK)
        pdf.multi_cell(cols[3][1] - 2, 3.6, r["apply"], align="L")
        x += cols[3][1]
        if r.get("url"):
            pdf.text_at(x + 1, y + 3, "바로가기", 7.2, True, CORAL, w=cols[4][1] - 1, link=r["url"])
        y += h
        pdf.line(x0, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 2)


def _bars(pdf: Report, items: list[tuple[str, int, tuple]], unit_max: int | None = None):
    x0, y = pdf.l_margin, pdf.get_y()
    label_w, total_w = 26, pdf.w - pdf.l_margin - pdf.r_margin - 26 - 26
    mx = unit_max or max([abs(v) for _, v, _ in items] + [1])
    for lab, v, color in items:
        pdf.text_at(x0, y + 1, lab, 8.2, color=INK, w=label_w)
        w = max(1.5, total_w * abs(v) / mx)
        pdf.box(x0 + label_w, y, w, 6, color, r=2)
        pdf.text_at(x0 + label_w + w + 2, y + 1, won(v), 8.2, True)
        y += 8.5
    pdf.set_y(y + 1)


def _simple_table(pdf: Report, header: list[str], rows: list[list[str]], widths: list[float], bold_last=True):
    x0, y = pdf.l_margin, pdf.get_y()
    pdf.set_draw_color(*LINE)
    x = x0
    for h, w in zip(header, widths):
        pdf.text_at(x + 1, y, h, 7.5, True, MUTED, w=w - 2, align="L" if x == x0 else "R")
        x += w
    y += 5
    pdf.line(x0, y, x0 + sum(widths), y)
    for row in rows:
        x = x0
        for i, (c, w) in enumerate(zip(row, widths)):
            pdf.text_at(x + 1, y + 1.6, c, 8, bold=(bold_last and i == len(row) - 1) or i == 0,
                        color=INK, w=w - 2, align="L" if i == 0 else "R")
            x += w
        y += 6.5
        pdf.line(x0, y, x0 + sum(widths), y)
    pdf.set_y(y + 2)


def build_pdf(d: dict) -> bytes:
    pdf = Report("자립ON 자립설계 요약")
    pdf.alias_nb_pages()
    pdf.add_page()
    W = pdf.w - pdf.l_margin - pdf.r_margin

    # 헤더
    pdf.box(pdf.l_margin, 12, W, 26, PEACH, r=5)
    pdf.text_at(pdf.l_margin + 6, 16, "자립ON · AI 자립설계 길잡이", 8, True, CORAL)
    pdf.text_at(pdf.l_margin + 6, 21, f"{d['name']} 님의 자립설계 요약 보고서", 16, True)
    pdf.text_at(pdf.l_margin + 6, 30.5, f"기준월 {d['base_month']} · 작성일 {d['generated']} · {d['profile_line']}", 7.8, color=MUTED)
    pdf.set_y(42)

    # 1. 현재 상태
    pdf.section("1. 현재 상태")
    st_ = d["status"]
    _tiles(pdf, [
        ("월 수입", won(st_["income"]), st_["income_note"], (PEACH, CORAL)),
        ("월 지출", won(st_["expense"]), st_["expense_note"], (LAV, LAV_D)),
        ("매달 남는 돈", won(st_["income"] - st_["expense"]), "수입 − 지출", (MINT, MINT_D)),
        ("자립 목표", f"{st_['goal_year']}년", f"초기자금 {won(st_['goal_amount'])}", (BUTTER, BUTTER_D)),
    ])

    # 2. 지원제도
    pdf.section("2. 맞춤 지원제도 · 2026년 기준 월 지원액", need=50)
    _programs(pdf, d["programs"])
    pdf.set_font("N", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(W, 3.4, "월 지원액은 2026년 고시 기준으로 계산한 예상액이에요(장애인연금: 기초급여 349,700원 + 부가급여, "
                           "선정기준 단독 140만 원). 실제 금액은 주민센터의 소득·재산 조사 후 확정돼요. ‘바로가기’를 누르면 공식 안내로 연결돼요.", align="L")
    pdf.ln(1)

    # 3. 현금흐름
    cf = d["cashflow"]
    pdf.section("3. 지원 적용 전후 월 현금흐름", need=45)
    bars = [("지원 전", cf["before"], (201, 184, 174)), ("지원 후", cf["after"], (240, 138, 108))]
    if cf.get("job") is not None:
        bars.append(("취업 후 (가정)", cf["job"], (111, 183, 154)))
    _bars(pdf, bars)
    hdr = ["기간 · 누적 잉여", "지원 전", "지원 후"] + (["지원 + 취업"] if cf.get("job") is not None else [])
    rows = [[f"{h['years']}년", won(h["before"]), won(h["after"])] + ([won(h["job"])] if cf.get("job") is not None else [])
            for h in cf["horizons"]]
    ws = [W * 0.28] + [W * 0.72 / (len(hdr) - 1)] * (len(hdr) - 1)
    _simple_table(pdf, hdr, rows, ws)
    if cf.get("assumptions"):
        pdf.set_font("N", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(W, 3.4, "가정 포함: " + ", ".join(cf["assumptions"]), align="L")

    # 4. 예·적금
    pdf.section(f"4. 예·적금 운용 비교 · {d['period']}개월, 매달 {won(d['monthly_saving'])} 저축", need=45)
    _simple_table(pdf, ["운용방안", "원금(내 돈)", "세후 이자(새로 생긴 돈)", "만기 금액"],
                  [[p["product"], f"{p['principal']:,}원", f"+{p['net_interest']:,}원", f"{p['maturity']:,}원"] for p in d["plans"]],
                  [W * 0.34, W * 0.22, W * 0.22, W * 0.22])

    # 5. 자립 목표
    g = d["goal"]
    pdf.section(f"5. {g['year']}년 자립 초기자금 목표", need=40)
    y = pdf.get_y()
    pct = min(1.0, g["balance"] / g["target"]) if g["target"] else 0
    pdf.box(pdf.l_margin, y, W, 7, GRAY_BG, r=3.5)
    pdf.box(pdf.l_margin, y, max(4, W * pct), 7, (255, 216, 199) if pct < 1 else (205, 235, 221), r=3.5)
    pdf.text_at(pdf.l_margin + 3, y + 1.4, f"예상 {won(g['balance'])} / 목표 {won(g['target'])}  ({g['balance'] / g['target'] * 100:.0f}%)"
                if g["target"] else "", 8.5, True)
    pdf.set_y(y + 10)
    _tiles(pdf, [
        ("가족 적립만 했을 때", won(g["family_only"]), "월 가족 적립 기준", (LAV, LAV_D)),
        ("이자 (새로 생긴 돈)", won(g["interest"]), "나머지는 모은 원금", (MINT, MINT_D)),
        ("필요한 본인 월 저축", won(g["need_self"]) if g["need_self"] is not None else "-", "취업 후 저축 가능한 달 기준", (SKY, (76, 131, 181))),
    ])

    # 6. 자립 이후
    ind = d["independence"]
    pdf.section(f"6. 자립 이후 한 달 살림 ({ind['period']})", need=35)
    parts = " + ".join(f"{k} {won(v)}" for k, v in ind["income_parts"].items() if v)
    pdf.set_font("N", "", 8.4)
    pdf.set_text_color(*INK)
    pdf.multi_cell(W, 4.6, f"들어오는 돈 {won(sum(ind['income_parts'].values()))} ({parts})\n"
                           f"나가는 돈 (독립 생활비) {won(ind['living'])}\n"
                           f"매달 남는 돈 {won(ind['diff'])}", align="L")
    pdf.ln(1)

    # 7. 점검
    pdf.section("7. 정기 점검 체크리스트 (재무설계 6단계 · 모니터링)", need=40)
    for when, txt in d["checks"]:
        y = pdf.get_y()
        pdf.box(pdf.l_margin, y, 24, 5.4, LAV, r=2.7)
        pdf.text_at(pdf.l_margin, y + 1.1, when, 7, True, LAV_D, w=24, align="C")
        pdf.text_at(pdf.l_margin + 27, y + 1, txt, 8.2, w=W - 27)
        pdf.set_y(y + 7)

    # 참고 링크
    pdf.section("참고 · 공식 확인처", need=25)
    pdf.set_font("N", "", 7.6)
    for label, url in d["refs"]:
        pdf.set_text_color(*CORAL)
        pdf.cell(0, 4.2, f"· {label}", link=url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())
