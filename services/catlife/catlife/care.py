"""Pure rules ported from the Cat Life Android app: vaccine schedules, dose naming, age tables and moods.

Dates travel as ISO strings (YYYY-MM-DD). `parse_date` also accepts the app's DD/MM/YYYY.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime

FREQUENCY_MONTHS = {
    "anual": 12,
    "anualmente": 12,
    "cada año": 12,
    "cada 6 meses": 6,
    "semestral": 6,
    "cada 3 meses": 3,
    "trimestral": 3,
    "cada 2 meses": 2,
    "bimestral": 2,
    "mensual": 1,
    "cada mes": 1,
}
SINGLE_DOSE = {"", "una sola vez", "única", "unica"}
FREQUENCIES = sorted(set(FREQUENCY_MONTHS) | {"una sola vez"})

HUMAN_AGE = [
    (2, "1-4 años"),
    (4, "6-8 años"),
    (6, "10 años"),
    (7, "12 años"),
    (12, "15 años"),
    (18, "21 años"),
    (24, "24 años"),
    *((months, f"{24 + 4 * (months // 12 - 2)} años") for months in range(36, 229, 12)),
]

TEETH_AGE = [
    ("No tiene dientes", "0-2 semanas"),
    ("Están saliendo dientes frontales", "2-4 semanas"),
    ("Tiene caninos (dientes largos y puntiagudos)", "4-6 semanas"),
    ("Crecimiento de premolares", "6-8 semanas"),
    ("Todos los dientes de leche", "2-4 meses"),
    ("Cambiando dientes de leche por permanentes", "4-6 meses"),
    ("Dentadura permanente completa", "6-12 meses"),
    ("Dientes blancos y limpios", "1-2 años"),
    ("Dientes amarillentos con poco sarro", "2-4 años"),
    ("Sarro extendido y desgaste visible", "4-7 años"),
    ("Dientes deteriorados con cambio en encías", "7-10 años"),
]

MOODS = [
    ("CONTENTO", "Tu gato está feliz y relajado. Cola levantada, postura erguida con confianza.",
     ["Cola alta y erguida", "Postura relajada", "Camina con confianza"]),
    ("AMIGABLE", "Tu gato busca interacción y cariño. Se acerca a ti con confianza y tranquilidad.",
     ["Se acerca calmadamente", "Cola en posición neutral", "Maullidos suaves"]),
    ("SUMISO", "Tu gato muestra respeto y sumisión. Postura baja sin representar amenaza.",
     ["Postura baja y pequeña", "Cola hacia abajo", "Evita contacto visual"]),
    ("RELAJADO", "Estado de completa relajación y bienestar. Tu gato se siente completamente cómodo.",
     ["Postura completamente relajada", "Respiración calmada", "Ojos entrecerrados"]),
    ("DEFENSIVO", "Tu gato se siente amenazado y adopta una posición defensiva con el pelo erizado.",
     ["Pelo completamente erizado", "Espalda arqueada", "Postura lateral intimidante"]),
    ("SEGURO", "Tu gato se siente confiado y protegido. Muestra seguridad con el pelo ligeramente erizado.",
     ["Postura erguida y segura", "Pelo ligeramente erizado", "Movimientos decididos"]),
    ("ALERTA", "Tu gato está muy alerta y observando algo específico con gran atención.",
     ["Orejas completamente erectas", "Cola quieta y tensa", "Ojos muy enfocados", "Máxima concentración"]),
    ("ASUSTADO", "Tu gato está muy temeroso. Pelo erizado por miedo, busca protección o huida.",
     ["Pelo erizado por miedo", "Postura muy agachada", "Ojos muy abiertos", "Temblores visibles"]),
    ("IRRITADO", "Tu gato está molesto y muestra clara irritación. Puede volverse agresivo.",
     ["Cola azotando violentamente", "Orejas hacia atrás", "Postura tensa", "Gruñidos de advertencia"]),
    ("INTERESADO", "Tu gato siente gran curiosidad por algo específico en su entorno.",
     ["Cabeza ligeramente inclinada", "Orejas muy erectas", "Se acerca cautelosamente", "Olfatea intensamente"]),
    ("AGRESIVO", "Tu gato está en modo de ataque. Postura muy amenazante y peligrosa.",
     ["Postura muy agachada y amenazante", "Cola baja y tensa", "Siseos intensos", "Listo para atacar"]),
    ("PENSATIVO", "Tu gato está en estado contemplativo, sentado y observando tranquilamente.",
     ["Sentado en posición estable", "Mirada contemplativa", "Muy quieto por largos períodos", "Estado meditativo"]),
]

RECORD_TYPES = {
    "consulta": "🩺 Consulta General",
    "emergencia": "🚨 Emergencia",
    "vacunacion": "💉 Vacunación",
    "cirugia": "⚕️ Cirugía",
    "chequeo": "📋 Chequeo",
    "dental": "🦷 Dental",
    "laboratorio": "🔬 Laboratorio",
    "imagenologia": "📷 Imagenología",
    "estetica": "✂️ Estética",
    "comportamiento": "🧠 Comportamiento",
    "otro": "📝 Otro",
}
REMINDER_KINDS = {
    "purgante": "💊 Desparasitación interna (purgante)",
    "antipulgas": "🐛 Desparasitación externa (pulgas y garrapatas)",
    "vacuna": "💉 Vacuna",
    "medicamento": "💊 Medicamento",
    "chequeo": "🩺 Chequeo",
    "dental": "🦷 Dental",
    "estetica": "✂️ Estética",
    "otro": "⏰ Otro",
}

KITTEN_MONTHS = 6
SENIOR_MONTHS = 7 * 12


def care_plan(age_months: int | None) -> list[dict]:
    """Common preventive schedule by life stage. Guidance only: the cat's veterinarian sets the real one."""
    kitten = age_months is not None and age_months < KITTEN_MONTHS
    senior = age_months is not None and age_months >= SENIOR_MONTHS
    return [
        {"kind": "purgante", "title": "Purgante (desparasitación interna)",
         "repeat": "mensual" if kitten else "trimestral",
         "why": "Cachorros: cada mes hasta los 6 meses. Adultos: cada 3 meses, o según su veterinario."},
        {"kind": "antipulgas", "title": "Antipulgas (desparasitación externa)", "repeat": "mensual",
         "why": "Pipeta o tableta mensual; la frecuencia depende del producto."},
        {"kind": "chequeo", "title": "Chequeo veterinario", "repeat": "semestral" if senior or kitten else "anual",
         "why": "Una vez al año en adultos; cada 6 meses en cachorros y mayores de 7 años."},
        {"kind": "dental", "title": "Revisión dental", "repeat": "anual",
         "why": "El sarro y la enfermedad de encías son comunes desde los 2 a 3 años."},
    ]


CONDITION_TYPES = ["alergia", "enfermedad_cronica", "condicion_genetica", "lesion", "infeccion", "comportamental", "otro"]
SEVERITIES = ["leve", "moderado", "severo", "critico"]
APPOINTMENT_STATUSES = ["programada", "confirmada", "completada", "cancelada", "no_asistio"]


def parse_date(value: str) -> date:
    """Accept YYYY-MM-DD or the app's DD/MM/YYYY; raise ValueError otherwise."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida: {value!r}. Usa AAAA-MM-DD o DD/MM/AAAA.")


def add_months(start: date, months: int) -> date:
    """Calendar month arithmetic that clamps to the month's last day, like java.util.Calendar.add."""
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def next_due_date(applied: date, frequency: str) -> date | None:
    """Next dose date for a frequency; None for single-dose vaccines. Unknown frequencies raise."""
    key = frequency.strip().lower()
    if key in SINGLE_DOSE:
        return None
    if key not in FREQUENCY_MONTHS:
        raise ValueError(f"Frecuencia no reconocida: {frequency!r}. Opciones: {', '.join(FREQUENCIES)}")
    return add_months(applied, FREQUENCY_MONTHS[key])


DOSE_STEPS = [(("1era", "primera"), "2da"), (("2da", "segunda"), "3era"), (("3era", "tercera"), "Refuerzo")]


def next_dose_name(name: str) -> str:
    """1era → 2da → 3era → Refuerzo; any other name gains '- Refuerzo' once."""
    lowered = name.lower()
    for aliases, successor in DOSE_STEPS:
        for alias in aliases:
            position = lowered.find(alias)
            if position >= 0:
                return name[:position] + successor + name[position + len(alias):]
    if "refuerzo" in lowered:
        return name
    return f"{name} - Refuerzo"


def human_age(months: int) -> str:
    if months < 0:
        raise ValueError("La edad en meses no puede ser negativa.")
    return next((label for limit, label in HUMAN_AGE if months <= limit), "96+ años")


def age_in_months(birth: date, today: date) -> int:
    return max(0, (today.year - birth.year) * 12 + today.month - birth.month - (today.day < birth.day))
