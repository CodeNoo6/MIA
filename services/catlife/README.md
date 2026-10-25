# Cat Life

El agente de MIA que hace todo lo que hace la app Android Cat Life, con los datos de cada usuario de MIA
(o de su hogar familiar, compartido entre varios usuarios de MIA) guardados en MongoDB. Un servidor MCP privado expone las herramientas al agente y un portal público sirve
lo que se comparte fuera del chat: carné, QR, imagen para redes, subida de fotos y calendario.

```
LibreChat agente ─(X-MIA-User-*)──► catlife-mcp (:8001/mcp/, privado) ─┐
                                                                      ├─► MongoDB  (base catlife)
Navegador / QR / redes ───────────► catlife-portal (:8000, público) ──┘
```

## Qué cubre

| App Cat Life | Herramientas del agente |
|---|---|
| Registrar, editar y borrar gatos | `register_cat`, `update_cat`, `delete_cat`, `list_cats` |
| Foto del gato | `cat_photo_upload_link` (enlace de 30 min para subirla desde el celular) |
| Vacunas, dosis y renovación (1era → 2da → 3era → Refuerzo) | `add_vaccine`, `apply_vaccine_dose`, `list_vaccines`, `delete_vaccine` |
| Recordatorios (vacunas, purgante, antipulgas, medicamentos, chequeos…) y notificaciones | `care_plan`, `get_agenda`, `add_reminder`, `list_reminders`, `update_reminder`, `complete_reminder`, `delete_reminder`, `calendar_subscription` (.ics con alarmas) |
| Historial clínico, peso, condiciones, citas y veterinarios | `add_medical_record`, `list_medical_history`, `health_summary`, `log_weight`, `weight_history`, `add_condition`, `add_appointment`, `save_veterinarian`… |
| Carné digital con QR | `show_card`, `share_card`, `stop_sharing_card` |
| Compartir en redes | `share_card` da enlaces de WhatsApp, Facebook, X, Telegram y correo, y la imagen 1080×1350 para Instagram o TikTok |
| Edad por dientes y edad humana | `teeth_age_guide`, `human_age` |
| Estados de ánimo | `mood_guide` |
| Veterinarias cercanas (10 km) | `find_veterinaries` (requiere `GOOGLE_PLACES_API_KEY`) |
| *Nuevo:* compartir gatos con la familia (usuarios de MIA) | `share_cats_with` (por correo, con aviso), `family_status`, `accept_family_invitation`, `decline_family_invitation`, `invite_to_family` (código), `family_activity`, `leave_family`, `remove_family_member` |

### Hogar familiar

Cada usuario de MIA trabaja en su propio espacio hasta que comparte: `share_cats_with(correo)` convierte su espacio en
un hogar (`catlife/family.py`) e invita a esa cuenta de MIA. Si `MIA_USERS_DB` está configurado, el correo se valida
contra los usuarios de LibreChat (solo lectura) y se rechaza si no existe. La persona invitada recibe un correo (si
las variables `EMAIL_*` están configuradas, las mismas de LibreChat) y, al abrir el agente, ve la invitación y decide
si acepta y si comparte también sus propios gatos. Cada cambio queda en `family_activity` con quién lo hizo, y todos
los miembros pueden suscribir el calendario del hogar. Si alguien sale, los gatos se quedan con la familia; el último
en salir se los lleva.

Las fechas próximas, las edades y los nombres de dosis se calculan en `catlife/care.py` con las mismas tablas
y reglas de la app; el modelo solo los cita.

## Correr en local

`docker compose up -d` levanta `catlife-portal` (http://localhost:8200) y `catlife-mcp` usando el Mongo de
LibreChat con la base `catlife`. Tests: `docker run --rm --entrypoint python mia-catlife:latest -m pytest -q tests`

## Crear el agente en MIA

1. **Agentes → Crear agente**. Nombre: `Cat Life`. Descripción: `Cuida a tus gatos: vacunas, historial, recordatorios y carné para compartir.`
2. Modelo: Claude.
3. En **Herramientas → Servidores MCP** agrega `Cat Life` con todas sus herramientas y activa **Artefactos**.
4. Instrucciones:

```
Eres Cat Life, el asistente de MIA para el cuidado de gatos. Haces todo lo que hace la app Cat Life usando las herramientas del servidor Cat Life.

Al empezar:
- Llama a family_status. Si tiene invitaciones pendientes, muéstralas primero (quién invita y qué gatos) y pregúntale si acepta y si quiere compartir también sus propios gatos.
- Si está en un hogar, llama a family_activity y cuenta en una o dos líneas lo que hicieron los otros miembros desde la última vez (is_you=false).
- Llama a list_cats y a get_agenda. Si hay vacunas, citas o recordatorios vencidos o en los próximos 7 días, avísalo primero.
- Si el usuario no tiene gatos, ofrécele registrar el primero y pregúntale nombre, género, fecha de nacimiento (o edad), peso, si está esterilizado y si tiene microchip.

Reglas:
- Nunca calcules fechas de vacunas, edades ni nombres de dosis: usa lo que devuelven las herramientas.
- Si el usuario tiene varios gatos y no queda claro de cuál habla, pregúntalo. Usa siempre el id que devolvió list_cats.
- Antes de borrar un gato, una vacuna o un registro, confirma con el usuario. delete_cat borra todo su historial.
- Cuando el usuario cuente que vacunaron a su gato, usa apply_vaccine_dose sobre la vacuna existente; usa add_vaccine solo si es una vacuna nueva.
- Para la foto del gato da el enlace de cat_photo_upload_link y explica que vence en 30 minutos. Las fotos que se adjuntan en el chat no se guardan en el carné.
- Para ver el carné usa show_card. Para compartirlo usa share_card y muestra el QR y los enlaces de cada red como enlaces Markdown. Para Instagram o TikTok explica que descargue la imagen y la suba.
Recordatorios:
- Las próximas dosis de vacunas registradas ya salen en get_agenda; no les crees recordatorio aparte.
- Al registrar un gato, o si el usuario pregunta qué le toca, llama a care_plan y propón los recordatorios que no estén programados (purgante, antipulgas, chequeo, dental) con su frecuencia. Crea con add_reminder solo los que acepte, preguntando cuándo fue la última aplicación (pásala en last_done; el servidor calcula la próxima) y el producto que usa.
- Aclara que el plan es orientativo y que su veterinario puede indicar otra frecuencia o producto.
- Cuando cuente que ya le dio el purgante o la pipeta, usa complete_reminder con la fecha real; el siguiente se programa solo.
- Después de crear recordatorios ofrece calendar_subscription para recibir avisos en el celular un día antes y el mismo día.
Familia:
- Si el usuario quiere compartir sus gatos con alguien, pídele el correo con el que esa persona entra a MIA, confírmalo y llama a share_cats_with. Dile si se envió el correo y que la otra persona verá la invitación al abrir Cat Life en MIA.
- Solo se comparte con usuarios de MIA. Si la herramienta dice que el correo no existe, explícale que esa persona debe registrarse primero en MIA.
- Antes de leave_family o remove_family_member confirma con el usuario.

Otros:
- Para estimar la edad, recorre teeth_age_guide preguntando cómo se ven sus dientes. Para el comportamiento, compara lo que describe con mood_guide.
- Si piden una gráfica de peso, llama a weight_history y crea un artefacto React con recharts que use solo esos puntos.
- No diagnostiques ni recetes. Ante síntomas graves (no come en más de 24 h, dificultad para respirar, sangrado, convulsiones, no orina) recomienda ir de urgencia y ofrece find_veterinaries con emergency=true.
- Responde en español, cálido y breve.
```

## Desplegar en Railway

Railway construye desde el repositorio de GitHub, así que primero sube los cambios a la rama que usa tu proyecto.

1. **MongoDB:** agrega un servicio **MongoDB** desde el catálogo de Railway (nómbralo `MongoDB`). Si LibreChat ya usa
   un Mongo en Railway, puedes reutilizarlo: Cat Life usa su propia base `catlife`.
2. **Dos servicios desde el mismo repo** con **Root Directory** `services/catlife` (Railway detecta el Dockerfile):

| Servicio | Start command | Variables | Red |
|---|---|---|---|
| `catlife-portal` | (por defecto) | `PORT=8000`, `MONGO_URL=${{MongoDB.MONGO_URL}}`, `CATLIFE_PUBLIC_URL=https://<dominio del portal>` | **Generate Domain** en el puerto 8000 |
| `catlife-mcp` | `python -m mcp_server.server` | `PORT=8001`, `MONGO_URL=${{MongoDB.MONGO_URL}}`, `CATLIFE_PUBLIC_URL=https://<dominio del portal>`, `CATLIFE_MCP_TOKEN=<secreto largo>`, `MIA_URL=https://<dominio de MIA>`, `MIA_USERS_MONGO_URL=<MONGO_URI de LibreChat>`, `MIA_USERS_DB=<base de LibreChat>`, `EMAIL_*` (opcional), `GOOGLE_PLACES_API_KEY` (opcional) | Solo privada, sin dominio |

   Los nombres deben ser exactamente `catlife-portal` y `catlife-mcp` para que `catlife-mcp.railway.internal` resuelva.
   `MIA_USERS_DB` es el nombre de la base al final del `MONGO_URI` de LibreChat; si LibreChat usa el mismo Mongo,
   omite `MIA_USERS_MONGO_URL`.
3. **LibreChat:** en su servicio define `CATLIFE_MCP_TOKEN` con el mismo secreto y `CONFIG_PATH=/app/deploy/config.railway.yaml`.
   Ese archivo ya apunta a `catlife-mcp.railway.internal:8001` y envía `X-MIA-User-Id`, `X-MIA-User-Name`,
   `X-MIA-User-Email` y `X-CatLife-Token`.
4. Redespliega LibreChat, entra a MIA y crea el agente con las instrucciones de arriba.
5. Prueba: `https://<dominio del portal>/health` responde `{"ok":true}`.

`catlife-mcp` confía en los headers de identidad, así que nunca debe tener dominio público. Con el portal en https,
Google Calendar acepta la suscripción y el QR del carné funciona desde cualquier celular.

## Pendiente

- Notificaciones push: se reemplazan con el calendario suscribible. Correos de recordatorio de vacunas quedan para después.
- Los datos de la app Android en Firebase no se migran; cada usuario de MIA empieza vacío.
