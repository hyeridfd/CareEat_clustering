# -*- coding: utf-8 -*-
"""식자재 단가 엑셀 내보내기 (openpyxl)

· build_search_xlsx  : 검색 결과 + 기간 월별 단가 + 검색 조건
· build_trends_xlsx  : 분류 월별 지수·kg당 중앙값(차트 포함) + 계절 패턴 + 많이 변한 품목 + 대분류 요약
"""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

KST = ZoneInfo("Asia/Seoul")
NAVY, NAVY_LIGHT, GRID = "07204D", "EEF3FB", "D7E3F6"
SUP_COLOR = {"hgreenfood": "0F9D76", "sajo": "D97706"}
SUP_LABEL = {"hgreenfood": "현대그린푸드", "sajo": "사조푸디스트"}
WON = '#,##0"원"'
PCT = '+0.0"%";-0.0"%";0.0"%"'

_thin = Side(style="thin", color=GRID)
_head_font = Font(bold=True, color="FFFFFF", size=10)
_head_fill = PatternFill("solid", fgColor=NAVY)
_title_font = Font(bold=True, size=14, color=NAVY)
_sub_font = Font(size=9, color="64748B")


def _now():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def _sheet_title(ws, title, sub, width_cols):
    ws["A1"] = title
    ws["A1"].font = _title_font
    ws["A2"] = sub
    ws["A2"].font = _sub_font
    ws.row_dimensions[1].height = 24
    if width_cols > 1:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width_cols)


def _table(ws, header_row, headers, rows, widths, formats=None, wrap_cols=()):
    """헤더 + 데이터 행. formats = {열번호(1부터): number_format}"""
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font, cell.fill = _head_font, _head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=_thin)
    ws.row_dimensions[header_row].height = 30
    for r_i, row in enumerate(rows, header_row + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r_i, column=c, value=v)
            cell.border = Border(bottom=_thin)
            if formats and c in formats:
                cell.number_format = formats[c]
            if c in wrap_cols:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if (r_i - header_row) % 2 == 0:
            for c in range(1, len(headers) + 1):
                ws.cell(row=r_i, column=c).fill = PatternFill("solid", fgColor="F8FAFD")
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    if rows:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{header_row + len(rows)}"


def _sup_cell(ws, row, col, sup):
    c = ws.cell(row=row, column=col)
    c.font = Font(bold=True, color=SUP_COLOR.get(sup, "0F172A"))


def _notes_sheet(wb, conditions, extra_notes):
    ws = wb.create_sheet("조건·안내")
    _sheet_title(ws, "검색 조건 및 안내", f"Care-Eat 식자재 · 내려받은 시각 {_now()}", 2)
    r = 4
    for k, v in conditions:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True, color=NAVY)
        ws.cell(row=r, column=2, value=v)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="참고").font = Font(bold=True, color=NAVY)
    for n in extra_notes:
        r += 1
        ws.cell(row=r, column=1, value="·")
        ws.cell(row=r, column=2, value=n).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 30
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 110


COMMON_NOTES = [
    "단가는 공급사 계약 단가표(공급가) 기준이며, 부가세 포함가는 현대그린푸드는 제공값, 사조는 과세 품목에 10%를 더한 추정값입니다.",
    "kg당 환산은 규격 표기(1.56Kg, 380g, 500G*10EA 등)에서 읽은 포장 중량으로 계산한 참고값입니다. 읽을 수 없는 품목은 비워 두었습니다.",
    "사조푸디스트의 대·중분류는 공급사가 제공하지 않아 품목명으로 자동 추정한 값입니다.",
    "월별 단가는 그 달에 받은 단가표들의 평균이며, 공급사 단가표 금액을 보정 없이 그대로 씁니다. 거의 모든 품목이 같은 비율로 한꺼번에 바뀐 달(예: 2026년 10→11월 현대그린푸드 ×1.30, 사조 ×1.40)은 그대로 반영되어 있습니다.",
]


def build_search_xlsx(items, series, months, conditions, vat=True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "검색결과"
    pp = "unit_price_tax" if vat else "unit_price"
    pk = "per_kg_tax" if vat else "per_kg"
    vat_lab = "부가세 포함" if vat else "부가세 별도"
    headers = ["공급사", "단품코드", "품목명", "대분류", "중분류", "규격", "단위", "보관", "원산지", "과세",
               "최소 발주", f"단가({vat_lab})", "단가(공급가)", f"kg당 환산({vat_lab})",
               "기간 평균(공급가)", "기간 최저", "기간 최고", "기간 처음", "기간 마지막", "기간 변동률",
               "단가표 기준일", "비고"]
    rows = []
    for it in items:
        per = it.get("period") or {}
        note = []
        if it.get("tax_estimated") and vat:
            note.append("부가세 추정")
        if it.get("category_auto"):
            note.append("분류 자동추정")
        if it.get("stale"):
            note.append("단종 의심")
        rows.append([SUP_LABEL.get(it["supplier"], it["supplier"]), it["item_cd"], it["item_nm"],
                     it.get("lcls_nm"), it.get("mcls_nm"), it.get("spec"), it.get("unit"), it.get("storage"),
                     it.get("origin"), it.get("tax_type"), it.get("min_order_day"), it.get(pp), it.get("unit_price"),
                     it.get(pk) if it.get("per_unit_label") == "kg당" else None,
                     per.get("avg"), per.get("min"), per.get("max"),
                     f'{per["first_month"]} {per["first"]:,}원' if per else None,
                     f'{per["last_month"]} {per["last"]:,}원' if per else None,
                     per.get("pct"), it.get("last_seen"), ", ".join(note) or None])
    n = len(headers)
    _sheet_title(ws, "식자재 단가 검색 결과",
                 f"{len(items):,}개 품목 · 기간 {months[0] if months else '-'} ~ {months[-1] if months else '-'} · 내려받은 시각 {_now()}", n)
    _table(ws, 4, headers, rows,
           [12, 11, 38, 9, 10, 26, 6, 6, 7, 6, 11, 13, 12, 14, 13, 11, 11, 15, 15, 10, 11, 16],
           {12: WON, 13: WON, 14: WON, 15: WON, 16: WON, 17: WON, 20: PCT})
    for r_i, it in enumerate(items, 5):
        _sup_cell(ws, r_i, 1, it["supplier"])
        pct = (it.get("period") or {}).get("pct")
        if pct:
            ws.cell(row=r_i, column=20).font = Font(bold=True, color="DC2626" if pct > 0 else "1151B8")

    # 월별 단가 (품목 × 달)
    if months:
        wm = wb.create_sheet("월별 단가")
        headers2 = ["공급사", "단품코드", "품목명", "규격", "단위"] + [f"{m[:4]}.{m[5:]}" for m in months] + ["기간 변동률"]
        rows2, sups2 = [], []
        for it in items:
            sr = dict(series.get((it["supplier"], it["item_cd"]), []))
            if not sr:
                continue
            sups2.append(it["supplier"])
            rows2.append([SUP_LABEL.get(it["supplier"], it["supplier"]), it["item_cd"], it["item_nm"], it.get("spec"),
                          it.get("unit")] + [round(sr[m]) if m in sr else None for m in months]
                         + [(it.get("period") or {}).get("pct")])
        _sheet_title(wm, "품목별 월평균 단가 (공급가)", "그 달에 받은 단가표들의 평균 · 비어 있으면 그 달 단가표에 없던 품목", len(headers2))
        fm = {c: WON for c in range(6, 6 + len(months))}
        fm[6 + len(months)] = PCT
        _table(wm, 4, headers2, rows2, [12, 11, 36, 22, 6] + [11] * len(months) + [10], fm)
        for r_i, sup in enumerate(sups2, 5):
            _sup_cell(wm, r_i, 1, sup)

    _notes_sheet(wb, conditions, COMMON_NOTES)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_trends_xlsx(data, lcls, mcls, conditions) -> bytes:
    """data = trends() 응답 (lcls 지정)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "월별 지수"
    series = data.get("series") or {}
    sups = [s for s in SUP_LABEL if series.get(s)]
    months = sorted({p["month"] for s in sups for p in series[s]})
    label = lcls if mcls == "전체" else f"{lcls} › {mcls}"

    headers = ["월"]
    for s in sups:
        nm = SUP_LABEL[s]
        headers += [f"{nm} 지수", f"{nm} 전월 대비", f"{nm} 전년 대비", f"{nm} kg당 중앙값",
                    f"{nm} kg당 하위25%", f"{nm} kg당 상위25%", f"{nm} 품목 수", f"{nm} 오른 품목 비율"]
    rows, fmts = [], {}
    for m in months:
        row = [m]
        for s in sups:
            p = next((x for x in series[s] if x["month"] == m), {})
            row += [p.get("idx"), p.get("mom_pct"), p.get("yoy_pct"), p.get("kg_median"), p.get("kg_p25"),
                    p.get("kg_p75"), p.get("n_items"), p.get("up_share")]
        rows.append(row)
    for i, _ in enumerate(sups):
        base = 2 + i * 8
        fmts.update({base: "0.0", base + 1: PCT, base + 2: PCT, base + 3: WON, base + 4: WON, base + 5: WON,
                     base + 6: "#,##0", base + 7: "0%"})
    _sheet_title(ws, f"{label} 시세 동향",
                 f"지수 = 같은 품목끼리 전월 대비 변화율을 이어 붙인 값(첫 달 = 100) · kg당 = 분류 안 품목들의 kg당 월평균 가격(공급가) · {_now()}",
                 len(headers))
    _table(ws, 4, headers, rows, [10] + [12] * (len(headers) - 1), fmts)
    ws.freeze_panes = "B5"

    # 차트: 지수 / kg당 중앙값
    if rows:
        for k, (title, off, ytitle, anchor) in enumerate([("변화율 지수 (첫 달 = 100)", 0, "지수", "B"),
                                                          ("kg당 중앙값 (원)", 3, "원/kg", "L")]):
            ch = LineChart()
            ch.title, ch.y_axis.title, ch.height, ch.width = title, ytitle, 8, 16
            for i, s in enumerate(sups):
                col = 2 + i * 8 + off
                ref = Reference(ws, min_col=col, min_row=4, max_row=4 + len(rows))
                ch.add_data(ref, titles_from_data=True)
                sr = ch.series[-1]
                sr.graphicalProperties.line.solidFill = SUP_COLOR[s]
                sr.graphicalProperties.line.width = 28000
                sr.smooth = True
            ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + len(rows)))
            ws.add_chart(ch, f"{anchor}{len(rows) + 7}")

    # 계절 패턴
    wsz = wb.create_sheet("계절 패턴")
    seas = data.get("seasonal") or {}
    h2 = ["공급사"] + [f"{i}월" for i in range(1, 13)] + ["기준 연도"]
    r2 = []
    for s in sups:
        z = seas.get(s)
        if z:
            r2.append([SUP_LABEL[s]] + list(z["pct"]) + [", ".join(z["years"])])
    _sheet_title(wsz, f"{label} 계절 패턴", "그해 평균 대비 달별 % (음수 = 싼 달, 양수 = 비싼 달) · 한 해에 10개월 이상 쌓인 해만 사용", len(h2))
    _table(wsz, 4, h2, r2, [14] + [8] * 12 + [14], {c: PCT for c in range(2, 14)})
    for r_i, row in enumerate(r2, 5):
        for c in range(2, 14):
            v = row[c - 1]
            if v is None:
                continue
            t = min(abs(v) / 12, 1)
            col = ("DC2626" if v > 0 else "1151B8")
            ws_c = wsz.cell(row=r_i, column=c)
            ws_c.fill = PatternFill("solid", fgColor=_mix("F1F3F6", col, t))
            ws_c.font = Font(bold=True, color="FFFFFF" if t > 0.55 else "0F172A")
            ws_c.alignment = Alignment(horizontal="center")
    if not r2:
        wsz["A5"] = "한 해에 10개월 이상 쌓이면 계절 패턴이 계산됩니다."

    # 많이 변한 품목
    wv = wb.create_sheet("많이 변한 품목")
    pl = {"mom": "전월 대비", "3m": "3개월 전 대비", "all": "첫 달부터"}
    kl = {"up": "많이 오름", "down": "많이 내림", "swing": "많이 출렁임"}
    h3 = ["기간", "구분", "순위", "공급사", "품목명", "규격", "비교 시작", "시작 단가", "비교 끝", "끝 단가", "변동률",
          "기간 최저", "최저 달", "기간 최고", "최고 달", "최저→최고", "같이 묶인 변형"]
    r3 = []
    for per in ("mom", "3m", "all"):
        for kind in ("up", "down", "swing"):
            for r in (data.get("movers") or {}).get(per, {}).get(kind, []):
                r3.append([pl[per], kl[kind], r["rank"], SUP_LABEL.get(r["supplier"], r["supplier"]), r["item_nm"],
                           r.get("spec"), (r.get("from_month") or "")[:7], r.get("p_from"), (r.get("to_month") or "")[:7],
                           r.get("p_to"), r.get("pct"), r.get("p_min"), (r.get("min_month") or "")[:7], r.get("p_max"),
                           (r.get("max_month") or "")[:7], r.get("swing_pct"),
                           f'외 {r["n_similar"]}개' if r.get("n_similar") else None])
    _sheet_title(wv, f"{label} 안에서 많이 변한 품목", "월평균 공급가 기준 · 공급사별 Top 10", len(h3))
    _table(wv, 4, h3, r3, [12, 11, 6, 12, 36, 22, 9, 11, 9, 11, 9, 11, 9, 11, 9, 10, 12],
           {8: WON, 10: WON, 11: PCT, 12: WON, 14: WON, 16: PCT})
    for r_i, row in enumerate(r3, 5):
        v = row[10]
        if v:
            wv.cell(row=r_i, column=11).font = Font(bold=True, color="DC2626" if v > 0 else "1151B8")
    wv.freeze_panes = "E5"

    # 대분류 요약
    wo = wb.create_sheet("대분류 요약")
    h4 = ["대분류", "공급사", "최근 달", "지수", "전월 대비", "전년 대비"]
    r4 = [[o["lcls"], SUP_LABEL.get(o["supplier"], o["supplier"]), o["month"], o["idx"], o["mom_pct"], o["yoy_pct"]]
          for o in data.get("overview") or []]
    _sheet_title(wo, "대분류별 최근 시세", "지수: 첫 달 = 100", len(h4))
    _table(wo, 4, h4, r4, [10, 14, 10, 9, 11, 11], {4: "0.0", 5: PCT, 6: PCT})

    _notes_sheet(wb, conditions, COMMON_NOTES)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mix(a, b, t):
    pa = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    pb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))
