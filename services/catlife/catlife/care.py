"""Pure pet-care rules: vaccine schedules and dose naming from the Cat Life Android app, plus per-species age
tables, teeth guides, body language and preventive plans for cats and dogs.

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

SPECIES = {"gato": ("gato", "gatos"), "perro": ("perro", "perros")}
BRANDS = {"gato": "Cuidador Felino", "perro": "Cuidador Canino"}
DEFAULT_SPECIES = "gato"

CAT_HUMAN_AGE = [
    (2, "1-4 años"),
    (4, "6-8 años"),
    (6, "10 años"),
    (7, "12 años"),
    (12, "15 años"),
    (18, "21 años"),
    (24, "24 años"),
    *((months, f"{24 + 4 * (months // 12 - 2)} años") for months in range(36, 229, 12)),
]
PUPPY_HUMAN_AGE = [(2, "2-3 años"), (4, "5-6 años"), (6, "8-10 años"), (9, "12 años"), (12, "15 años"),
                   (18, "20 años"), (24, "24 años")]
DOG_SIZES = {
    "pequeno": {"label": "pequeño (menos de 10 kg)", "max_kg": 10, "years_per_year": 4, "senior_years": 8},
    "mediano": {"label": "mediano (10 a 25 kg)", "max_kg": 25, "years_per_year": 5, "senior_years": 7},
    "grande": {"label": "grande (25 a 45 kg)", "max_kg": 45, "years_per_year": 6, "senior_years": 6},
    "gigante": {"label": "gigante (más de 45 kg)", "max_kg": float("inf"), "years_per_year": 7, "senior_years": 5},
}

TEETH_AGE = {
    "gato": [
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
    ],
    "perro": [
        ("No tiene dientes", "0-2 semanas"),
        ("Están saliendo los incisivos de leche", "3-4 semanas"),
        ("Tiene caninos y premolares de leche", "4-6 semanas"),
        ("Dentadura de leche completa (28 dientes)", "6-8 semanas"),
        ("Cambiando los incisivos de leche por permanentes", "3-4 meses"),
        ("Salen los caninos y las muelas permanentes", "4-6 meses"),
        ("Dentadura permanente completa (42 dientes) y muy blanca", "6-12 meses"),
        ("Dientes blancos con poco o nada de sarro", "1-2 años"),
        ("Algo de sarro en las muelas de atrás y leve desgaste", "3-5 años"),
        ("Sarro visible y desgaste de los incisivos", "5-8 años"),
        ("Sarro abundante, encías retraídas o dientes faltantes", "8 años o más"),
    ],
}

MOODS = {
    "gato": [
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
         ["Sentado en posición estable", "Mirada contemplativa", "Muy quieto por largos períodos",
          "Estado meditativo"]),
    ],
    "perro": [
        ("FELIZ", "Tu perro está contento y cómodo con lo que pasa a su alrededor.",
         ["Cola que se mueve amplia a media altura", "Boca abierta y relajada", "Cuerpo suelto"]),
        ("JUGUETÓN", "Tu perro te invita a jugar.",
         ["Reverencia de juego: patas delanteras abajo y cola arriba", "Saltos y carreras cortas",
          "Ladridos agudos y cortos"]),
        ("RELAJADO", "Tu perro descansa tranquilo y se siente seguro.",
         ["Tumbado de lado o panza arriba", "Respiración lenta", "Mirada suave"]),
        ("ALERTA", "Tu perro vigila algo que le llamó la atención.",
         ["Orejas hacia adelante", "Cuerpo quieto y erguido", "Cola alta y quieta", "Boca cerrada"]),
        ("CURIOSO", "Tu perro está investigando algo nuevo.",
         ["Cabeza ladeada", "Olfatea mucho", "Se acerca despacio"]),
        ("ANSIOSO", "Tu perro está estresado o incómodo.",
         ["Jadea sin tener calor", "Bosteza y se relame seguido", "Se le ve lo blanco de los ojos",
          "Camina de un lado a otro"]),
        ("ASUSTADO", "Tu perro tiene miedo y quiere alejarse.",
         ["Cola entre las patas", "Orejas pegadas hacia atrás", "Cuerpo agachado", "Tiembla o se esconde"]),
        ("SUMISO", "Tu perro quiere calmar la situación y evitar conflicto.",
         ["Se tumba panza arriba", "Evita la mirada", "Lame la cara o las manos"]),
        ("DEFENSIVO", "Tu perro se siente amenazado y avisa que no quiere que se acerquen.",
         ["Pelo del lomo erizado", "Gruñe", "Muestra los dientes", "Cuerpo inclinado hacia atrás"]),
        ("AGRESIVO", "Tu perro podría morder. Dale espacio y no lo fuerces.",
         ["Cuerpo rígido hacia adelante", "Mirada fija", "Labios recogidos mostrando dientes",
          "Gruñido grave", "Cola alta y rígida"]),
        ("CANSADO", "Tu perro necesita descanso.",
         ["Bosteza", "Se echa en cuanto puede", "Se mueve despacio"]),
        ("CON DOLOR", "Tu perro podría estar adolorido: consulta a su veterinario.",
         ["Se lame una zona insistentemente", "Cojea o se mueve encorvado", "No quiere que lo toquen",
          "Gime o jadea en reposo"]),
    ],
}

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
    "estetica": "✂️ Estética (baño, peluquería)",
    "corazon": "❤️ Prevención del gusano del corazón",
    "unas": "💅 Corte de uñas",
    "otro": "⏰ Otro",
}

YOUNG_MONTHS = 6
CAT_SENIOR_MONTHS = 7 * 12


def species_key(species: str | None) -> str:
    key = (species or DEFAULT_SPECIES).strip().lower()
    if key not in SPECIES:
        raise ValueError(f"Especie no soportada: {species!r}. Opciones: {', '.join(SPECIES)}")
    return key


def dog_size(weight_kg: float | None, size: str | None = None) -> str | None:
    """The given size, or the one implied by the dog's adult weight."""
    if size:
        key = size.strip().lower().replace("ñ", "n")
        if key not in DOG_SIZES:
            raise ValueError(f"Tamaño desconocido. Opciones: {', '.join(DOG_SIZES)}")
        return key
    if weight_kg is None:
        return None
    return next(name for name, info in DOG_SIZES.items() if float(weight_kg) < info["max_kg"])


def care_plan(species: str, age_months: int | None, size: str | None = None) -> list[dict]:
    """Common preventive schedule by species and life stage. Guidance only: the pet's veterinarian sets the
    real one."""
    young = age_months is not None and age_months < YOUNG_MONTHS
    senior_months = DOG_SIZES[size]["senior_years"] * 12 if species == "perro" and size else CAT_SENIOR_MONTHS
    senior = age_months is not None and age_months >= senior_months
    plan = [
        {"kind": "purgante", "title": "Purgante (desparasitación interna)",
         "repeat": "mensual" if young else "trimestral",
         "why": "Cachorros: cada mes hasta los 6 meses. Adultos: cada 3 meses, o según su veterinario."},
        {"kind": "antipulgas", "title": "Antipulgas y garrapatas (desparasitación externa)", "repeat": "mensual",
         "why": "Pipeta, collar o tableta; la frecuencia depende del producto."},
        {"kind": "chequeo", "title": "Chequeo veterinario", "repeat": "semestral" if senior or young else "anual",
         "why": "Una vez al año en adultos; cada 6 meses en cachorros y en la etapa senior."},
        {"kind": "dental", "title": "Revisión dental", "repeat": "anual",
         "why": "El sarro y la enfermedad de encías son comunes desde los 2 a 3 años."},
    ]
    if species == "perro":
        plan += [
            {"kind": "corazon", "title": "Prevención del gusano del corazón", "repeat": "mensual",
             "why": "Se transmite por mosquitos; es clave en zonas cálidas. Su veterinario indica si aplica."},
            {"kind": "unas", "title": "Corte de uñas", "repeat": "mensual",
             "why": "Si suenan al caminar sobre piso duro, ya están largas."},
            {"kind": "estetica", "title": "Baño", "repeat": "mensual",
             "why": "Entre cada 3 y 6 semanas según el pelaje y la actividad."},
        ]
    return plan


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


def human_age(months: int, species: str = DEFAULT_SPECIES, size: str | None = None) -> str:
    """Equivalent human age. Cats follow the Cat Life table; dogs age faster the bigger they are."""
    if months < 0:
        raise ValueError("La edad en meses no puede ser negativa.")
    if species != "perro":
        return next((label for limit, label in CAT_HUMAN_AGE if months <= limit), "96+ años")
    young = next((label for limit, label in PUPPY_HUMAN_AGE if months <= limit), None)
    if young:
        return young
    per_year = DOG_SIZES[size or "mediano"]["years_per_year"]
    return f"{24 + per_year * (months // 12 - 2)} años" + ("" if size else " (aprox., según su tamaño)")


def age_in_months(birth: date, today: date) -> int:
    return max(0, (today.year - birth.year) * 12 + today.month - birth.month - (today.day < birth.day))
