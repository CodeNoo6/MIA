# Auditor de Backtests

Motor determinista que audita un backtest y un servidor MCP que deja a un agente de MIA explicar el informe.
El LLM nunca calcula ni elige qué probar: el agente solo lee resultados ya calculados, y un "¿y si…?" se vuelve
una corrida nueva del motor que suma 1 al N de combinaciones examinadas.

```
Portal (:8100) ─► engine.api ─► engine.audit + engine.stats ─► /data/runs/<id>/result.json + hash ─► PDF
                                        ▲
LibreChat agente ◄─► MCP (:8001/mcp/) ──┘  get_report · get_metric · get_chart_data · explain_methodology · request_rerun · verify_report
```

## Qué calcula

| Requisito | Dónde |
|---|---|
| FR-01 ingesta CSV (`pnl`; opcionales `timestamp`, `fees`) | `engine/audit.py` `parse_trades` |
| FR-02/FR-04 Sharpe probabilístico y desinflado por N | `engine/stats.py` `deflated_sharpe` |
| FR-05 PBO por CSCV (requiere matriz de variantes) | `engine/stats.py` `probability_of_overfitting` |
| FR-06 Monte Carlo del drawdown y límite de prop firm | `engine/stats.py` `monte_carlo_drawdown` |
| FR-07 sensibilidad a costos x0–x3 | `engine/stats.py` `cost_sensitivity` |
| FR-08 subperiodos y régimen de volatilidad (proxy por P&L) | `engine/stats.py` |
| FR-09/FR-10 informe PDF con hash SHA-256 verificable | `engine/store.py`, `engine/report.py` |
| FR-21 placebo de dirección aleatoria | `engine/stats.py` `placebo_sign_test` |
| FR-16 a FR-19 contexto de microestructura | pendiente: requiere proveedor de datos tick/libro |

Todos los cálculos usan semilla fija (`seed`, 42 por defecto): la misma entrada da el mismo informe.

## Correr en local

Desde la raíz del repo, `docker compose up -d` levanta `backtest-engine` y `backtest-mcp` junto con LibreChat
(ver `docker-compose.override.yml`). El portal queda en http://localhost:8100.

Tests: `docker run --rm --entrypoint python mia-backtest:latest -m pytest -q tests`

## Crear el agente en MIA

1. En MIA abre **Agentes → Crear agente**.
2. Nombre: `Auditor de Backtests`. Categoría: Finanzas.
3. Descripción: `Explica tu informe de auditoría de backtest y corre escenarios "¿y si…?".`
4. Modelo: el que prefieras (Claude u OpenAI).
5. En **Herramientas → Servidores MCP** agrega `Auditor de Backtests` con sus 6 herramientas, y activa **Artefactos**
   en las capacidades del agente para que pueda dibujar gráficas en el chat.
6. Instrucciones:

```
Eres el Auditor de Backtests de MIA. Explicas informes que ya calculó un motor determinista.

Reglas:
- Nunca calcules, estimes ni redondees por tu cuenta una métrica. Cita los valores que devuelven las herramientas e indica de qué corrida salen (report_id).
- Si el usuario no te ha dado un ID de informe, pídeselo y explícale que lo obtiene al subir su CSV en el portal.
- Para cualquier "¿y si…?" (comisiones, costo por operación, límite de drawdown) usa request_rerun. Avisa que cada corrida nueva suma 1 al número de combinaciones examinadas y por eso baja el Sharpe desinflado.
- Usa explain_methodology para definir una métrica antes de interpretarla.
- Si una sección es null (por ejemplo pbo sin matriz de variantes o market_context), dilo y explica qué falta.
- No des recomendaciones de inversión. Tu papel es explicar la evidencia.
- Si piden una gráfica, llama a get_chart_data y crea un artefacto React con recharts que use exclusivamente esas series (curva de capital y drawdown, histograma del drawdown simulado con líneas en p95 y p99, barras de sensibilidad a costos). No inventes, suavices ni interpoles puntos.
- Responde en español, claro y breve; al final comparte el enlace pdf_url.
```

## Desplegar en Railway

1. Crea dos servicios desde este repo con **Root Directory** `services/backtest`:
   - `backtest-engine`: start command por defecto, y un **volumen** montado en `/data`, donde quedan los informes.
   - `backtest-mcp`: start command `python -m mcp_server.server`, con
     `BACKTEST_ENGINE_URL=http://backtest-engine.railway.internal:8000` y
     `BACKTEST_PORTAL_URL=<dominio público del engine>`.
2. Expón públicamente solo `backtest-engine`, por el portal. El MCP va solo por red privada.
3. En el servicio LibreChat define `CONFIG_PATH=/app/deploy/config.yaml` y cambia en ese archivo la URL del MCP y
   `allowedAddresses` a `backtest-mcp.railway.internal:8001`.

## Pendiente antes de producción

- Pago por informe en el portal (USD 249 base y 400–600 con contexto, según el benchmarking) antes de ejecutar la corrida.
- Identidad: hoy cualquiera que conozca un ID puede leer su informe. Los IDs son aleatorios de 128 bits y el MCP no
  permite listarlos, pero falta asociar cada informe a su dueño.
- Capa de contexto de microestructura (FR-16 a FR-19) con un proveedor licenciado de datos tick y libro de órdenes.
