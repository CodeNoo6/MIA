"""MCP server behind MIA's habits agent: count how often each user eats something, visits someone, smokes or
does anything else, and see it compared and charted over the year, like the Repeat iOS app.

LibreChat sends the signed-in user's id in `X-MIA-User-Id` (from `{{LIBRECHAT_USER_ID}}`) and, when
`HABITS_MCP_TOKEN` is set, the shared secret in `X-Habits-Token`. Every store call is scoped to that id, so the
server must stay on the private network: the header is trusted.
"""

import functools
import hmac
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP, Image

from habits import charts, config, stats
from habits.store import CATEGORIES, Store, make_goal

mcp = FastMCP(
    "habitos",
    instructions=(
        "Registro de hábitos del usuario de MIA que conversa contigo: cuántas veces come algo, visita a alguien, "
        "fuma o hace cualquier cosa. Los totales, comparaciones, rachas y gráficas los calcula el servidor: "
        "cítalos, no los calcules. Las fechas son las del usuario (list_habits devuelve su 'today')."
    ),
)


def _owner() -> str:
    request = mcp.get_context().request_context.request
    headers = request.headers if request is not None else {}
    if config.MCP_TOKEN and not hmac.compare_digest(headers.get("x-habits-token", ""), config.MCP_TOKEN):
        raise PermissionError("Petición no autorizada.")
    owner = headers.get("x-mia-user-id", "").strip()
    if not owner or owner.startswith("{{"):
        raise PermissionError("No llegó la identidad del usuario de MIA; revisa los headers del servidor MCP.")
    return owner


def tool(fn: Callable) -> Callable:
    """Register a tool whose domain errors come back as {"error": ...} for the agent to relay."""

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return fn(*args, **kwargs)
        except (ValueError, PermissionError) as error:
            return {"error": str(error)}

    return mcp.tool()(wrapper)


def _store() -> Store:
    return config.store()


@tool
def list_habits(include_archived: bool = False) -> dict:
    """Hábitos del usuario con sus totales de hoy, semana, mes y año, su meta y su racha. Incluye 'today' y la
    zona horaria del usuario. Llámala al empezar y antes de registrar para usar el nombre exacto."""
    return _store().habits(_owner(), include_archived)


@tool
def create_habit(
    name: str,
    polarity: str = "neutral",
    unit: str = "veces",
    category: str = "otro",
    aliases: list[str] | None = None,
    goal_target: float | None = None,
    goal_period: str | None = None,
    goal_direction: str | None = None,
    notes: str | None = None,
) -> dict:
    """Crea algo para contar. polarity: bueno (quiere hacerlo más), malo (quiere reducirlo: cigarrillos, comida
    chatarra, alcohol…) o neutral (solo quiere saber cuántas veces). unit: veces, cigarrillos, vasos, minutos,
    km… category: salud, alimentacion, social, productividad, estilo_de_vida, fitness, finanzas, otro.
    aliases: otras formas de llamarlo ('cafecito', 'tinto'). Meta opcional: goal_target por goal_period (dia,
    semana, mes); goal_direction max = no pasar de (por defecto en malos) o min = llegar al menos a."""
    goal = make_goal(goal_target, goal_period, goal_direction, polarity)
    return _store().create_habit(_owner(), name, unit, category, polarity, aliases, goal, notes)


@tool
def update_habit(
    habit: str,
    name: str | None = None,
    polarity: str | None = None,
    unit: str | None = None,
    category: str | None = None,
    aliases: list[str] | None = None,
    goal_target: float | None = None,
    goal_period: str | None = None,
    goal_direction: str | None = None,
    remove_goal: bool = False,
    notes: str | None = None,
) -> dict:
    """Cambia solo los campos indicados de un hábito (por nombre, alias o id). remove_goal=true quita la meta."""
    owner = _owner()
    current = _store().find_habit(owner, habit)
    goal = make_goal(goal_target, goal_period, goal_direction, polarity or current["polarity"])
    fields = {"name": name, "polarity": polarity, "unit": unit, "category": category, "aliases": aliases,
              "goal": goal, "notes": notes}
    return _store().update_habit(owner, habit, clear_goal=remove_goal, **fields)


@tool
def archive_habit(habit: str, archived: bool = True) -> dict:
    """Archiva un hábito que ya no quiere ver (conserva sus registros); archived=false lo recupera. Registrar
    de nuevo en un hábito archivado lo recupera solo."""
    return _store().set_archived(_owner(), habit, archived)


@tool
def delete_habit(habit: str) -> dict:
    """Borra un hábito y TODOS sus registros. Confirma antes; normalmente es mejor archive_habit."""
    return _store().delete_habit(_owner(), habit)


@tool
def log(habit: str, value: float = 1, when: str | None = None, detail: str | None = None,
        note: str | None = None) -> dict:
    """Registra que pasó: habit es el nombre o alias del hábito. value = cuántas veces o cuánto (3 cigarrillos,
    2 vasos). when: vacío para ahora, 'hoy', 'ayer', 'anteayer', AAAA-MM-DD o AAAA-MM-DD HH:MM en hora del
    usuario. detail: el qué o el quién para desglosar después (pizza, mamá, cerveza). Devuelve los totales
    actualizados y la meta para que le des retroalimentación."""
    return _store().log(_owner(), habit, value, when, detail, note)


@tool
def list_entries(habit: str | None = None, from_date: str | None = None, to_date: str | None = None,
                 limit: int = 30) -> dict:
    """Registros más recientes, de un hábito o de todos, opcionalmente entre dos fechas."""
    return {"entries": _store().entries(_owner(), habit, from_date, to_date, min(limit, 200))}


@tool
def delete_entry(entry_id: str | None = None) -> dict:
    """Borra un registro por su id, o el último que se registró si no se da id (para 'deshaz lo último')."""
    return _store().delete_entry(_owner(), entry_id)


@tool
def habit_stats(habit: str, year: int | None = None) -> dict:
    """Análisis de un hábito: hoy vs ayer, semana, mes y año contra el periodo anterior hasta la misma fecha
    (trend sube/baja/estable y verdict mejora/empeora según si es bueno o malo), meta, rachas (current_days
    seguidos; days_since_last es cuánto lleva sin hacerlo), día de la semana, horas y detalles más
    frecuentes del año."""
    return _store().habit_stats(_owner(), habit, year)


@tool
def habit_series(habit: str, year: int | None = None, granularity: str = "mes") -> dict:
    """Serie completa del año por dia, semana o mes (con ceros) para graficar en un artefacto. Grafica solo
    estos puntos; no los suavices ni inventes."""
    return _store().series(_owner(), habit, year, granularity)


@tool
def show_habit_chart(habit: str, year: int | None = None) -> list:
    """Muestra en el chat la gráfica del año de un hábito: un mapa de calor con cada día y barras por mes."""
    owner = _owner()
    daily = _store().series(owner, habit, year, "dia")
    monthly = _store().series(owner, habit, year, "mes")
    png = charts.habit_year(daily["habit"], daily["unit"], daily["polarity"], daily["year"], daily["series"],
                            monthly["series"], daily.get("goal"))
    total = sum(point["value"] for point in monthly["series"])
    return [Image(data=png, format="png"), {"habit": daily["habit"], "year": daily["year"], "total": total}]


@tool
def year_in_review(year: int | None = None) -> list:
    """Resumen del año de todos los hábitos: total, días activos, mes pico, desglose, comparación con el año
    anterior y cuáles mejoraron o empeoraron, con una gráfica. Ideal a fin de año."""
    summary = _store().year_summary(_owner(), year)
    return [Image(data=charts.year_summary(summary), format="png"), summary]


@tool
def set_timezone(timezone: str) -> dict:
    """Cambia la zona horaria del usuario (p. ej. America/Bogota, America/Mexico_City, Europe/Madrid) para
    que 'hoy' y 'ayer' sean los suyos."""
    return _store().set_timezone(_owner(), timezone)


@tool
def options() -> dict:
    """Valores válidos de categorías, tipos, periodos y granularidades."""
    return {"categories": list(CATEGORIES), "polarities": list(stats.POLARITIES), "periods": list(stats.PERIODS),
            "goal_periods": ["dia", "semana", "mes"], "granularities": list(stats.GRANULARITIES)}


app = mcp.streamable_http_app()

if __name__ == "__main__":
    from habits.serve import serve

    serve(app, 8001)
