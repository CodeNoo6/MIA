"""MCP server that gives a MIA agent everything the Cat Life app does, per MIA user.

LibreChat sends the signed-in user's id in `X-MIA-User-Id` (from `{{LIBRECHAT_USER_ID}}` in the MCP
server headers) and, when `CATLIFE_MCP_TOKEN` is set, the shared secret in `X-CatLife-Token`. Every
store call is scoped to that id. The server must stay on the private network: the header is trusted.
"""

import base64
import functools
import hmac
from collections.abc import Callable
from typing import NamedTuple

import httpx
from mcp.server.fastmcp import FastMCP, Image

from catlife import card as render
from catlife import care, config, notify
from catlife.places import find_veterinaries as search_places
from catlife.store import Store

mcp = FastMCP(
    "cat-life",
    instructions=(
        "Herramientas de Cat Life sobre los gatos del usuario de MIA que conversa contigo. "
        "Las fechas próximas, edades y nombres de dosis los calcula el servidor: cítalos, no los calcules. "
        "Antes de crear o borrar algo confirma el gato por su nombre; usa list_cats para obtener los id. "
        "Los gatos pueden ser de un hogar familiar compartido entre usuarios de MIA: al iniciar llama a "
        "family_status (invitaciones pendientes primero) y a family_activity para contar lo que hicieron los demás. "
        f"El carné público, el QR, las fotos y el calendario se sirven desde {config.PUBLIC_URL}."
    ),
)


ACTIVITY = {
    "register_cat": "registró al gato", "update_cat": "actualizó los datos del gato", "delete_cat": "borró al gato",
    "add_vaccine": "registró la vacuna", "apply_vaccine_dose": "aplicó la vacuna", "delete_vaccine": "borró una vacuna",
    "add_reminder": "programó", "update_reminder": "cambió el recordatorio", "complete_reminder": "marcó como hecho",
    "delete_reminder": "borró un recordatorio", "add_medical_record": "agregó al historial clínico",
    "delete_medical_record": "borró un registro clínico", "log_weight": "registró el peso",
    "add_condition": "registró la condición", "update_condition": "actualizó la condición",
    "add_appointment": "agendó una cita", "update_appointment": "actualizó una cita",
    "save_veterinarian": "guardó al veterinario", "delete_veterinarian": "borró un veterinario",
}


def _header_text(value: str) -> str | None:
    """LibreChat sends names outside Latin-1 as `b64:<base64>`; unresolved placeholders count as missing."""
    value = value.strip()
    if not value or value.startswith("{{"):
        return None
    if value.startswith("b64:"):
        return base64.b64decode(value[4:]).decode("utf-8", "replace")
    return value


class Identity(NamedTuple):
    user_id: str
    name: str | None
    email: str | None


def _identity() -> Identity:
    request = mcp.get_context().request_context.request
    headers = request.headers if request is not None else {}
    if config.MCP_TOKEN and not hmac.compare_digest(headers.get("x-catlife-token", ""), config.MCP_TOKEN):
        raise PermissionError("Petición no autorizada.")
    user_id = _header_text(headers.get("x-mia-user-id", ""))
    if not user_id:
        raise PermissionError("No llegó la identidad del usuario de MIA; revisa los headers del servidor MCP.")
    return Identity(user_id, _header_text(headers.get("x-mia-user-name", "")),
                    _header_text(headers.get("x-mia-user-email", "")))


def _owner() -> str:
    """The data space of the current MIA user: their own, or their household's."""
    return config.family().space(*_identity())


def _describe(result: dict) -> str | None:
    for source in (result, result.get("next") or {}):
        for key in ("name", "title", "reason", "next_dose"):
            if source.get(key):
                return str(source[key])
    if result.get("weight_kg"):
        return f"{result['weight_kg']} kg"
    return None


def _record(action: str, kwargs: dict, result: object) -> None:
    if not isinstance(result, dict) or "error" in result:
        return
    user_id, name, _ = _identity()
    cat_id = kwargs.get("cat_id") or result.get("cat_id") or (result.get("id") if action == "register_cat" else None)
    config.family().log(config.family().space(user_id), user_id, name, ACTIVITY[action], cat_id, _describe(result))


def tool(fn: Callable) -> Callable:
    """Register a tool whose domain errors come back as {"error": ...} for the agent to relay. Changes to the
    cats are written to the activity log so everyone in the household hears about them."""

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            result = fn(*args, **kwargs)
            if fn.__name__ in ACTIVITY:
                _record(fn.__name__, kwargs, result)
            return result
        except (ValueError, PermissionError) as error:
            return {"error": str(error)}

    return mcp.tool()(wrapper)


def _store() -> Store:
    return config.store()


# --- gatos -----------------------------------------------------------------------------------------


@tool
def list_cats() -> dict:
    """Lista los gatos del usuario con su id, datos, edad en meses y edad humana equivalente."""
    return {"cats": _store().cats(_owner())}


@tool
def register_cat(
    name: str,
    gender: str | None = None,
    breed: str | None = None,
    color: str | None = None,
    birth_date: str | None = None,
    age_months: int | None = None,
    weight_kg: float | None = None,
    sterilized: bool = False,
    microchip: bool = False,
    notes: str | None = None,
) -> dict:
    """Registra un gato. gender: Macho o Hembra. birth_date en AAAA-MM-DD o DD/MM/AAAA; si no se conoce,
    usa age_months (puedes estimarla con teeth_age_guide). breed por defecto Mestizo."""
    return _store().add_cat(_owner(), name=name, gender=gender, breed=breed, color=color, birth_date=birth_date,
                            age_months=age_months, weight_kg=weight_kg, sterilized=sterilized,
                            microchip=microchip, notes=notes)


@tool
def update_cat(
    cat_id: str,
    name: str | None = None,
    gender: str | None = None,
    breed: str | None = None,
    color: str | None = None,
    birth_date: str | None = None,
    age_months: int | None = None,
    weight_kg: float | None = None,
    sterilized: bool | None = None,
    microchip: bool | None = None,
    notes: str | None = None,
) -> dict:
    """Edita solo los campos indicados de un gato. Cambiar el peso también lo registra en su historial."""
    return _store().update_cat(_owner(), cat_id, name=name, gender=gender, breed=breed, color=color,
                               birth_date=birth_date, age_months=age_months, weight_kg=weight_kg,
                               sterilized=sterilized, microchip=microchip, notes=notes)


@tool
def delete_cat(cat_id: str) -> dict:
    """Borra un gato con TODAS sus vacunas, historial, citas, recordatorios y foto. Pide confirmación antes."""
    return _store().delete_cat(_owner(), cat_id)


@tool
def cat_photo_upload_link(cat_id: str) -> dict:
    """Enlace para que el usuario suba o cambie la foto del gato desde su celular o computador (vence en 30 min).
    La foto aparece en el carné, en la imagen para redes y en show_card."""
    owner = _owner()
    token = _store().photo_upload_token(owner, cat_id)
    return {"upload_url": f"{config.PUBLIC_URL}/foto/{token}", "expires_in_minutes": 30}


# --- vacunas ---------------------------------------------------------------------------------------


@tool
def add_vaccine(
    cat_id: str,
    name: str,
    frequency: str,
    applied_date: str | None = None,
    next_due: str | None = None,
    total_doses: int = 1,
    veterinarian: str | None = None,
    notes: str | None = None,
) -> dict:
    """Registra una vacuna. frequency: anual, semestral (cada 6 meses), trimestral, bimestral, mensual o
    'una sola vez'. Con applied_date se registra la 1.ª dosis y la próxima fecha se calcula sola; sin
    applied_date queda pendiente para next_due. Usa nombres como 'Triple Felina 1era' para encadenar dosis."""
    return _store().add_vaccine(_owner(), cat_id, name, applied_date, frequency, total_doses, veterinarian,
                                notes, next_due)


@tool
def apply_vaccine_dose(
    vaccine_id: str,
    applied_date: str,
    veterinarian: str | None = None,
    notes: str | None = None,
    next_due: str | None = None,
) -> dict:
    """Marca como aplicada la dosis pendiente (completar y renovar): guarda el historial, calcula la próxima
    fecha según la frecuencia (o usa next_due si el veterinario dio otra) y avanza 1era → 2da → 3era → Refuerzo."""
    return _store().apply_dose(_owner(), vaccine_id, applied_date, veterinarian, notes, next_due)


@tool
def list_vaccines(cat_id: str | None = None) -> dict:
    """Vacunas con historial de dosis, última aplicación y próxima fecha. Sin cat_id trae las de todos los gatos."""
    return {"vaccines": _store().vaccines(_owner(), cat_id)}


@tool
def delete_vaccine(vaccine_id: str) -> dict:
    """Borra una vacuna y su historial."""
    return _store().delete_vaccine(_owner(), vaccine_id)


# --- recordatorios y agenda ------------------------------------------------------------------------


@tool
def get_agenda(days: int = 30, cat_id: str | None = None) -> dict:
    """Vacunas, citas y recordatorios vencidos (overdue=true) y de los próximos `days` días, en orden de fecha.
    Úsala al iniciar la conversación para avisar lo pendiente."""
    return {"items": _store().agenda(_owner(), days, cat_id)}


@tool
def care_plan(cat_id: str) -> dict:
    """Plan preventivo sugerido para la edad del gato (purgante, antipulgas, chequeo, dental) marcando lo que ya
    está programado, más las vacunas pendientes. Propónlo al usuario y crea con add_reminder solo lo que acepte."""
    return _store().care_plan(_owner(), cat_id)


@tool
def add_reminder(
    cat_id: str,
    title: str,
    kind: str = "otro",
    due_date: str | None = None,
    last_done: str | None = None,
    repeat: str | None = None,
    product: str | None = None,
    notes: str | None = None,
) -> dict:
    """Crea un recordatorio. kind: purgante, antipulgas, vacuna, medicamento, chequeo, dental, estetica u otro.
    Da due_date si el usuario sabe la próxima fecha; si solo sabe cuándo se aplicó la última vez, pasa last_done
    con repeat y el servidor calcula la próxima; sin ninguna, queda para hoy.
    repeat usa las frecuencias de las vacunas (mensual, trimestral, semestral, anual…); al completarlo se programa
    el siguiente. product: nombre del producto o medicamento (p. ej. 'Drontal', 'Revolution'). Para vacunas ya
    registradas no hace falta: su próxima dosis ya aparece en la agenda."""
    return _store().add_reminder(_owner(), cat_id, title, due_date, repeat, notes, kind, product, last_done)


@tool
def list_reminders(cat_id: str | None = None, include_completed: bool = False) -> dict:
    """Recordatorios del usuario (o de un gato), por fecha. include_completed=true incluye el historial."""
    return {"reminders": _store().reminders(_owner(), cat_id, include_completed), "kinds": care.REMINDER_KINDS}


@tool
def update_reminder(reminder_id: str, title: str | None = None, due_date: str | None = None,
                    repeat: str | None = None, product: str | None = None, notes: str | None = None) -> dict:
    """Cambia fecha, frecuencia, producto o notas de un recordatorio."""
    return _store().update_reminder(_owner(), reminder_id, title, due_date, repeat, product, notes)


@tool
def delete_reminder(reminder_id: str) -> dict:
    """Borra un recordatorio. Confirma con el usuario antes."""
    return _store().delete_reminder(_owner(), reminder_id)


@tool
def complete_reminder(reminder_id: str, done_date: str | None = None) -> dict:
    """Marca un recordatorio como hecho (hoy o en done_date) y, si se repite, programa el siguiente contando desde
    esa fecha. Para vacunas registradas usa apply_vaccine_dose."""
    return _store().complete_reminder(_owner(), reminder_id, done_date)


@tool
def calendar_subscription(rotate: bool = False) -> dict:
    """Conecta la agenda de Cat Life a la aplicación de calendario predeterminada del usuario (Calendario de Mac
    o iPhone, Outlook, Google Calendar). Se hace una sola vez: desde entonces cada vacuna, recordatorio o cita que
    crees aparece sola en su calendario, con avisos un día antes y el mismo día. Comparte subscribe_page como
    enlace. rotate=true invalida el enlace anterior."""
    token = _store().calendar_token(_owner(), rotate)
    return {
        **render.calendar_links(config.PUBLIC_URL, token),
        "how_to": "Abre subscribe_page y pulsa 'Agregar a mi calendario'; el computador abre su app de calendario "
                  "y pide confirmar la suscripción. En Mac elige 'Actualizar automáticamente: cada 5 minutos'.",
    }


# --- historial clínico -----------------------------------------------------------------------------


@tool
def add_medical_record(
    cat_id: str,
    record_type: str = "consulta",
    date: str | None = None,
    reason: str | None = None,
    symptoms: list[str] | None = None,
    diagnosis: str | None = None,
    treatment: str | None = None,
    medications: list[dict] | None = None,
    exam_results: list[dict] | None = None,
    weight_kg: float | None = None,
    temperature_c: float | None = None,
    veterinarian: str | None = None,
    clinic: str | None = None,
    cost: str | None = None,
    next_appointment: str | None = None,
    notes: str | None = None,
) -> dict:
    """Agrega una entrada al historial clínico. record_type: consulta, emergencia, vacunacion, cirugia, chequeo,
    dental, laboratorio, imagenologia, estetica, comportamiento u otro. medications: [{name, dosage, duration,
    instructions, start_date, end_date}]. exam_results: [{exam_type, results, normal_range, is_normal}].
    El peso se suma al historial de peso y next_appointment crea la cita de seguimiento."""
    return _store().add_record(
        _owner(), cat_id, record_type=record_type, date=date, reason=reason, symptoms=symptoms,
        diagnosis=diagnosis, treatment=treatment, medications=medications, exam_results=exam_results,
        weight_kg=weight_kg, temperature_c=temperature_c, veterinarian=veterinarian, clinic=clinic, cost=cost,
        next_appointment=next_appointment, notes=notes,
    )


@tool
def list_medical_history(cat_id: str, record_type: str | None = None) -> dict:
    """Historial clínico del gato, del más reciente al más antiguo; opcionalmente de un solo tipo."""
    return {"records": _store().records(_owner(), cat_id, record_type), "types": care.RECORD_TYPES}


@tool
def delete_medical_record(record_id: str) -> dict:
    """Borra una entrada del historial clínico."""
    return _store().delete_record(_owner(), record_id)


@tool
def health_summary(cat_id: str) -> dict:
    """Resumen de salud: última visita, peso actual y tendencia, condiciones y medicamentos activos,
    pendientes vencidos y próximos."""
    return _store().health_summary(_owner(), cat_id)


@tool
def log_weight(cat_id: str, weight_kg: float, date: str | None = None, notes: str | None = None) -> dict:
    """Registra un peso (kg) y lo deja como peso actual del gato."""
    return _store().add_weight(_owner(), cat_id, weight_kg, date, notes)


@tool
def weight_history(cat_id: str) -> dict:
    """Serie completa de peso (date, weight_kg) para graficar en un artefacto. No inventes puntos."""
    return {"weights": _store().weights(_owner(), cat_id)}


@tool
def add_condition(
    cat_id: str,
    name: str,
    condition_type: str,
    severity: str = "leve",
    description: str | None = None,
    diagnosed: str | None = None,
    treatment: str | None = None,
    notes: str | None = None,
) -> dict:
    """Registra una alergia o condición. condition_type: alergia, enfermedad_cronica, condicion_genetica, lesion,
    infeccion, comportamental, otro. severity: leve, moderado, severo, critico."""
    return _store().add_condition(_owner(), cat_id, name=name, condition_type=condition_type, severity=severity,
                                  description=description, diagnosed=diagnosed, treatment=treatment, notes=notes)


@tool
def list_conditions(cat_id: str) -> dict:
    """Alergias y condiciones del gato, activas e inactivas."""
    return {"conditions": _store().conditions(_owner(), cat_id)}


@tool
def update_condition(condition_id: str, active: bool | None = None, treatment: str | None = None,
                     notes: str | None = None) -> dict:
    """Actualiza una condición; active=false la marca como resuelta."""
    return _store().update_condition(_owner(), condition_id, active, treatment, notes)


@tool
def add_appointment(cat_id: str, date: str, reason: str, time: str | None = None, veterinarian: str | None = None,
                    clinic: str | None = None, notes: str | None = None) -> dict:
    """Agenda una cita veterinaria. time en HH:MM (24 h)."""
    return _store().add_appointment(_owner(), cat_id, date, time, reason, veterinarian, clinic, notes)


@tool
def list_appointments(cat_id: str | None = None) -> dict:
    """Citas del usuario (o de un gato) con su estado."""
    return {"appointments": _store().appointments(_owner(), cat_id)}


@tool
def update_appointment(appointment_id: str, status: str | None = None, date: str | None = None,
                       time: str | None = None, notes: str | None = None) -> dict:
    """Cambia estado o fecha de una cita. status: programada, confirmada, completada, cancelada, no_asistio."""
    return _store().update_appointment(_owner(), appointment_id, status, date, time, notes)


@tool
def save_veterinarian(name: str, clinic: str | None = None, phone: str | None = None, email: str | None = None,
                      address: str | None = None, emergency_hours: str | None = None, website: str | None = None,
                      primary: bool = False, notes: str | None = None) -> dict:
    """Guarda un veterinario en los contactos del usuario; primary=true lo deja como principal."""
    return _store().add_vet(_owner(), name=name, clinic=clinic, phone=phone, email=email, address=address,
                            emergency_hours=emergency_hours, website=website, primary=primary, notes=notes)


@tool
def list_veterinarians() -> dict:
    """Contactos veterinarios guardados por el usuario."""
    return {"veterinarians": _store().vets(_owner())}


@tool
def delete_veterinarian(vet_id: str) -> dict:
    """Borra un contacto veterinario."""
    return _store().delete_vet(_owner(), vet_id)


@tool
def find_veterinaries(location: str | None = None, latitude: float | None = None, longitude: float | None = None,
                      emergency: bool = False) -> dict:
    """Busca veterinarias cerca (radio de 10 km) con Google Places. location: barrio y ciudad, p. ej.
    'Chapinero, Bogotá'. emergency=true busca urgencias 24 horas."""
    if not config.PLACES_API_KEY:
        return {"error": "La búsqueda de veterinarias no está configurada (falta GOOGLE_PLACES_API_KEY)."}
    if not location and (latitude is None or longitude is None):
        return {"error": "Pide al usuario su barrio y ciudad."}
    _owner()
    with httpx.Client(timeout=20) as client:
        return {"veterinaries": search_places(client, config.PLACES_API_KEY, location, latitude, longitude, emergency)}


# --- carné y redes ---------------------------------------------------------------------------------


def _shared(cat_id: str, rotate: bool = False) -> tuple[str, dict]:
    owner = _owner()
    token = _store().share_token(owner, cat_id, rotate)
    return config.card_url(token), _store().public_card(token)


@tool
def show_card(cat_id: str) -> list:
    """Muestra en el chat la imagen del carné de vacunación (foto, datos, vacunas y QR). Activa el enlace
    público del carné si aún no existía."""
    url, card = _shared(cat_id)
    photo = _store().photo(cat_id) if card["cat"]["has_photo"] else None
    png = render.card_png(card, url, photo["data"] if photo else None)
    return [Image(data=png, format="png"), {"card_url": url, "image_url": f"{url}/imagen.png"}]


@tool
def share_card(cat_id: str, rotate: bool = False) -> list:
    """Comparte el carné: devuelve el QR, el enlace público y enlaces listos para WhatsApp, Facebook, X,
    Telegram y correo. Para Instagram o TikTok entrega image_url (descargar y subir). rotate=true genera un
    enlace nuevo e invalida el anterior."""
    url, card = _shared(cat_id, rotate)
    text = f"Carné de vacunación de {card['cat']['name']} 🐱"
    return [
        Image(data=render.qr_png(url), format="png"),
        {"card_url": url, "qr_url": f"{url}/qr.png", "image_url": f"{url}/imagen.png",
         "share": render.share_links(url, text),
         "instagram": "Descarga image_url y súbela como publicación o historia; agrega card_url en la descripción."},
    ]


@tool
def stop_sharing_card(cat_id: str) -> dict:
    """Desactiva el enlace público y el QR del carné; los ya compartidos dejan de funcionar."""
    return _store().stop_sharing(_owner(), cat_id)


# --- familia --------------------------------------------------------------------------------------


@tool
def family_status() -> dict:
    """Hogar familiar del usuario: miembros (usuarios de MIA) e invitaciones pendientes que le enviaron.
    Úsala al iniciar la conversación; si hay invitaciones pendientes, muéstralas antes que nada."""
    me = _identity()
    return {**config.family().status(me.user_id), "pending_invitations": config.family().pending(me.email)}


@tool
def share_cats_with(email: str) -> dict:
    """Comparte los gatos del usuario con otro usuario de MIA por su correo: queda invitado al hogar familiar y
    recibe un correo (si MIA tiene correo configurado) y un aviso al abrir el agente Cat Life. La otra persona
    decide si acepta. Confirma el correo con el usuario antes de llamarla."""
    me = _identity()
    if config.mia_user_exists(email) is False:
        return {"error": f"No hay ninguna cuenta de MIA con el correo {email}. Pídele que se registre en "
                         f"{config.MIA_URL} y vuelve a intentarlo."}
    invite = config.family().invite_email(me.user_id, me.name, me.email, email)
    mailer = notify.Mailer.from_env()
    email_sent = False
    if mailer is not None:
        cats = [cat["name"] for cat in _store().cats(_owner())]
        try:
            mailer.send(notify.invitation(invite["email"], me.name or "Un usuario de MIA", cats, invite["code"],
                                          config.MIA_URL))
            email_sent = True
        except OSError:
            email_sent = False
    return {**invite, "email_sent": email_sent, "in_app_notice": True,
            "note": "Verá la invitación al abrir el agente Cat Life en MIA y podrá aceptarla o rechazarla."}


@tool
def accept_family_invitation(code: str, bring_my_cats: bool = True) -> dict:
    """Acepta una invitación pendiente (de family_status) o un código que le dieron. bring_my_cats=true comparte
    también los gatos que ya tenía; con false quedan aparte y vuelven si sale del hogar. Pregunta antes."""
    me = _identity()
    return config.family().join(me.user_id, me.name, code, bring_my_cats, me.email)


@tool
def decline_family_invitation(code: str) -> dict:
    """Rechaza una invitación pendiente."""
    return config.family().decline(_identity().email, code)


@tool
def invite_to_family() -> dict:
    """Código de invitación (8 caracteres, válido 7 días, sirve para varias personas) para quien no quiera dar su
    correo. Si el usuario aún no tiene hogar, lo crea con sus gatos. Prefiere share_cats_with cuando den un correo."""
    me = _identity()
    invite = config.family().invite(me.user_id, me.name)
    return {**invite, "how_to": "La otra persona entra a MIA con su cuenta, abre el agente Cat Life y escribe: "
                                f"'quiero unirme a mi familia con el código {invite['code']}'."}


@tool
def leave_family() -> dict:
    """Saca al usuario del hogar. Los gatos se quedan con la familia; si es el último miembro, se los lleva.
    Confirma antes."""
    return config.family().leave(_identity().user_id)


@tool
def remove_family_member(member_user_id: str) -> dict:
    """Saca a otra persona del hogar (solo quien lo administra). Usa el user_id de family_status. Confirma antes."""
    return config.family().remove(_identity().user_id, member_user_id)


@tool
def family_activity(days: int = 7) -> dict:
    """Qué cambió en los gatos del hogar y quién lo hizo en los últimos días (is_you=false son otros miembros).
    Úsala al iniciar la conversación para contar lo que hicieron los demás."""
    me = _identity()
    return {"activity": config.family().activity(config.family().space(*me), me.user_id, days)}


# --- guías -----------------------------------------------------------------------------------------


@tool
def human_age(age_months: int) -> dict:
    """Edad equivalente en años humanos según la tabla de Cat Life."""
    return {"age_months": age_months, "human_age": care.human_age(age_months)}


@tool
def teeth_age_guide() -> dict:
    """Guía para estimar la edad de un gato por sus dientes. Pregunta al usuario qué ve y usa el rango."""
    return {"stages": [{"teeth": teeth, "age": age} for teeth, age in care.TEETH_AGE]}


@tool
def mood_guide() -> dict:
    """Los 12 estados de ánimo felinos con sus señales corporales, para interpretar lo que describe el usuario."""
    return {"moods": [{"mood": mood, "description": text, "signals": signals} for mood, text, signals in care.MOODS]}


if __name__ == "__main__":
    from catlife.serve import serve

    serve(mcp.streamable_http_app(), 8001)
