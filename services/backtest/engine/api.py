"""HTTP API and upload portal for the backtest engine."""

from __future__ import annotations

import html
import os
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from engine.audit import AuditParams, parse_trades, parse_variants, run_audit
from engine.charts import render_png
from engine.report import render_pdf
from engine.store import RunStore

DATA_DIR = Path(os.environ.get("BACKTEST_DATA_DIR", "/data"))
MAX_UPLOAD_BYTES = int(os.environ.get("BACKTEST_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

store = RunStore(DATA_DIR)
app = FastAPI(title="Motor de auditoría de backtests", version="0.1.0")


class RerunRequest(BaseModel):
    cost_multiplier: float | None = Field(default=None, ge=0, le=20)
    cost_per_trade: float | None = Field(default=None, ge=0)
    drawdown_limit: float | None = Field(default=None, gt=0)


def _load(run_id: str) -> dict:
    try:
        return store.load(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Corrida no encontrada")


def _execute(trades_raw: bytes, variants_raw: bytes | None, params: AuditParams, family_id: str | None, parent_id: str | None) -> dict:
    try:
        trades = parse_trades(trades_raw)
        variants = parse_variants(variants_raw) if variants_raw else None
        combinations_examined = store.next_combinations(family_id, params.declared_variants)
        result = run_audit(trades, params, combinations_examined, variants)
    except (ValueError, IndexError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    inputs = {"trades.csv": trades_raw, **({"variants.csv": variants_raw} if variants_raw else {})}
    return store.save(result, inputs, family_id, parent_id)


async def _read_limited(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande")
    return data


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/runs")
async def create_run(
    trades: UploadFile = File(...),
    variants: UploadFile | None = File(default=None),
    declared_variants: int = Form(1, ge=1),
    cost_per_trade: float = Form(0.0, ge=0),
    drawdown_limit: float | None = Form(default=None),
    seed: int = Form(42),
) -> dict:
    params = AuditParams(
        declared_variants=declared_variants,
        cost_per_trade=cost_per_trade,
        drawdown_limit=drawdown_limit or None,
        seed=seed,
    )
    variants_raw = await _read_limited(variants) if variants and variants.filename else None
    return _execute(await _read_limited(trades), variants_raw, params, None, None)


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _load(run_id)


@app.post("/runs/{run_id}/rerun")
def rerun(run_id: str, request: RerunRequest) -> dict:
    """A "what if" is a new engine run on the same input; it raises N for the whole family."""
    base = _load(run_id)
    params = AuditParams(**base["params"])
    changes = {k: v for k, v in request.model_dump().items() if v is not None}
    trades_raw = store.load_input(run_id, "trades.csv")
    if trades_raw is None:
        raise HTTPException(status_code=409, detail="La corrida original no conserva su archivo")
    return _execute(trades_raw, store.load_input(run_id, "variants.csv"), replace(params, **changes), base["family_id"], run_id)


@app.get("/runs/{run_id}/verify")
def verify(run_id: str) -> dict:
    _load(run_id)
    return store.verify(run_id)


@app.get("/runs/{run_id}/report.pdf")
def report(run_id: str) -> Response:
    pdf = render_pdf(_load(run_id))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="auditoria-{run_id}.pdf"'})


@app.get("/runs/{run_id}/charts.png")
def charts(run_id: str) -> Response:
    return Response(render_png(_load(run_id)), media_type="image/png")


PORTAL = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Auditor de Backtests</title><style>
:root{color-scheme:light dark;--bg:#f5f1ea;--fg:#132033;--card:#fff;--line:#d9d2c5;--accent:#e07a2e}
@media (prefers-color-scheme:dark){:root{--bg:#0f1724;--fg:#f5f1ea;--card:#17233a;--line:#2b3a55}}
body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:640px;margin:0 auto;padding:32px 16px}h1{margin:0 0 4px}p{line-height:1.5}
form,.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;display:grid;gap:14px}
label{display:grid;gap:6px;font-weight:600}input{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:transparent;color:inherit}
button,a.button{font:inherit;font-weight:600;padding:10px 16px;border:0;border-radius:8px;background:var(--fg);color:var(--bg);cursor:pointer;text-decoration:none;text-align:center}
small{opacity:.75;font-weight:400}code{word-break:break-all}</style></head><body><main>{body}</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def portal() -> str:
    return PORTAL.replace(
        "{body}",
        """<h1>Auditor de Backtests</h1><p>Sube tu CSV y recibe un informe que te dice si tu estrategia es real o solo sobreajuste.</p>
<form method="post" action="/portal" enctype="multipart/form-data">
<label>Operaciones (CSV) <small>Columna obligatoria: pnl. Opcionales: timestamp, fees.</small><input type="file" name="trades" accept=".csv,text/csv" required></label>
<label>Variantes probadas (N) <small>Cuántas configuraciones probaste antes de elegir esta.</small><input type="number" name="declared_variants" min="1" value="1" required></label>
<label>Matriz de variantes (CSV, opcional) <small>Una columna por variante y una fila por periodo; habilita el PBO.</small><input type="file" name="variants" accept=".csv,text/csv"></label>
<label>Costo por operación <small>Se suma a la columna fees si existe.</small><input type="number" name="cost_per_trade" min="0" step="any" value="0"></label>
<label>Límite de drawdown de la prop firm (opcional)<input type="number" name="drawdown_limit" min="0" step="any"></label>
<button type="submit">Auditar</button></form>""",
    )


@app.post("/portal")
async def portal_submit(
    trades: UploadFile = File(...),
    variants: UploadFile | None = File(default=None),
    declared_variants: int = Form(1, ge=1),
    cost_per_trade: float = Form(0.0, ge=0),
    drawdown_limit: str = Form(""),
) -> RedirectResponse:
    record = await create_run(trades, variants, declared_variants, cost_per_trade, float(drawdown_limit) if drawdown_limit else None, 42)
    return RedirectResponse(f"/view/{record['run_id']}", status_code=303)


@app.get("/view/{run_id}", response_class=HTMLResponse)
def view(run_id: str) -> str:
    record = _load(run_id)
    safe_id = html.escape(record["run_id"])
    dsr = record["deflated_sharpe"]["dsr"]
    return PORTAL.replace(
        "{body}",
        f"""<h1>Informe listo</h1><div class="card">
<p><strong>ID del informe:</strong> <code>{safe_id}</code></p>
<p>Sharpe desinflado (DSR): <strong>{dsr:.3f}</strong> con N = {record['combinations_examined']} combinaciones.</p>
<p>Hash SHA-256: <code>{html.escape(record['report_hash'])}</code></p>
<img src="/runs/{safe_id}/charts.png" alt="Gráficas del informe" style="width:100%;border-radius:8px;background:#fff">
<a class="button" href="/runs/{safe_id}/report.pdf">Descargar PDF</a>
<p><small>Para que el agente te lo explique, pega este ID en el chat de MIA con el Auditor de Backtests.</small></p></div>""",
    )
