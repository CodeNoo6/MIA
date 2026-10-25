"""MCP bridge between LibreChat agents and the backtest engine.

Read-only by design, plus `request_rerun`, which asks the engine for a new run instead of
computing anything. There is no tool to list runs: a report is reachable only by its id,
which the owner gets from the upload portal.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP, Image

ENGINE_URL = os.environ.get("BACKTEST_ENGINE_URL", "http://backtest-engine:8000")
PORTAL_URL = os.environ.get("BACKTEST_PORTAL_URL", "http://localhost:8100")
TIMEOUT = float(os.environ.get("BACKTEST_ENGINE_TIMEOUT", "120"))

METHODOLOGY = {
    "psr": "Sharpe probabilístico: probabilidad de que el Sharpe real supere 0, corrigiendo por asimetría, curtosis y número de operaciones.",
    "deflated_sharpe": "Sharpe desinflado (DSR): como el PSR, pero contra el Sharpe máximo esperado por azar entre N combinaciones examinadas. Por debajo de 0.95 no hay evidencia sólida de habilidad.",
    "combinations_examined": "N: variantes que el trader declaró más cada nueva corrida pedida desde el chat. Cada '¿y si…?' lo aumenta.",
    "pbo": "Probabilidad de sobreajuste por validación cruzada combinatoria simétrica (CSCV). Requiere la matriz de variantes. Más de 0.5 indica que elegir la mejor variante en la muestra suele empeorar fuera de ella.",
    "monte_carlo": "Remuestreo con reemplazo del orden de las operaciones con semilla fija; da la distribución del drawdown máximo y la probabilidad de romper el límite de una prop firm.",
    "cost_sensitivity": "Resultado y Sharpe con los costos multiplicados por 0, 1, 2 y 3.",
    "subperiods": "La serie dividida en 4 tramos consecutivos para ver si el resultado depende de un solo periodo.",
    "volatility_regimes": "Desempeño según terciles de la volatilidad reciente del P&L. Es un proxy hasta conectar datos de mercado.",
    "placebo": "Comparación con estrategias de dirección aleatoria sobre las mismas magnitudes; p-valor = fracción de placebos con Sharpe igual o mayor.",
    "charts": "Series ya calculadas para graficar: curva de capital y drawdown por operación, histograma del drawdown máximo simulado y sensibilidad a costos.",
    "market_context": "Capa de contexto (barrido de liquidez, flujo de órdenes, VWAP anclado, perfil de volumen). Aún no conectada a un proveedor de datos.",
}

mcp = FastMCP(
    "auditor-backtests",
    instructions=(
        "Herramientas de solo lectura sobre informes ya calculados por el motor determinista. "
        "Nunca estimes ni calcules métricas: cita los valores devueltos. Para un escenario hipotético usa request_rerun."
    ),
)


def _engine(method: str, path: str, json: dict | None = None) -> dict:
    with httpx.Client(base_url=ENGINE_URL, timeout=TIMEOUT) as client:
        response = client.request(method, path, json=json)
    if response.status_code == 404:
        return {"error": "No existe un informe con ese ID. Pide al usuario el ID que le mostró el portal."}
    if response.status_code >= 400:
        return {"error": response.json().get("detail", response.text)}
    return response.json()


def _with_links(record: dict) -> dict:
    if "run_id" in record:
        record["pdf_url"] = f"{PORTAL_URL}/runs/{record['run_id']}/report.pdf"
    return record


@mcp.tool()
def get_report(report_id: str) -> dict:
    """Devuelve el informe completo ya calculado para un ID de informe."""
    return _with_links(_engine("GET", f"/runs/{report_id}"))


@mcp.tool()
def get_metric(report_id: str, metric: str) -> dict:
    """Devuelve una sola sección del informe (por ejemplo deflated_sharpe, pbo, monte_carlo, cost_sensitivity, subperiods, placebo)."""
    record = _engine("GET", f"/runs/{report_id}")
    if "error" in record:
        return record
    if metric not in record:
        return {"error": f"Métrica desconocida. Disponibles: {', '.join(sorted(record))}"}
    return {"report_id": report_id, "metric": metric, "value": record[metric], "definition": METHODOLOGY.get(metric)}


@mcp.tool()
def show_charts(report_id: str) -> list:
    """Muestra en el chat la gráfica del informe dibujada por el motor: curva de capital con el drawdown
    sombreado. Úsala siempre al explicar un informe."""
    with httpx.Client(base_url=ENGINE_URL, timeout=TIMEOUT) as client:
        response = client.get(f"/runs/{report_id}/charts.png")
    if response.status_code == 404:
        return ["No existe un informe con ese ID. Pide al usuario el ID que le mostró el portal."]
    response.raise_for_status()
    return [Image(data=response.content, format="png"), f"Gráfica del informe {report_id}, calculada por el motor."]


@mcp.tool()
def get_chart_data(report_id: str) -> dict:
    """Devuelve las series listas para graficar: equity_curve (trade, equity, drawdown),
    drawdown_histogram (from, to, count) y cost_sensitivity (multiplier, total, sharpe).
    Grafica solo estos valores; no agregues ni interpoles puntos."""
    record = _engine("GET", f"/runs/{report_id}")
    if "error" in record:
        return record
    return {
        "report_id": report_id,
        "equity_curve": record["charts"]["equity_curve"],
        "drawdown_histogram": record["monte_carlo"]["histogram"],
        "drawdown_percentiles": {k: record["monte_carlo"][k] for k in ("observed", "p50", "p95", "p99")},
        "cost_sensitivity": record["cost_sensitivity"],
    }


@mcp.tool()
def explain_methodology() -> dict:
    """Define cada métrica del informe tal como la calcula el motor."""
    return METHODOLOGY


@mcp.tool()
def request_rerun(
    report_id: str,
    cost_multiplier: float | None = None,
    cost_per_trade: float | None = None,
    drawdown_limit: float | None = None,
) -> dict:
    """Pide al motor una corrida nueva con parámetros cambiados (p. ej. cost_multiplier=2 para duplicar comisiones).
    Suma 1 al número de combinaciones examinadas de toda la familia de corridas."""
    changes = {
        "cost_multiplier": cost_multiplier,
        "cost_per_trade": cost_per_trade,
        "drawdown_limit": drawdown_limit,
    }
    if all(value is None for value in changes.values()):
        return {"error": "Indica al menos un parámetro a cambiar."}
    return _with_links(_engine("POST", f"/runs/{report_id}/rerun", json=changes))


@mcp.tool()
def verify_report(report_id: str) -> dict:
    """Verifica que el hash del informe coincide con su contenido."""
    return _engine("GET", f"/runs/{report_id}/verify")


if __name__ == "__main__":
    from engine.serve import serve

    serve(mcp.streamable_http_app(), 8001)
