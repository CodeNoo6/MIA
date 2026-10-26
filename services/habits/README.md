# Hábitos

Servidor MCP del **Agente de Hábitos** de MIA: lleva la cuenta de cuántas veces cada usuario hace algo y lo
analiza como la app iOS Repeat. Los datos de cada usuario de MIA viven en MongoDB (base `habits`) y todos los
cálculos los hace el servidor; el modelo solo los cita.

```
LibreChat agente ─(X-MIA-User-Id)─► habits-mcp (:8001/mcp/, privado) ─► MongoDB (base habits)
```

La guía para crear el agente en MIA, con las instrucciones para pegar, está en
[agents/habitos/README.md](agents/habitos/README.md).

## Qué cubre

| Repeat | Herramientas |
|---|---|
| Métricas con categoría, unidad y meta | `create_habit`, `update_habit`, `archive_habit`, `delete_habit`, `list_habits` |
| Registrar entradas con valor, fecha y nota | `log` (con `detail` para desglosar: pizza, mamá…), `list_entries`, `delete_entry` |
| Hoy, semana, mes y año contra el periodo anterior | `habit_stats` (sube/baja ±5 %, significativo >10 %, y mejora o empeora según si el hábito es bueno o malo) |
| Gráficas | `show_habit_chart` (mapa de calor del año y barras por mes), `habit_series` (para artefactos) |
| Resumen | `year_in_review`: totales, mes pico, desglose y comparación con el año anterior |

Además: metas de máximo o mínimo por día, semana o mes; rachas con el hábito y días sin él; día de la semana,
horas y detalles más frecuentes; zona horaria por usuario (`set_timezone`, por defecto `HABITS_TIMEZONE`).

| Archivo | Responsabilidad |
|---|---|
| `habits/stats.py` | Cálculos puros: periodos, comparaciones, metas, rachas, distribuciones y series |
| `habits/store.py` | Persistencia por usuario en Mongo, fechas en la zona del usuario y búsqueda por nombre o alias |
| `habits/charts.py` | Gráficas PNG con matplotlib a partir de series ya calculadas |
| `mcp_server/server.py` | Herramientas MCP e identidad del usuario por headers |

## Correr en local

`docker compose up -d habits-mcp` lo levanta junto con MIA usando el Mongo de LibreChat.
Tests: `docker run --rm --entrypoint python mia-habits:latest -m pytest -q tests`

## Desplegar en Railway

1. Crea un servicio desde el repo con **Root Directory** `services/habits` (usa su Dockerfile; no necesita start
   command).
2. **Settings → Networking → Private Networking:** el dominio debe ser exactamente `habits-mcp` (queda
   `habits-mcp.railway.internal`). Railway lo fija con el nombre que tenía el servicio al crearlo; si salió otro,
   edítalo con el lápiz. **No generes dominio público**: el servidor confía en el header de identidad.
3. **Variables:**
   ```
   PORT=8001
   MONGO_URL=${{Mongo.MONGO_URL}}
   HABITS_TIMEZONE=America/Bogota
   HABITS_MCP_TOKEN=<secreto>
   ```
4. En el servicio **LibreChat** agrega `HABITS_MCP_TOKEN` con el mismo secreto y redespliega.
   `deploy/config.railway.yaml` ya define el servidor `habitos` y permite `habits-mcp.railway.internal:8001`.
