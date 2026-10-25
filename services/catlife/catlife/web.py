"""Public portal of the pet agents (Cat Life and Dog Life): shared carnés, their QR and social image, photo uploads and calendar feeds.

Nothing here is reachable without a random token; a carné token unlocks one pet's profile and vaccines,
a calendar token one user's agenda, and an upload token one photo write for thirty minutes.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from html import escape

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from catlife import card as render
from catlife import care
from catlife.store import NotFound, Store

STYLE = """
:root{--bg:#f6f3ff;--surface:#fff;--ink:#221e2e;--muted:#6e6880;--accent:#7c4dff;--ok:#2e7d32;--late:#c62828;--line:#e6e0f5}
@media (prefers-color-scheme:dark){:root{--bg:#15121c;--surface:#1f1a29;--ink:#f1edf9;--muted:#a59fb8;--accent:#b39dff;--ok:#81c784;--late:#ef9a9a;--line:#332c42}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:720px;margin:0 auto;padding:24px 16px 48px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:24px;margin-bottom:16px}
.head{display:flex;gap:20px;align-items:center;flex-wrap:wrap}
.avatar{width:120px;height:120px;border-radius:50%;object-fit:cover;background:var(--line);display:grid;place-items:center;font-size:48px;font-weight:700;color:var(--accent)}
h1{margin:0;font-size:32px}h2{margin:0 0 12px;font-size:20px}.muted{color:var(--muted)}
dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:0}dt{color:var(--muted);font-size:13px}dd{margin:0;font-weight:600}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px 6px;border-bottom:1px solid var(--line);font-size:15px}
.late{color:var(--late);font-weight:600}.ok{color:var(--ok)}
.share{display:flex;flex-wrap:wrap;gap:8px}.share a,.share button{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:8px 14px;text-decoration:none;font:inherit;cursor:pointer}
.share .primary{background:var(--accent);border-color:var(--accent);color:#fff}
.qr{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.qr img{width:180px;height:180px;border-radius:12px;background:#fff;padding:8px}
input[type=file]{margin:16px 0;display:block}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def _page(title: str, body: str, head: str = "") -> HTMLResponse:
    return HTMLResponse(
        f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>'
        f"{head}<style>{STYLE}</style></head><body><main>{body}</main></body></html>"
    )


def _dmy(value: str | None) -> str:
    return escape(render.dmy(value))


def _card_html(card: dict, url: str) -> HTMLResponse:
    pet = card["pet"]
    name = escape(pet["name"])
    brand = care.BRANDS[pet.get("species", care.DEFAULT_SPECIES)]
    text = f"Carné de vacunación de {pet['name']}"
    avatar = (f'<img class="avatar" src="{url}/foto" alt="Foto de {name}">' if pet["has_photo"]
              else f'<div class="avatar" aria-hidden="true">{escape(pet["name"][:1].upper())}</div>')
    facts = "".join(f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
                    for label, value in render.pet_facts(pet))
    rows = "".join(
        f"<tr><td>{escape(v['name'])}</td><td>{v.get('doses_applied', 0)}</td><td>{_dmy(v.get('last_applied'))}</td>"
        f"<td class=\"{'late' if v.get('next_due') and v['next_due'] < card['generated'] else 'ok'}\">"
        f"{_dmy(v.get('next_due'))}</td></tr>"
        for v in card["vaccines"]
    ) or '<tr><td colspan="4" class="muted">Aún no hay vacunas registradas.</td></tr>'
    links = "".join(f'<a href="{escape(href)}" target="_blank" rel="noopener">{label}</a>'
                    for label, href in zip(("WhatsApp", "Facebook", "X", "Telegram", "Correo"),
                                           render.share_links(url, text).values()))
    payload = json.dumps({"title": text, "url": url}).replace("</", "<\\/")
    head = (
        f'<meta property="og:type" content="website"><meta property="og:title" content="{escape(text)}">'
        f'<meta property="og:description" content="Vacunas y datos de {name}, compartido desde MIA · {brand}.">'
        f'<meta property="og:image" content="{url}/imagen.png"><meta property="og:url" content="{url}">'
        f'<meta name="twitter:card" content="summary_large_image">'
    )
    body = f"""
<section class="card head">{avatar}<div><p class="muted">Carné de vacunación</p><h1>{name}</h1>
<p class="muted">{escape(pet.get('species') or 'Felino')} · actualizado {_dmy(card['generated'])}</p></div></section>
<section class="card"><h2>Datos</h2><dl>{facts}</dl></section>
<section class="card"><h2>Vacunas</h2><table><thead><tr><th>Vacuna</th><th>Dosis</th><th>Aplicada</th><th>Próxima</th></tr></thead>
<tbody>{rows}</tbody></table></section>
<section class="card"><h2>Compartir</h2><div class="qr"><img src="{url}/qr.png" alt="Código QR del carné de {name}">
<div class="share"><button class="primary" id="share" type="button">Compartir…</button>{links}
<a href="{url}/imagen.png" download="carne-{name}.png">Descargar imagen para Instagram</a>
<button id="copy" type="button">Copiar enlace</button></div></div></section>
<script>
const data={payload};
document.getElementById('share').onclick=async()=>{{
  try{{const blob=await (await fetch(data.url+'/imagen.png')).blob();
    const file=new File([blob],'carne.png',{{type:'image/png'}});
    if(navigator.canShare&&navigator.canShare({{files:[file]}})) return await navigator.share({{...data,files:[file]}});
    if(navigator.share) return await navigator.share(data);}}catch(e){{if(e.name==='AbortError')return;}}
  navigator.clipboard.writeText(data.url);document.getElementById('copy').textContent='¡Enlace copiado!';}};
document.getElementById('copy').onclick=e=>{{navigator.clipboard.writeText(data.url);e.target.textContent='¡Enlace copiado!';}};
</script>"""
    return _page(text, body, head)


CALENDAR_SYSTEMS = [
    ("apple", "Mac, iPhone o iPad", "webcal_url", "Agregar a Calendario",
     "Se abre la app Calendario: confirma la suscripción y en Mac elige «Actualizar automáticamente: cada 5 minutos»."),
    ("windows", "Windows (Outlook)", "webcal_url", "Abrir en Outlook",
     "Outlook pregunta si quieres agregar el calendario de Internet: acepta. En Outlook.com: Agregar calendario → "
     "Suscribirse desde la web → pega el enlace."),
    ("android", "Android (Google Calendar)", "google_calendar", "Agregar a Google Calendar",
     "Se abre Google Calendar en la web; al aceptar, aparece en la app del celular con la misma cuenta de Google."),
    ("linux", "Linux (Thunderbird, GNOME o KDE)", "webcal_url", "Abrir en mi calendario",
     "Si no se abre solo: Nuevo calendario → En la red → pega el enlace."),
]


def _calendar_html(links: dict) -> HTMLResponse:
    sections = []
    for system, label, key, action, help_text in CALENDAR_SYSTEMS:
        href = links[key]
        button = (f'<a class="primary" href="{escape(href)}" target="_blank" rel="noopener">{action}</a>' if href
                  else '<span class="muted">Disponible cuando MIA esté publicado con https.</span>')
        sections.append(f'<section class="card" data-os="{system}"><h2>{escape(label)}</h2>'
                        f'<div class="share">{button}</div><p class="muted">{escape(help_text)}</p></section>')
    payload = json.dumps(links["ics_url"]).replace("</", "<\\/")
    return _page("Calendario MIA · Cuidado animal", f"""
<section class="card"><h1>Calendario de tus mascotas</h1>
<p class="muted">Conéctalo una sola vez. Desde entonces cada vacuna, purgante, antipulgas o cita que programes con
el agente aparece sola en tu calendario, con avisos un día antes y el mismo día.</p>
<div class="share"><button id="copy" type="button">Copiar enlace del calendario</button>
<a href="{escape(links["ics_url"])}" download="pet-life.ics">Descargar .ics (copia única, no se actualiza)</a></div>
</section>
<div id="systems">{"".join(sections)}</div>
<script>
const ics={payload};
const ua=navigator.userAgent;
const os=/iPhone|iPad|Macintosh/.test(ua)?'apple':/Android/.test(ua)?'android':/Windows/.test(ua)?'windows':/Linux/.test(ua)?'linux':null;
const mine=os&&document.querySelector('[data-os="'+os+'"]');
if(mine){{mine.querySelector('h2').textContent+=' · tu dispositivo';document.getElementById('systems').prepend(mine);}}
document.getElementById('copy').onclick=e=>{{navigator.clipboard.writeText(ics);e.target.textContent='¡Enlace copiado!';}};
</script>""")


def create_app(get_store: Callable[[], Store], public_url: str) -> FastAPI:
    app = FastAPI(title="Cat Life", docs_url=None, redoc_url=None)

    def card_or_404(token: str) -> dict:
        card = get_store().public_card(token)
        if card is None:
            raise HTTPException(404, "Este carné no existe o su dueño dejó de compartirlo.")
        return card

    def url_for(token: str) -> str:
        return f"{public_url}/carne/{token}"

    def photo_bytes(card: dict) -> dict | None:
        return get_store().photo(card["pet"]["id"]) if card["pet"]["has_photo"] else None

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/carne/{token}", response_class=HTMLResponse)
    def carne(token: str) -> HTMLResponse:
        return _card_html(card_or_404(token), url_for(token))

    @app.get("/carne/{token}/qr.png")
    def qr(token: str) -> Response:
        card_or_404(token)
        return Response(render.qr_png(url_for(token)), media_type="image/png")

    @app.get("/carne/{token}/imagen.png")
    def social_image(token: str) -> Response:
        card = card_or_404(token)
        photo = photo_bytes(card)
        png = render.card_png(card, url_for(token), photo["data"] if photo else None)
        return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

    @app.get("/carne/{token}/foto")
    def cat_photo(token: str) -> Response:
        photo = photo_bytes(card_or_404(token))
        if photo is None:
            raise HTTPException(404, "Esta mascota no tiene foto.")
        return Response(photo["data"], media_type=photo["content_type"])

    @app.get("/foto/{token}", response_class=HTMLResponse)
    def upload_form(token: str) -> HTMLResponse:
        target = get_store().upload_target(token)
        if target is None:
            return _page("Enlace vencido", '<section class="card"><h1>Enlace vencido</h1>'
                         '<p class="muted">Pide un enlace nuevo en el chat de MIA.</p></section>')
        name = escape(target["name"])
        return _page(f"Foto de {target['name']}", f"""
<section class="card"><h1>Foto de {name}</h1><p class="muted">Elige una imagen (máximo 5 MB). Aparecerá en su carné.</p>
<form method="post" enctype="multipart/form-data"><label for="photo">Foto</label>
<input id="photo" name="photo" type="file" accept="image/*" capture="environment" required>
<div class="share"><button class="primary" type="submit">Subir foto</button></div></form></section>""")

    @app.post("/foto/{token}", response_class=HTMLResponse)
    async def upload(token: str, photo: UploadFile = File(...)) -> HTMLResponse:
        try:
            target = get_store().save_photo(token, await photo.read(), photo.content_type or "")
        except NotFound as error:
            return _page("Enlace vencido", f'<section class="card"><h1>Enlace vencido</h1><p>{escape(str(error))}</p></section>')
        except ValueError as error:
            return _page("Foto no válida", f'<section class="card"><h1>No se pudo subir</h1><p>{escape(str(error))}</p>'
                         f'<p><a href="/foto/{escape(token)}">Intentar de nuevo</a></p></section>')
        return _page("Foto guardada", f'<section class="card"><h1>¡Listo!</h1><p>La foto de {escape(target["name"])} '
                     "quedó guardada. Ya puedes volver al chat.</p></section>")

    @app.get("/calendario/{token}.ics")
    def calendar(token: str) -> Response:
        store = get_store()
        owner = store.calendar_owner(token)
        if owner is None:
            raise HTTPException(404, "Calendario no encontrado.")
        return Response(render.calendar_ics(store.agenda(owner, 365)), media_type="text/calendar; charset=utf-8")

    @app.get("/calendario/{token}", response_class=HTMLResponse)
    def calendar_page(token: str) -> HTMLResponse:
        if get_store().calendar_owner(token) is None:
            raise HTTPException(404, "Calendario no encontrado.")
        links = render.calendar_links(public_url, token)
        return _calendar_html(links)

    return app
