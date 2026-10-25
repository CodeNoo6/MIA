# Agente de Cuidador Felino y Agente de Cuidador Canino · Cuidado animal

Los agentes de MIA que hacen todo lo que hace la app Android Cat Life, para gatos (**Agente de Cuidador Felino**) y para
perros (**Agente de Cuidador Canino**), con los datos de cada usuario de MIA (o de su hogar familiar, compartido entre varios usuarios de
MIA) guardados en MongoDB. Un servidor MCP privado expone las herramientas a los dos agentes y un portal público
sirve lo que se comparte fuera del chat: carné, QR, imagen para redes, subida de fotos y calendario.

```
Felino ─(cat-life, X-MIA-Species: gato)───┐
                                           ├─► catlife-mcp (:8001/mcp/, privado) ─┐
Canino ─(dog-life, X-MIA-Species: perro)──┘                                     ├─► MongoDB (base catlife)
Navegador / QR / redes ───────────────────────► catlife-portal (:8000, público) ──┘
```

Cada agente solo ve y toca mascotas de su especie (el servidor lo valida en cada herramienta). El hogar
familiar, el calendario y el registro de actividad son comunes: una familia con gato y perro ve todo junto en
su calendario.

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
| Edad por dientes y edad humana (perros según tamaño) | `teeth_age_guide`, `human_age` |
| Estados de ánimo y lenguaje corporal de cada especie | `mood_guide` |
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

## Crear los agentes en MIA

Los dos agentes van en la categoría **Cuidado animal**, que MIA crea sola al arrancar, y aparecen agrupados en el
**Marketplace de agentes**. Cada uno tiene su guía con la configuración, las instrucciones para pegar y qué probar:

| Agente | Especie | Servidor MCP | Guía |
|---|---|---|---|
| Agente de Cuidador Felino | Gatos | `cat-life` | [agents/cat-life/README.md](agents/cat-life/README.md) |
| Agente de Cuidador Canino | Perros | `dog-life` | [agents/dog-life/README.md](agents/dog-life/README.md) |

## Desplegar en Railway

Railway construye desde el repositorio de GitHub, así que primero sube los cambios a la rama que usa tu proyecto.

1. **MongoDB:** agrega un servicio **MongoDB** desde el catálogo de Railway (nómbralo `MongoDB`). Si LibreChat ya usa
   un Mongo en Railway, puedes reutilizarlo: los agentes usan su propia base `catlife`.
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
