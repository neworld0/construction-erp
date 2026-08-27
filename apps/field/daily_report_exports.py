"""PDF exports for the read-only, source-backed construction daily reports."""
from io import BytesIO
from datetime import timedelta
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _document(*, landscape_mode=False):
    stream = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    document = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4) if landscape_mode else A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DailyTitle", parent=styles["Title"], fontName="HYSMyeongJo-Medium", fontSize=18, leading=25, alignment=1))
    styles.add(ParagraphStyle(name="DailyText", parent=styles["Normal"], fontName="HYSMyeongJo-Medium", fontSize=8, leading=12, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="DailyHead", parent=styles["Normal"], fontName="HYSMyeongJo-Medium", fontSize=8, leading=11, alignment=1, textColor=colors.white, wordWrap="CJK"))
    return stream, document, styles


def _p(value, styles, style="DailyText"):
    return Paragraph(escape(str(value if value not in (None, "") else "-")), styles[style])


def _amount(value):
    return f"{value:,.0f}원"


def _table(data, widths, *, header=True):
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#94A3B8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        commands.extend([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")), ("ALIGN", (1, 1), (-1, -1), "RIGHT")])
    table.setStyle(TableStyle(commands))
    return table


def _period_rows(periods, styles):
    metrics = (
        ("진행률 입력", lambda row: f"{row['progress_count']}건"),
        ("승인 출역 공수", lambda row: f"{row['labor_headcount']:,.2f}"),
        ("승인 노무비", lambda row: _amount(row["labor_amount"])),
        ("승인 원가", lambda row: _amount(row["cost_amount"])),
        ("승인 자재투입", lambda row: _amount(row["issue_amount"])),
        ("자재 반입 / 투입", lambda row: f"{row['receipt_qty']:,.3f} / {row['issue_qty']:,.3f}"),
    )
    head = ["구분", f"전일\n{periods['yesterday']['start_date']:%m.%d}", f"금일\n{periods['today']['start_date']:%m.%d}", f"당월 누계\n{periods['month_to_date']['start_date']:%m.%d}~{periods['month_to_date']['end_date']:%m.%d}"]
    rows = [[_p(cell, styles, "DailyHead") for cell in head]]
    for label, formatter in metrics:
        rows.append([_p(label, styles), *[_p(formatter(periods[key]), styles) for key in ("yesterday", "today", "month_to_date")]])
    return rows


def _organization_periods(organization_report):
    """Supply period labels even when the selected legal entity has no projects."""
    as_of_date = organization_report["as_of_date"]
    defaults = {
        "yesterday": (as_of_date - timedelta(days=1), as_of_date - timedelta(days=1)),
        "today": (as_of_date, as_of_date),
        "month_to_date": (as_of_date.replace(day=1), as_of_date),
    }
    periods = {}
    for key, (start_date, end_date) in defaults.items():
        row = dict(organization_report["period_totals"][key])
        row.setdefault("start_date", start_date)
        row.setdefault("end_date", end_date)
        periods[key] = row
    return periods


def project_daily_report_pdf(report):
    """Create a one-project report PDF from the same data used on screen."""
    stream, document, styles = _document()
    project = report["project"]
    story = [
        Paragraph("공 사 일 보", styles["DailyTitle"]),
        Spacer(1, 4 * mm),
        Paragraph(f"공사명: {escape(project.name)} / 법인: {escape(project.legal_entity.legal_name)} / 기준일: {report['as_of_date']:%Y년 %m월 %d일}", styles["DailyText"]),
        Paragraph("진행률·출역·원가·자재투입 원천을 자동 취합한 읽기 전용 보고서", styles["DailyText"]),
        Spacer(1, 4 * mm),
        _table(_period_rows(report["periods"], styles), [37 * mm, 43 * mm, 43 * mm, 52 * mm]),
        Spacer(1, 5 * mm),
        Paragraph("금일 작업 내역", styles["DailyTitle"]),
        Spacer(1, 2 * mm),
    ]
    work_rows = [[_p(label, styles, "DailyHead") for label in ("구분", "업무", "메모", "상태", "금액")]]
    for item in report["work_items"]:
        work_rows.append([
            _p(item["category"], styles), _p(item["title"], styles), _p(item["detail"], styles),
            _p(item["status"], styles), _p(_amount(item["amount"]) if item["amount"] is not None else "-", styles),
        ])
    if len(work_rows) == 1:
        work_rows.append([_p("-", styles), _p("금일 입력된 업무 내역이 없습니다.", styles), _p("-", styles), _p("-", styles), _p("-", styles)])
    story.append(_table(work_rows, [17 * mm, 42 * mm, 67 * mm, 22 * mm, 25 * mm]))
    document.build(story)
    stream.seek(0)
    return stream


def organization_daily_report_pdf(organization_report, scope_label):
    """Create a multi-project HQ/CEO consolidated daily-report PDF."""
    stream, document, styles = _document(landscape_mode=True)
    as_of_date = organization_report["as_of_date"]
    totals = _organization_periods(organization_report)
    story = [
        Paragraph(f"{escape(scope_label)} 공 사 일 보", styles["DailyTitle"]),
        Spacer(1, 4 * mm),
        Paragraph(f"기준일: {as_of_date:%Y년 %m월 %d일} / 여러 프로젝트의 전일·금일·당월 누계를 자동 취합한 경영 보고서", styles["DailyText"]),
        Spacer(1, 4 * mm),
        _table(_period_rows(totals, styles), [48 * mm, 62 * mm, 62 * mm, 76 * mm]),
        Spacer(1, 5 * mm),
        Paragraph("프로젝트별 금일 현황 및 업무 내역", styles["DailyTitle"]),
        Spacer(1, 2 * mm),
    ]
    rows = [[_p(label, styles, "DailyHead") for label in ("법인", "프로젝트", "금일 노무비", "금일 원가", "금일 자재투입", "금일 업무 내역", "확인 필요")]]
    for report in organization_report["project_reports"]:
        work = " / ".join(f"[{item['category']}] {item['title']}" for item in report["approved_work_items"][:2]) or "금일 승인 입력 없음"
        today = report["periods"]["today"]
        attention = report["ceo_attention"]
        rows.append([
            _p(report["project"].legal_entity.legal_name, styles), _p(report["project"].name, styles),
            _p(_amount(today["labor_amount"]), styles), _p(_amount(today["cost_amount"]), styles),
            _p(_amount(today["issue_amount"]), styles), _p(work, styles),
            _p(
                f"반려 미조치 {attention['rejected_count']} · 장기 대기 {attention['overdue_submission_count']}"
                if attention["total"] else "없음",
                styles,
            ),
        ])
    if len(rows) == 1:
        rows.append([_p("-", styles), _p("조회 대상 프로젝트가 없습니다.", styles), *[_p("-", styles) for _ in range(5)]])
    story.append(_table(rows, [28 * mm, 37 * mm, 29 * mm, 29 * mm, 29 * mm, 62 * mm, 39 * mm]))
    document.build(story)
    stream.seek(0)
    return stream
