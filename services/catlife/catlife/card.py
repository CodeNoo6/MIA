"""Renderings of a shared carné: QR code, a 1080x1350 image for social networks, and the iCalendar feed."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

from catlife import care

FONT_PATHS = {
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
INK = (34, 30, 46)
MUTED = (110, 104, 128)
ACCENT = (124, 77, 255)
PAPER = (250, 248, 255)
OK = (46, 125, 50)
LATE = (198, 40, 40)
WIDTH, HEIGHT = 1080, 1350
VACCINES_BOTTOM = HEIGHT - 300
VACCINE_ROW = 84


def share_links(url: str, text: str) -> dict:
    """Prefilled share intents; Instagram and TikTok have none, so they take the downloadable image."""
    message = quote(f"{text} {url}")
    return {
        "whatsapp": f"https://wa.me/?text={message}",
        "facebook": f"https://www.facebook.com/sharer/sharer.php?u={quote(url)}",
        "x": f"https://twitter.com/intent/tweet?text={quote(text)}&url={quote(url)}",
        "telegram": f"https://t.me/share/url?url={quote(url)}&text={quote(text)}",
        "email": f"mailto:?subject={quote(text)}&body={message}",
    }


def calendar_links(public_url: str, token: str) -> dict:
    """Subscribe links for one user's feed. webcal:// opens the computer's default calendar app (Calendario
    en Mac, Outlook en Windows); Google only accepts feeds on a public https address."""
    ics = f"{public_url}/calendario/{token}.ics"
    webcal = "webcal://" + ics.split("://", 1)[1]
    return {
        "subscribe_page": f"{public_url}/calendario/{token}",
        "webcal_url": webcal,
        "ics_url": ics,
        "google_calendar": f"https://calendar.google.com/calendar/r?cid={quote(webcal, safe='')}"
        if ics.startswith("https://") else None,
    }


def qr_png(data: str, box: int = 10) -> bytes:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box, border=2)
    code.add_data(data)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATHS[bold], size)
    except OSError:
        return ImageFont.load_default(size=size)


def _yes(value: object) -> str:
    return "Sí" if value else "No"


def dmy(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d/%m/%Y") if value else "—"


def pet_facts(pet: dict) -> list[tuple[str, str]]:
    size = care.DOG_SIZES.get(pet.get("size") or "", {}).get("label", "").split(" (")[0]
    facts = [
        ("Especie", care.SPECIES[pet.get("species", care.DEFAULT_SPECIES)][0].capitalize()),
        ("Raza", pet.get("breed") or "Mestizo"),
        ("Género", pet.get("gender") or "—"),
        ("Color", pet.get("color") or "—"),
        ("Edad", f"{pet['age_months']} meses" if "age_months" in pet else "—"),
        ("Edad humana", pet.get("human_age") or "—"),
        ("Peso", f"{pet['weight_kg']} kg" if pet.get("weight_kg") else "—"),
        *((("Tamaño", size.capitalize()),) if size else ()),
        ("Esterilizado", _yes(pet.get("sterilized"))),
        ("Microchip", _yes(pet.get("microchip"))),
    ]
    return facts


def card_png(card: dict, url: str, photo: bytes | None) -> bytes:
    pet, vaccines = card["pet"], card["vaccines"]
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 200), fill=ACCENT)
    species = care.SPECIES[pet.get("species", care.DEFAULT_SPECIES)][0].upper()
    draw.text((60, 50), f"CARNÉ DE VACUNACIÓN · {species}", font=_font(34, True), fill="white")
    draw.text((60, 100), pet["name"], font=_font(64, True), fill="white")

    avatar = (60, 240, 380, 560)
    if photo:
        picture = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (320, 320))
        mask = Image.new("L", (320, 320), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 320, 320), fill=255)
        image.paste(picture, avatar[:2], mask)
    else:
        draw.ellipse(avatar, fill=(232, 224, 255))
        draw.text((220, 400), pet["name"][:1].upper(), font=_font(140, True), fill=ACCENT, anchor="mm")

    y = 240
    for label, value in pet_facts(pet):
        draw.text((420, y), label, font=_font(26), fill=MUTED)
        draw.text((620, y), value, font=_font(28, True), fill=INK)
        y += 40

    y = max(600, y + 24)
    draw.text((60, y), "Vacunas", font=_font(40, True), fill=INK)
    y += 64
    today = card["generated"]
    fits = max(1, (VACCINES_BOTTOM - y) // VACCINE_ROW)
    shown = vaccines[:fits] if len(vaccines) <= fits else vaccines[:fits - 1]
    for vaccine in shown:
        due = vaccine.get("next_due")
        color = LATE if due and due < today else OK
        draw.ellipse((60, y + 8, 80, y + 28), fill=color)
        draw.text((100, y), vaccine["name"], font=_font(30, True), fill=INK)
        detail = f"Aplicada: {dmy(vaccine.get('last_applied'))}   Próxima: {dmy(due)}"
        draw.text((100, y + 38), detail, font=_font(24), fill=MUTED)
        y += VACCINE_ROW
    if not vaccines:
        draw.text((60, y), "Aún no hay vacunas registradas.", font=_font(28), fill=MUTED)
    if len(vaccines) > len(shown):
        draw.text((60, y), f"+{len(vaccines) - len(shown)} vacunas más en el carné en línea", font=_font(24),
                  fill=MUTED)

    code = Image.open(io.BytesIO(qr_png(url, 6))).resize((220, 220))
    image.paste(code, (WIDTH - 280, HEIGHT - 280))
    draw.text((60, HEIGHT - 190), "Escanea el código para ver", font=_font(28), fill=MUTED)
    draw.text((60, HEIGHT - 150), "el carné actualizado", font=_font(28), fill=MUTED)
    brand = care.BRANDS[pet.get("species", care.DEFAULT_SPECIES)]
    draw.text((60, HEIGHT - 90), f"MIA · {brand}", font=_font(30, True), fill=ACCENT)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 folding: lines over 75 octets continue on the next line after a space, never splitting a UTF-8 char."""
    parts, current = [], ""
    for char in line:
        if len((current + char).encode()) > (75 if not parts else 74):
            parts.append(current)
            current = ""
        current += char
    return "\r\n ".join([*parts, current])


def calendar_ics(items: list[dict]) -> str:
    """All-day events (or timed ones for appointments) with a one-day-before and same-day alarm."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MIA//Cuidado animal//ES", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:MIA · Cuidado animal", "X-PUBLISHED-TTL:PT1H", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    for item in items:
        day = date.fromisoformat(item["date"])
        if item.get("time"):
            start = datetime.combine(day, datetime.strptime(item["time"], "%H:%M").time())
            when = [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{start + timedelta(hours=1):%Y%m%dT%H%M%S}"]
        else:
            when = [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
        summary = _ics_text(f"{item['pet']}: {item['title']}")
        lines += ["BEGIN:VEVENT", f"UID:{item['kind']}-{item['id']}-{item['date']}@catlife.mia", f"DTSTAMP:{stamp}",
                  *when, f"SUMMARY:{summary}"]
        if item.get("detail"):
            lines.append(f"DESCRIPTION:{_ics_text(item['detail'])}")
        for trigger in ("-P1D", "PT9H"):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{summary}", f"TRIGGER:{trigger}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
