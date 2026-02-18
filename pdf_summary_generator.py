"""
PDF Summary Generator for N8N Workflow
=======================================
Generates a visually rich, professional PDF summary from workflow insights.

Usage (standalone):
    python3 pdf_summary_generator.py --data '{"title": "My Report", ...}' --output summary.pdf

Usage (from N8N Execute Command node):
    python3 pdf_summary_generator.py --data '{{ $json.insights_json }}' --output /tmp/summary_{{ $json.id }}.pdf

Input JSON schema:
{
    "title": str,
    "subtitle": str,
    "date": str,
    "source_filename": str,
    "executive_summary": str,
    "kpis": [{"label": str, "value": str, "change": str, "trend": "up"|"down"|"neutral"}],
    "insights": [{"category": str, "text": str, "importance": "high"|"medium"|"low"}],
    "sections": [{"title": str, "content": str, "bullet_points": [str]}],
    "table": {"headers": [str], "rows": [[str]]}
}
"""

import json
import sys
import argparse
import io
import math
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak, Image as RLImage
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.graphics import renderPDF

# ─── COLOR PALETTE ─────────────────────────────────────────────────────────────
PRIMARY      = colors.HexColor("#1A237E")   # Deep indigo
SECONDARY    = colors.HexColor("#283593")   # Slightly lighter indigo
ACCENT       = colors.HexColor("#42A5F5")   # Bright blue accent
ACCENT2      = colors.HexColor("#26C6DA")   # Cyan accent
SUCCESS      = colors.HexColor("#00C853")   # Green
WARNING      = colors.HexColor("#FFD600")   # Yellow
DANGER       = colors.HexColor("#F44336")   # Red
NEUTRAL      = colors.HexColor("#78909C")   # Blue-grey
BG_LIGHT     = colors.HexColor("#F5F7FA")   # Very light grey
BG_CARD      = colors.HexColor("#FFFFFF")   # White
TEXT_DARK    = colors.HexColor("#1C2B4B")   # Dark navy text
TEXT_MEDIUM  = colors.HexColor("#4A5568")   # Medium grey text
TEXT_LIGHT   = colors.HexColor("#90A4AE")   # Light grey text
DIVIDER      = colors.HexColor("#E8ECF0")   # Divider line

IMPORTANCE_COLORS = {
    "high":    colors.HexColor("#FFF3E0"),
    "medium":  colors.HexColor("#E8F5E9"),
    "low":     colors.HexColor("#E3F2FD"),
}
IMPORTANCE_BORDER = {
    "high":    colors.HexColor("#FF6F00"),
    "medium":  colors.HexColor("#2E7D32"),
    "low":     colors.HexColor("#1565C0"),
}
IMPORTANCE_LABELS = {"high": "חשוב", "medium": "בינוני", "low": "מידע"}
TREND_COLORS = {"up": SUCCESS, "down": DANGER, "neutral": NEUTRAL}
TREND_ARROWS = {"up": "▲", "down": "▼", "neutral": "●"}

PAGE_W, PAGE_H = A4


# ─── CUSTOM FLOWABLES ──────────────────────────────────────────────────────────

class ColorBox(Flowable):
    """Colored rectangle with optional text and border radius effect."""

    def __init__(self, width, height, fill_color, text="", text_color=colors.white,
                 font="Helvetica-Bold", font_size=10, border_color=None, border_width=0):
        super().__init__()
        self.width = width
        self.height = height
        self.fill_color = fill_color
        self.text = text
        self.text_color = text_color
        self.font = font
        self.font_size = font_size
        self.border_color = border_color
        self.border_width = border_width

    def draw(self):
        c = self.canv
        c.setFillColor(self.fill_color)
        if self.border_color and self.border_width:
            c.setStrokeColor(self.border_color)
            c.setLineWidth(self.border_width)
        else:
            c.setStrokeColor(self.fill_color)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1 if self.border_width else 0)
        if self.text:
            c.setFillColor(self.text_color)
            c.setFont(self.font, self.font_size)
            c.drawCentredString(self.width / 2, self.height / 2 - self.font_size * 0.35, self.text)


class KPICard(Flowable):
    """A single KPI metric card."""

    def __init__(self, label, value, change="", trend="neutral", width=4*cm):
        super().__init__()
        self.label = label
        self.value = value
        self.change = change
        self.trend = trend
        self.width = width
        self.height = 3.2 * cm

    def draw(self):
        c = self.canv
        w, h = self.width, self.height

        # Card shadow effect
        c.setFillColor(colors.HexColor("#D0D8E8"))
        c.roundRect(2, -2, w, h, 6, fill=1, stroke=0)

        # Card background
        c.setFillColor(BG_CARD)
        c.setStrokeColor(DIVIDER)
        c.setLineWidth(0.5)
        c.roundRect(0, 0, w, h, 6, fill=1, stroke=1)

        # Top accent bar
        c.setFillColor(ACCENT)
        c.roundRect(0, h - 4, w, 4, 2, fill=1, stroke=0)

        # Value (large)
        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(w / 2, h * 0.48, str(self.value))

        # Label
        c.setFillColor(TEXT_MEDIUM)
        c.setFont("Helvetica", 8)
        # Truncate label if too long
        label = self.label if len(self.label) <= 20 else self.label[:18] + "..."
        c.drawCentredString(w / 2, h * 0.22, label)

        # Trend / change
        if self.change:
            tc = TREND_COLORS.get(self.trend, NEUTRAL)
            arrow = TREND_ARROWS.get(self.trend, "")
            c.setFillColor(tc)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(w / 2, h * 0.06, f"{arrow} {self.change}")


class SectionHeader(Flowable):
    """A visually styled section header bar."""

    def __init__(self, title, width=None, icon=""):
        super().__init__()
        self.title = title
        self.icon = icon
        self.width = width or (PAGE_W - 4 * cm)
        self.height = 1.0 * cm

    def draw(self):
        c = self.canv
        w, h = self.width, self.height

        # Background gradient simulation (two rects)
        c.setFillColor(PRIMARY)
        c.roundRect(0, 0, w, h, 4, fill=1, stroke=0)

        # Accent strip on left
        c.setFillColor(ACCENT)
        c.roundRect(0, 0, 0.5 * cm, h, 4, fill=1, stroke=0)
        c.rect(0.3 * cm, 0, 0.2 * cm, h, fill=1, stroke=0)

        # Title text
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        text = f"  {self.icon}  {self.title}" if self.icon else f"   {self.title}"
        c.drawString(0.7 * cm, h * 0.28, text)


class InsightRow(Flowable):
    """A single insight with category badge and importance indicator."""

    def __init__(self, category, text, importance="medium", width=None):
        super().__init__()
        self.category = category
        self.text = text
        self.importance = importance
        self.width = width or (PAGE_W - 4 * cm)
        # Dynamic height based on text length
        chars_per_line = int(self.width / (0.22 * cm))
        lines = max(1, math.ceil(len(text) / chars_per_line))
        self.height = max(1.6 * cm, 0.8 * cm + lines * 0.45 * cm)

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        bg = IMPORTANCE_COLORS.get(self.importance, IMPORTANCE_COLORS["medium"])
        border = IMPORTANCE_BORDER.get(self.importance, IMPORTANCE_BORDER["medium"])

        # Card bg
        c.setFillColor(bg)
        c.setStrokeColor(border)
        c.setLineWidth(0.8)
        c.roundRect(0, 0, w, h, 5, fill=1, stroke=1)

        # Left accent strip
        c.setFillColor(border)
        c.roundRect(0, 0, 0.35 * cm, h, 5, fill=1, stroke=0)
        c.rect(0.2 * cm, 0, 0.15 * cm, h, fill=1, stroke=0)

        # Category badge
        badge_w = max(2.0 * cm, len(self.category) * 0.22 * cm + 0.4 * cm)
        c.setFillColor(border)
        c.roundRect(0.55 * cm, h - 0.55 * cm, badge_w, 0.42 * cm, 3, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(0.65 * cm, h - 0.39 * cm, self.category.upper())

        # Importance label on right
        label = IMPORTANCE_LABELS.get(self.importance, "")
        c.setFillColor(border)
        c.setFont("Helvetica", 7)
        c.drawRightString(w - 0.3 * cm, h - 0.38 * cm, label)

        # Main text
        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica", 9)
        max_chars = int((w - 1.2 * cm) / 0.21 / cm * cm)
        # Simple text wrapping
        words = self.text.split()
        lines = []
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            if len(test) > 85:
                if current:
                    lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)

        y_start = h - 0.75 * cm
        for i, line in enumerate(lines):
            c.drawString(0.6 * cm, y_start - i * 0.42 * cm, line)


# ─── HEADER / FOOTER CANVAS ────────────────────────────────────────────────────

class PdfCanvas(canvas.Canvas):
    """Custom canvas that draws header and footer on every page."""

    def __init__(self, *args, doc_meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._doc_meta = doc_meta or {}
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_decorations(self._pageNumber, total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_page_decorations(self, page_num, total_pages):
        w, h = PAGE_W, PAGE_H
        meta = self._doc_meta

        # ── HEADER (only page > 1) ──────────────────────────────────────────
        if page_num > 1:
            self.setFillColor(PRIMARY)
            self.rect(0, h - 1.2 * cm, w, 1.2 * cm, fill=1, stroke=0)
            self.setFillColor(ACCENT)
            self.rect(0, h - 1.2 * cm, 0.5 * cm, 1.2 * cm, fill=1, stroke=0)
            self.setFillColor(colors.white)
            self.setFont("Helvetica-Bold", 9)
            title = meta.get("title", "Summary Report")
            if len(title) > 60:
                title = title[:57] + "..."
            self.drawString(0.8 * cm, h - 0.75 * cm, title)
            self.setFont("Helvetica", 8)
            self.drawRightString(w - 1 * cm, h - 0.75 * cm, meta.get("date", ""))

        # ── FOOTER ──────────────────────────────────────────────────────────
        self.setFillColor(PRIMARY)
        self.rect(0, 0, w, 0.9 * cm, fill=1, stroke=0)
        self.setFillColor(ACCENT)
        self.rect(0, 0, 0.4 * cm, 0.9 * cm, fill=1, stroke=0)

        self.setFillColor(colors.white)
        self.setFont("Helvetica", 7.5)
        self.drawString(0.7 * cm, 0.32 * cm, "Generated by AI PDF Analyzer  •  Confidential")

        self.setFont("Helvetica-Bold", 8)
        self.drawRightString(w - 0.8 * cm, 0.32 * cm, f"Page {page_num} / {total_pages}")


# ─── CHART HELPERS ─────────────────────────────────────────────────────────────

def make_importance_pie(insights):
    """Create a pie chart of insight importance distribution."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for ins in insights:
        lvl = ins.get("importance", "medium")
        if lvl in counts:
            counts[lvl] += 1
    labels = [f"{k.capitalize()} ({v})" for k, v in counts.items() if v > 0]
    sizes  = [v for v in counts.values() if v > 0]
    clrs   = ["#FF6F00", "#2E7D32", "#1565C0"][:len(sizes)]

    if not sizes:
        return None

    fig, ax = plt.subplots(figsize=(3.2, 3.2), facecolor="none")
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=clrs, autopct="%1.0f%%",
        startangle=90, pctdistance=0.75,
        wedgeprops={"linewidth": 2, "edgecolor": "white", "width": 0.6}
    )
    for t in texts:
        t.set_fontsize(8)
        t.set_color("#1C2B4B")
    for at in autotexts:
        at.set_fontsize(8)
        at.set_fontweight("bold")
        at.set_color("white")
    ax.set_title("Insights Distribution", fontsize=9, fontweight="bold", color="#1A237E", pad=6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


def make_kpi_bar_chart(kpis):
    """Create a horizontal bar chart for KPIs with numeric values."""
    numeric_kpis = []
    for k in kpis:
        try:
            val_str = str(k.get("value", "")).replace(",", "").replace("%", "").replace("₪", "").strip()
            numeric_kpis.append((k.get("label", ""), float(val_str)))
        except ValueError:
            pass

    if len(numeric_kpis) < 2:
        return None

    labels = [k[0] for k in numeric_kpis]
    values = [k[1] for k in numeric_kpis]
    bar_colors = ["#1A237E", "#283593", "#3949AB", "#42A5F5", "#26C6DA"][:len(values)]

    fig, ax = plt.subplots(figsize=(5.5, max(2.5, len(labels) * 0.55)), facecolor="none")
    bars = ax.barh(labels, values, color=bar_colors, height=0.55, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Value", fontsize=8, color="#4A5568")
    ax.tick_params(axis="y", labelsize=8, colors="#1C2B4B")
    ax.tick_params(axis="x", labelsize=7, colors="#4A5568")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E8ECF0")
    ax.spines["bottom"].set_color("#E8ECF0")
    ax.set_facecolor("none")
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.1f}", va="center", fontsize=7.5, color="#1A237E", fontweight="bold")
    ax.set_title("Key Metrics Overview", fontsize=9, fontweight="bold", color="#1A237E", pad=6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


# ─── COVER PAGE ────────────────────────────────────────────────────────────────

def build_cover_page(data):
    """Draw a full cover page and return as a list of flowables."""
    elements = []
    w = PAGE_W - 4 * cm

    # Big top decoration bar
    cover_header = ColorBox(
        width=w, height=5.5 * cm,
        fill_color=PRIMARY,
    )
    elements.append(cover_header)
    elements.append(Spacer(1, 0))

    # Decorative accent band inside header area (simulated with table)
    accent_data = [[""] * 6]
    accent_style = TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT),
        ("BACKGROUND", (1, 0), (1, 0), ACCENT2),
        ("BACKGROUND", (2, 0), (5, 0), PRIMARY),
        ("ROWHEIGHT", (0, 0), (-1, -1), 0.6 * cm),
    ])
    accent_table = Table(accent_data, colWidths=[0.8*cm, 0.5*cm] + [w/5]*4)
    accent_table.setStyle(accent_style)
    elements.append(accent_table)
    elements.append(Spacer(1, 0.8 * cm))

    # Report type label
    styles = _get_styles()
    elements.append(Paragraph("AI-GENERATED ANALYSIS REPORT", styles["cover_eyebrow"]))
    elements.append(Spacer(1, 0.3 * cm))

    # Main title
    title = data.get("title", "Document Summary")
    elements.append(Paragraph(title, styles["cover_title"]))
    elements.append(Spacer(1, 0.3 * cm))

    # Subtitle
    subtitle = data.get("subtitle", "")
    if subtitle:
        elements.append(Paragraph(subtitle, styles["cover_subtitle"]))
    elements.append(Spacer(1, 0.8 * cm))

    # Divider
    elements.append(HRFlowable(width=w, thickness=2, color=ACCENT, spaceAfter=0.6 * cm))

    # Meta info row (source file, date, pages)
    meta_items = []
    if data.get("source_filename"):
        meta_items.append(("Source", data["source_filename"]))
    meta_items.append(("Date", data.get("date", datetime.today().strftime("%d %B %Y"))))
    if data.get("total_pages"):
        meta_items.append(("Pages", str(data["total_pages"])))

    meta_row = []
    for label, val in meta_items:
        cell_content = f"<b>{label}</b><br/>{val}"
        meta_row.append(Paragraph(cell_content, styles["meta_cell"]))

    if meta_row:
        meta_table = Table([meta_row], colWidths=[w / len(meta_row)] * len(meta_row))
        meta_table.setStyle(TableStyle([
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",  (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0,0), (-1, -1), 6),
            ("LINEBEFORE",  (1, 0), (-1, -1), 0.5, DIVIDER),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 0.8 * cm))

    # Summary statistics badges
    n_insights = len(data.get("insights", []))
    n_kpis     = len(data.get("kpis", []))
    n_sections = len(data.get("sections", []))

    if any([n_insights, n_kpis, n_sections]):
        stats = []
        if n_insights: stats.append((str(n_insights), "Insights"))
        if n_kpis:     stats.append((str(n_kpis),     "Key Metrics"))
        if n_sections: stats.append((str(n_sections), "Sections"))

        badge_cells = []
        for val, lbl in stats:
            badge_cells.append([
                Paragraph(f'<font size="24" color="#1A237E"><b>{val}</b></font>', styles["badge_number"]),
                Paragraph(lbl, styles["badge_label"]),
            ])

        badge_data = [badge_cells[i] if i < len(badge_cells) else ["", ""]
                      for i in range(min(len(badge_cells), 4))]

        # Two per row
        rows = []
        for i in range(0, len(badge_cells), 3):
            row_items = badge_cells[i:i+3]
            while len(row_items) < 3:
                row_items.append([Paragraph("", styles["badge_number"]), Paragraph("", styles["badge_label"])])
            rows.append(row_items)

        for row in rows:
            # Each item is [number, label] stacked vertically in nested table
            flat_row = []
            for item in row:
                inner = Table([[item[0]], [item[1]]], colWidths=[w/3])
                inner.setStyle(TableStyle([
                    ("ALIGN",   (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                    ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
                ]))
                flat_row.append(inner)
            outer = Table([flat_row], colWidths=[w/3]*3, hAlign="CENTER")
            outer.setStyle(TableStyle([
                ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(outer)
            elements.append(Spacer(1, 0.2 * cm))

    elements.append(PageBreak())
    return elements


# ─── STYLES ────────────────────────────────────────────────────────────────────

def _get_styles():
    base = getSampleStyleSheet()
    s = {}

    def ps(name, **kwargs):
        defaults = dict(
            fontName="Helvetica", fontSize=10, leading=14,
            textColor=TEXT_DARK, spaceAfter=6, spaceBefore=0,
            alignment=TA_LEFT
        )
        defaults.update(kwargs)
        s[name] = ParagraphStyle(name, **defaults)

    ps("cover_eyebrow", fontSize=9, textColor=ACCENT, fontName="Helvetica-Bold",
       alignment=TA_CENTER, spaceAfter=4, letterSpacing=2)
    ps("cover_title",   fontSize=28, textColor=PRIMARY, fontName="Helvetica-Bold",
       alignment=TA_CENTER, leading=34, spaceAfter=8)
    ps("cover_subtitle",fontSize=13, textColor=TEXT_MEDIUM, fontName="Helvetica",
       alignment=TA_CENTER, spaceAfter=6)
    ps("meta_cell",     fontSize=9,  textColor=TEXT_DARK, alignment=TA_CENTER,
       fontName="Helvetica")
    ps("badge_number",  fontSize=24, textColor=PRIMARY, fontName="Helvetica-Bold",
       alignment=TA_CENTER)
    ps("badge_label",   fontSize=8,  textColor=TEXT_MEDIUM, alignment=TA_CENTER)

    ps("body",       fontSize=9.5, leading=14.5, textColor=TEXT_DARK)
    ps("body_just",  fontSize=9.5, leading=14.5, textColor=TEXT_DARK, alignment=TA_JUSTIFY)
    ps("caption",    fontSize=8,   textColor=TEXT_LIGHT, spaceAfter=3)
    ps("bullet",     fontSize=9.5, leading=14, textColor=TEXT_DARK,
       leftIndent=18, bulletIndent=6, spaceAfter=3)

    ps("exec_summary", fontSize=10.5, leading=16, textColor=TEXT_DARK,
       fontName="Helvetica", alignment=TA_JUSTIFY,
       backColor=BG_LIGHT, borderPad=(8, 12, 8, 12), spaceAfter=0)

    ps("table_header", fontSize=9, fontName="Helvetica-Bold",
       textColor=colors.white, alignment=TA_CENTER)
    ps("table_cell",   fontSize=8.5, textColor=TEXT_DARK, alignment=TA_LEFT)
    ps("table_cell_c", fontSize=8.5, textColor=TEXT_DARK, alignment=TA_CENTER)

    return s


# ─── MAIN BUILD FUNCTION ───────────────────────────────────────────────────────

def build_pdf(data: dict, output_path: str):
    """Build the complete PDF from the data dictionary."""

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.3 * cm,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        title=data.get("title", "Summary Report"),
        author="AI PDF Analyzer",
        subject="Document Summary",
    )

    # Ensure date is set
    if not data.get("date"):
        data["date"] = datetime.today().strftime("%d %B %Y")

    styles = _get_styles()
    content_w = PAGE_W - 4.0 * cm
    elements = []

    # ── 1. COVER PAGE ──────────────────────────────────────────────────────
    elements.extend(build_cover_page(data))

    # ── 2. EXECUTIVE SUMMARY ───────────────────────────────────────────────
    exec_summary = data.get("executive_summary", "")
    if exec_summary:
        elements.append(SectionHeader("Executive Summary", width=content_w, icon="★"))
        elements.append(Spacer(1, 0.3 * cm))
        # Box styling via Table
        summary_table = Table(
            [[Paragraph(exec_summary, styles["body_just"])]],
            colWidths=[content_w]
        )
        summary_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), BG_LIGHT),
            ("BOX",           (0, 0), (-1, -1), 1, ACCENT),
            ("LINEBEFORE",    (0, 0), (0, -1), 4, ACCENT),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.6 * cm))

    # ── 3. KPI CARDS ───────────────────────────────────────────────────────
    kpis = data.get("kpis", [])
    if kpis:
        elements.append(SectionHeader("Key Performance Indicators", width=content_w, icon="◆"))
        elements.append(Spacer(1, 0.4 * cm))

        # Arrange KPIs in rows of 4
        cards_per_row = 4
        card_gap = 0.3 * cm
        card_w = (content_w - card_gap * (cards_per_row - 1)) / cards_per_row

        kpi_rows = [kpis[i:i+cards_per_row] for i in range(0, len(kpis), cards_per_row)]
        for row in kpi_rows:
            cells = []
            for kpi in row:
                card = KPICard(
                    label=kpi.get("label", ""),
                    value=kpi.get("value", "-"),
                    change=kpi.get("change", ""),
                    trend=kpi.get("trend", "neutral"),
                    width=card_w,
                )
                cells.append(card)
            # Pad to fill row
            while len(cells) < cards_per_row:
                cells.append(Spacer(card_w, 3.2 * cm))

            t = Table([cells], colWidths=[card_w] * cards_per_row,
                      rowHeights=[3.5 * cm])
            t.setStyle(TableStyle([
                ("LEFTPADDING",  (0, 0), (-1, -1), card_gap / 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), card_gap / 2),
                ("TOPPADDING",   (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ]))
            elements.append(t)
        elements.append(Spacer(1, 0.4 * cm))

        # Optional bar chart
        chart_buf = make_kpi_bar_chart(kpis)
        if chart_buf:
            img = RLImage(chart_buf, width=content_w * 0.6, height=min(6*cm, max(3.5*cm, len(kpis)*0.7*cm)))
            chart_table = Table([[img]], colWidths=[content_w])
            chart_table.setStyle(TableStyle([
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("BACKGROUND", (0,0), (-1,-1), BG_LIGHT),
                ("BOX", (0,0), (-1,-1), 0.5, DIVIDER),
                ("TOPPADDING",    (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ]))
            elements.append(chart_table)
            elements.append(Spacer(1, 0.6 * cm))

    # ── 4. INSIGHTS ────────────────────────────────────────────────────────
    insights = data.get("insights", [])
    if insights:
        elements.append(SectionHeader("Key Insights", width=content_w, icon="●"))
        elements.append(Spacer(1, 0.4 * cm))

        # Side-by-side: insights list + pie chart
        insight_cells = []
        for ins in insights:
            row = InsightRow(
                category=ins.get("category", "Insight"),
                text=ins.get("text", ""),
                importance=ins.get("importance", "medium"),
                width=content_w * 0.63 - 0.3 * cm,
            )
            insight_cells.append(row)
            insight_cells.append(Spacer(1, 0.2 * cm))

        pie_buf = make_importance_pie(insights)
        if pie_buf and len(insights) >= 2:
            pie_img = RLImage(pie_buf, width=content_w * 0.34, height=content_w * 0.34)
            # Two-column layout: insights on left, chart on right
            layout_table = Table(
                [[insight_cells, pie_img]],
                colWidths=[content_w * 0.63, content_w * 0.37]
            )
            layout_table.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING",   (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ]))
            elements.append(layout_table)
        else:
            for cell in insight_cells:
                elements.append(cell)

        elements.append(Spacer(1, 0.6 * cm))

    # ── 5. CONTENT SECTIONS ────────────────────────────────────────────────
    sections = data.get("sections", [])
    for section in sections:
        title   = section.get("title", "Section")
        content = section.get("content", "")
        bullets = section.get("bullet_points", [])

        elements.append(KeepTogether([
            SectionHeader(title, width=content_w),
            Spacer(1, 0.3 * cm),
        ]))

        if content:
            elements.append(Paragraph(content, styles["body_just"]))
            elements.append(Spacer(1, 0.25 * cm))

        for bp in bullets:
            elements.append(Paragraph(f"<bullet>\u2022</bullet> {bp}", styles["bullet"]))

        elements.append(Spacer(1, 0.5 * cm))

    # ── 6. DATA TABLE ──────────────────────────────────────────────────────
    table_data = data.get("table")
    if table_data and table_data.get("headers") and table_data.get("rows"):
        elements.append(SectionHeader("Data Table", width=content_w, icon="▦"))
        elements.append(Spacer(1, 0.35 * cm))

        headers = table_data["headers"]
        rows    = table_data["rows"]
        col_w   = content_w / max(len(headers), 1)

        header_row = [Paragraph(h, styles["table_header"]) for h in headers]
        body_rows  = []
        for i, row in enumerate(rows):
            body_rows.append([
                Paragraph(str(cell), styles["table_cell_c" if j > 0 else "table_cell"])
                for j, cell in enumerate(row)
            ])

        table_content = [header_row] + body_rows
        col_widths = [col_w] * len(headers)

        t = Table(table_content, colWidths=col_widths, repeatRows=1)
        row_styles = [
            ("BACKGROUND",    (0, 0), (-1, 0),  PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  9),
            ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, 0),  8),
            ("BOTTOMPADDING", (0, 0), (-1, 0),  8),
            ("FONTSIZE",      (0, 1), (-1, -1), 8.5),
            ("TOPPADDING",    (0, 1), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BG_CARD, BG_LIGHT]),
            ("BOX",           (0, 0), (-1, -1), 0.5, DIVIDER),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, DIVIDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]
        t.setStyle(TableStyle(row_styles))
        elements.append(t)
        elements.append(Spacer(1, 0.6 * cm))

    # ── 7. BUILD ───────────────────────────────────────────────────────────
    doc_meta = {
        "title": data.get("title", "Summary Report"),
        "date":  data.get("date", ""),
    }

    def make_canvas(*args, **kwargs):
        kwargs["doc_meta"] = doc_meta
        return PdfCanvas(*args, **kwargs)

    doc.build(elements, canvasmaker=make_canvas)
    return output_path


# ─── CLI ENTRY POINT ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate a visual PDF summary from JSON data")
    parser.add_argument("--data",   required=True, help="JSON string or path to JSON file")
    parser.add_argument("--output", default="summary.pdf", help="Output PDF path")
    args = parser.parse_args()

    # Accept JSON string or file path
    try:
        data = json.loads(args.data)
    except json.JSONDecodeError:
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)

    out = build_pdf(data, args.output)
    print(json.dumps({"success": True, "output": out}))


if __name__ == "__main__":
    main()
