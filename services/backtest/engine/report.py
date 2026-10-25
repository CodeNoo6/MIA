"""Render a stored audit record as a PDF certificate. It reads the record; it never recomputes."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#132033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def render_pdf(record: dict) -> bytes:
    styles = getSampleStyleSheet()
    summary = record["summary"]
    dsr = record["deflated_sharpe"]
    mc = record["monte_carlo"]
    placebo = record["placebo"]
    pbo = record.get("pbo")
    story = [
        Paragraph("Auditoría de backtest", styles["Title"]),
        Paragraph(f"Corrida {record['run_id']} · {record['created_at']}", styles["Normal"]),
        Paragraph(f"Hash del informe (SHA-256): {record['report_hash']}", styles["Code"]),
        Spacer(1, 12),
        Paragraph("Resumen", styles["Heading2"]),
        _table(
            [
                ["Métrica", "Valor"],
                ["Operaciones", str(record["trades"])],
                ["Resultado neto", _fmt(summary["total"], 2)],
                ["Sharpe por operación", _fmt(summary["sharpe_per_trade"])],
                ["Drawdown máximo observado", _fmt(summary["max_drawdown"], 2)],
                ["Combinaciones examinadas (N)", str(record["combinations_examined"])],
                ["Sharpe probabilístico (PSR)", _fmt(record["psr"])],
                ["Umbral de Sharpe por N", _fmt(dsr["sharpe_threshold"])],
                ["Sharpe desinflado (DSR)", _fmt(dsr["dsr"])],
                ["PBO (CSCV)", _fmt(pbo["pbo"]) if pbo else "Requiere matriz de variantes"],
                ["Placebo: p-valor", _fmt(placebo["p_value"])],
            ]
        ),
        Spacer(1, 12),
        Paragraph(f"Monte Carlo del drawdown ({mc['sims']} simulaciones, semilla {record['params']['seed']})", styles["Heading2"]),
        _table(
            [["p50", "p95", "p99", "Prob. de romper el límite"]]
            + [[_fmt(mc["p50"], 2), _fmt(mc["p95"], 2), _fmt(mc["p99"], 2), _fmt(mc.get("breach_probability"))]]
        ),
        Spacer(1, 12),
        Paragraph("Sensibilidad a costos", styles["Heading2"]),
        _table(
            [["Multiplicador", "Resultado neto", "Sharpe"]]
            + [[f"x{r['multiplier']:g}", _fmt(r["total"], 2), _fmt(r["sharpe"])] for r in record["cost_sensitivity"]]
        ),
        Spacer(1, 12),
        Paragraph("Subperiodos", styles["Heading2"]),
        _table(
            [["Segmento", "Operaciones", "Resultado", "Sharpe"]]
            + [[str(r["segment"]), str(r["trades"]), _fmt(r["total"], 2), _fmt(r["sharpe"])] for r in record["subperiods"]]
        ),
        Spacer(1, 12),
        Paragraph(
            "Los resultados los calcula un motor determinista con semilla fija; ningún modelo de lenguaje "
            "interviene en el cálculo ni en este certificado. Verifica la integridad recalculando el hash del registro.",
            styles["Italic"],
        ),
    ]
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, title=f"Auditoría {record['run_id']}").build(story)
    return buffer.getvalue()
