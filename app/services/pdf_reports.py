"""
app/services/pdf_reports.py
───────────────────────────
PDF report generation with styled tables, color coding, and Unicode support.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from fpdf import FPDF

logger = logging.getLogger(__name__)

FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts"
)

SEVERITY_COLORS = {
    "critica": (220, 38, 38),
    "alta": (234, 88, 12),
    "media": (37, 99, 235),
    "baja": (107, 114, 128),
}

ESTADO_COLORS = {
    "abierta": (239, 68, 68),
    "en_revision": (245, 158, 11),
    "resuelta": (34, 197, 94),
    "descartada": (156, 163, 175),
}


def _find_font() -> str | None:
    """Locate DejaVuSans.ttf — bundled, matplotlib, or system paths."""
    bundled = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
    if os.path.exists(bundled):
        return bundled
    try:
        import matplotlib.font_manager as fm
        return fm.findfont("DejaVu Sans")
    except Exception:
        pass
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/DejaVuSans.ttf",
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


class _ReportPDF(FPDF):
    """PDF with auto header/footer and configurable title."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self._font_name = "Helvetica"
        self._has_unicode = False
        self.set_auto_page_break(auto=True, margin=20)

        font_path = _find_font()
        if font_path:
            try:
                self.add_font("DejaVu", "", font_path)
                bold_path = font_path.replace(".ttf", "-Bold.ttf")
                if os.path.exists(bold_path):
                    self.add_font("DejaVu", "B", bold_path)
                else:
                    self.add_font("DejaVu", "B", font_path)
                self._font_name = "DejaVu"
                self._has_unicode = True
            except Exception:
                self._font_name = "Helvetica"
        else:
            logger.info("DejaVuSans.ttf no encontrada — usando Helvetica Latin-1")

    def _enc(self, text: str) -> str:
        if self._has_unicode:
            return text
        return text.encode("latin-1", errors="replace").decode("latin-1")

    def header(self) -> None:
        self.set_fill_color(30, 58, 95)
        self.rect(0, 0, 210, 12, "F")
        self.set_text_color(255, 255, 255)
        self.set_font(self._font_name, "B", 10)
        self.set_y(3)
        self.cell(0, 6, self._enc(self._title), align="C")
        self.set_y(15)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(self._font_name, "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, self._enc(f"Página {self.page_no()}/{{nb}}"), align="C")

    def table_header(self, col_w: list[float], headers: list[str]) -> None:
        self.set_fill_color(30, 58, 95)
        self.set_text_color(255, 255, 255)
        self.set_font(self._font_name, "B", 9)
        for w, h in zip(col_w, headers):
            self.cell(w, 8, self._enc(h), border=0, align="C", fill=True)
        self.ln()
        self.set_text_color(50, 50, 50)

    def cell(self, w: float = 0, h: float = 0, txt: str = "",
             border: int = 0, ln: int = 0, align: str = "",
             fill: bool = False, link: str = "") -> None:
        super().cell(w, h, self._enc(txt), border, ln, align, fill, link)

    def multi_cell(self, w: float, h: float, txt: str = "",
                   border: int = 0, align: str = "L",
                   fill: bool = False) -> None:
        super().multi_cell(w, h, self._enc(txt), border, align, fill)


# ── Public API ────────────────────────────────────────────────────────────────


def gen_pdf_incidencias(df: pd.DataFrame) -> bytes:
    """Styled incident report with color-coded severity."""
    pdf = _ReportPDF("Reporte de Incidencias")
    pdf.alias_nb_pages()
    pdf.add_page()
    fn = pdf._font_name

    pdf.set_font(fn, "", 9)
    pdf.set_text_color(100, 100, 100)
    now_str = datetime.now(ZoneInfo("America/Caracas")).strftime("%d/%m/%Y %H:%M")
    pdf.cell(0, 5, f"Generado: {now_str} (Venezuela)", ln=True)
    pdf.cell(0, 5, f"Total de registros: {len(df)}", ln=True)
    pdf.ln(4)

    col_w = [12, 34, 28, 58, 18, 20, 20]
    headers = ["ID", "Fecha/Hora", "Tipo", "Descripcion", "Severidad", "Estado", "Score"]
    pdf.table_header(col_w, headers)

    for idx, (_, r) in enumerate(df.iterrows()):
        ts = pd.to_datetime(r["fecha_hora"])
        if ts.tz is None:
            ts = ts.replace(tzinfo=ZoneInfo("UTC"))
        ts_str = ts.astimezone(ZoneInfo("America/Caracas")).strftime("%d/%m/%Y %H:%M")
        desc = str(r.get("descripcion", ""))[:80]
        sev = str(r["severidad"])
        score = f"{float(r['score_anomalia']):.2f}" if r.get("score_anomalia") is not None else "-"

        sev_color = SEVERITY_COLORS.get(sev, (100, 100, 100))
        estado = str(r["estado"])
        estado_color = ESTADO_COLORS.get(estado, (100, 100, 100))

        is_alt = idx % 2 == 1
        if is_alt:
            pdf.set_fill_color(248, 249, 250)

        pdf.set_font(fn, "", 7)
        pdf.cell(col_w[0], 6, str(r["id"]), fill=is_alt)
        pdf.cell(col_w[1], 6, ts_str, fill=is_alt)
        pdf.cell(col_w[2], 6, str(r["tipo"])[:14], fill=is_alt)
        pdf.cell(col_w[3], 6, desc, fill=is_alt)

        pdf.set_text_color(*sev_color)
        pdf.set_font(fn, "B", 7)
        pdf.cell(col_w[4], 6, sev, align="C", fill=is_alt)

        pdf.set_text_color(*estado_color)
        pdf.set_font(fn, "", 7)
        pdf.cell(col_w[5], 6, estado, align="C", fill=is_alt)

        pdf.set_text_color(50, 50, 50)
        pdf.set_font(fn, "", 7)
        pdf.cell(col_w[6], 6, score, align="C", fill=is_alt)
        pdf.ln()

    result = pdf.output(dest="S")
    return bytes(result)


def gen_pdf_consumo(df_kwh: pd.DataFrame, total_kwh: float, periodo: str) -> bytes:
    """Styled energy consumption report with totals."""
    pdf = _ReportPDF("Reporte de Consumo Energetico")
    pdf.alias_nb_pages()
    pdf.add_page()
    fn = pdf._font_name

    pdf.set_font(fn, "", 9)
    pdf.set_text_color(100, 100, 100)
    now_str = datetime.now(ZoneInfo("America/Caracas")).strftime("%d/%m/%Y %H:%M")
    pdf.cell(0, 5, f"Generado: {now_str} (Venezuela)", ln=True)
    pdf.cell(0, 5, f"Periodo: {periodo}", ln=True)
    pdf.cell(0, 5, f"Total: {total_kwh:.3f} kWh", ln=True)
    pdf.ln(5)

    col_w = [50, 40, 40]
    headers = ["Fecha", "kWh", "% del total"]
    pdf.table_header(col_w, headers)

    for idx, (_, r) in enumerate(df_kwh.iterrows()):
        pct = (r["kwh"] / total_kwh * 100) if total_kwh > 0 else 0
        is_alt = idx % 2 == 1
        if is_alt:
            pdf.set_fill_color(248, 249, 250)
        pdf.set_font(fn, "", 9)
        pdf.cell(col_w[0], 6, str(r["fecha"]), fill=is_alt)
        pdf.cell(col_w[1], 6, f"{r['kwh']:.3f}", align="R", fill=is_alt)
        pdf.cell(col_w[2], 6, f"{pct:.1f}%", align="R", fill=is_alt)
        pdf.ln()

    avg_kwh = df_kwh["kwh"].mean() if not df_kwh.empty else 0

    pdf.ln(3)
    pdf.set_fill_color(240, 240, 245)
    pdf.set_font(fn, "B", 9)
    pdf.cell(col_w[0], 7, "Promedio diario", fill=True)
    pdf.cell(col_w[1], 7, f"{avg_kwh:.3f} kWh", align="R", fill=True)
    pdf.cell(col_w[2], 7, "", fill=True)
    pdf.ln()

    pdf.set_fill_color(30, 58, 95)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(fn, "B", 10)
    pdf.cell(col_w[0], 8, "TOTAL", fill=True)
    pdf.cell(col_w[1], 8, f"{total_kwh:.3f} kWh", align="R", fill=True)
    pdf.cell(col_w[2], 8, "100.0%", align="R", fill=True)

    result = pdf.output(dest="S")
    return bytes(result)
