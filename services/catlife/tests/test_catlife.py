from datetime import date

import asyncio

import mongomock
import pytest
from fastapi.testclient import TestClient

from catlife import card, care
from catlife.store import NotFound, Store
from catlife.web import create_app

TODAY = date(2026, 10, 25)


@pytest.fixture
def store():
    return Store(mongomock.MongoClient(tz_aware=True)["catlife"], today=lambda: TODAY)


def test_next_due_follows_frequency_and_clamps_month_end():
    assert care.next_due_date(date(2026, 1, 31), "mensual") == date(2026, 2, 28)
    assert care.next_due_date(date(2026, 3, 10), "Anual") == date(2027, 3, 10)
    assert care.next_due_date(date(2026, 3, 10), "una sola vez") is None
    with pytest.raises(ValueError):
        care.next_due_date(date(2026, 3, 10), "cada luna llena")


def test_dose_names_and_ages_match_the_app():
    assert care.next_dose_name("Triple Felina 1era") == "Triple Felina 2da"
    assert care.next_dose_name("Leucemia segunda") == "Leucemia 3era"
    assert care.next_dose_name("Rabia") == "Rabia - Refuerzo"
    assert care.next_dose_name("Rabia - Refuerzo") == "Rabia - Refuerzo"
    assert [care.human_age(m) for m in (2, 6, 12, 36, 228, 300)] == ["1-4 años", "10 años", "15 años", "28 años",
                                                                     "92 años", "96+ años"]
    assert care.parse_date("05/03/2026") == date(2026, 3, 5)


def test_users_never_see_each_others_cats(store):
    mishi = store.add_cat("ana", name="Mishi", birth_date="2025-10-25", weight_kg=4.2)
    assert mishi["age_months"] == 12 and mishi["human_age"] == "15 años"
    assert store.cats("bruno") == []
    with pytest.raises(NotFound):
        store.add_vaccine("bruno", mishi["id"], "Rabia", "2026-01-01", "anual")
    with pytest.raises(NotFound):
        store.delete_cat("bruno", mishi["id"])
    assert store.weights("ana", mishi["id"])[0]["weight_kg"] == 4.2


def test_vaccine_dose_chain_and_agenda(store):
    cat = store.add_cat("ana", name="Mishi")
    vaccine = store.add_vaccine("ana", cat["id"], "Triple Felina 1era", "2026-07-20", "cada 3 meses")
    assert vaccine["next_due"] == "2026-10-20" and vaccine["next_dose"] == "Triple Felina 2da"

    agenda = store.agenda("ana", 30)
    assert agenda[0]["overdue"] and agenda[0]["title"] == "Vacuna Triple Felina 2da"

    after = store.apply_dose("ana", vaccine["id"], "25/10/2026")
    assert after["doses_applied"] == 2 and after["next_due"] == "2027-01-25"
    assert after["history"][-1]["name"] == "Triple Felina 2da" and after["next_dose"] == "Triple Felina 3era"
    assert store.agenda("ana", 30) == []


def test_records_feed_weight_appointments_and_summary(store):
    cat = store.add_cat("ana", name="Mishi")
    store.add_record("ana", cat["id"], record_type="consulta", date="2026-10-01", reason="Vómito",
                     weight_kg=4.5, next_appointment="2026-11-01",
                     medications=[{"name": "Omeprazol", "end_date": "2026-11-30"}])
    store.add_condition("ana", cat["id"], name="Alergia al pollo", condition_type="alergia", severity="moderado")
    reminder = store.add_reminder("ana", cat["id"], "Desparasitación", "2026-10-30", "trimestral", None)
    follow = store.complete_reminder("ana", reminder["id"])["next"]
    assert follow["due"] == "2027-01-25"

    summary = store.health_summary("ana", cat["id"])
    assert summary["current_weight_kg"] == 4.5 and summary["total_visits"] == 1
    assert summary["active_medications"][0]["name"] == "Omeprazol"
    assert summary["upcoming"][0]["kind"] == "cita"
    assert len(summary["active_conditions"]) == 1


def test_reminders_by_kind_and_care_plan(store):
    kitten = store.add_cat("ana", name="Michi", age_months=3)
    plan = store.care_plan("ana", kitten["id"])
    assert {s["kind"]: s["repeat"] for s in plan["suggestions"]}["purgante"] == "mensual"

    purgante = store.add_reminder("ana", kitten["id"], "Purgante", "2026-10-20", "mensual", None, "purgante",
                                  "Drontal")
    with pytest.raises(ValueError):
        store.add_reminder("ana", kitten["id"], "x", "2026-10-20", None, None, "magia")
    assert next(s for s in store.care_plan("ana", kitten["id"])["suggestions"]
                if s["kind"] == "purgante")["already_scheduled"]
    assert store.agenda("ana", 30)[0]["detail"] == "Drontal"

    done = store.complete_reminder("ana", purgante["id"], "2026-10-24")
    assert done["next"]["due"] == "2026-11-24" and done["next"]["kind"] == "purgante"
    assert [r["id"] for r in store.reminders("ana")] == [done["next"]["id"]]
    assert len(store.reminders("ana", include_completed=True)) == 2

    store.update_reminder("ana", done["next"]["id"], None, "2026-11-30", None, "Milbemax", None)
    assert store.reminders("ana")[0]["product"] == "Milbemax"
    store.delete_reminder("ana", done["next"]["id"])
    with pytest.raises(NotFound):
        store.delete_reminder("bruno", purgante["id"])

    from_last = store.add_reminder("ana", kitten["id"], "Antipulgas", None, "mensual", None, "antipulgas",
                                   last_done="2026-09-30")
    assert from_last["due"] == "2026-10-30"
    assert store.add_reminder("ana", kitten["id"], "Baño", None, None, None, "estetica")["due"] == "2026-10-25"

    adult = store.add_cat("ana", name="Luna", age_months=24)
    assert {s["kind"]: s["repeat"] for s in store.care_plan("ana", adult["id"])["suggestions"]}["purgante"] == \
        "trimestral"


def test_delete_cat_cascades(store):
    cat = store.add_cat("ana", name="Mishi", weight_kg=4)
    store.add_vaccine("ana", cat["id"], "Rabia", "2026-01-01", "anual")
    removed = store.delete_cat("ana", cat["id"])["removed"]
    assert removed["vaccines"] == 1 and removed["weights"] == 1
    assert store.vaccines("ana") == []


def test_public_card_photo_and_calendar(store):
    cat = store.add_cat("ana", name='Mishi "</script>', gender="Hembra", sterilized=True)
    store.add_vaccine("ana", cat["id"], "Rabia", "2026-01-01", "anual")
    app = TestClient(create_app(lambda: store, "https://cat.test"))

    token = store.share_token("ana", cat["id"])
    page = app.get(f"/carne/{token}")
    assert page.status_code == 200 and "Rabia" in page.text and "wa.me" in page.text
    assert '"</script>' not in page.text
    assert app.get(f"/carne/{token}/qr.png").headers["content-type"] == "image/png"
    assert app.get(f"/carne/{token}/imagen.png").content[:4] == b"\x89PNG"
    assert app.get(f"/carne/{token}/foto").status_code == 404

    upload = store.photo_upload_token("ana", cat["id"])
    photo = app.get(f"/carne/{token}/qr.png").content
    assert app.post(f"/foto/{upload}", files={"photo": ("m.png", photo, "image/png")}).status_code == 200
    assert app.get(f"/carne/{token}/foto").content == photo
    assert "Enlace vencido" in app.post(f"/foto/{upload}", files={"photo": ("m.png", photo, "image/png")}).text
    assert app.get(f"/carne/{token}/imagen.png").status_code == 200

    store.stop_sharing("ana", cat["id"])
    assert app.get(f"/carne/{token}").status_code == 404

    feed = app.get(f"/calendario/{store.calendar_token('ana')}.ics").text
    assert "SUMMARY:Mishi" in feed and "DTSTART;VALUE=DATE:20270101" in feed
    assert app.get("/calendario/otro.ics").status_code == 404
    page = app.get(f"/calendario/{store.calendar_token('ana')}").text
    assert 'href="webcal://cat.test/calendario/' in page and "calendar.google.com" in page
    assert card.calendar_links("http://localhost:8200", "t")["google_calendar"] is None


def test_calendar_lines_fold_at_75_octets():
    feed = card.calendar_ics([{"kind": "cita", "id": "x", "cat": "Mishi", "date": "2026-11-01", "time": "09:30",
                               "title": "Cita: " + "revisión ñ " * 20, "detail": "Clínica " * 30}])
    assert all(len(line.encode()) <= 75 for line in feed.split("\r\n"))
    assert "DTSTART:20261101T093000" in feed


def test_share_links_cover_networks():
    links = card.share_links("https://cat.test/carne/x", "Carné de Mishi")
    assert set(links) == {"whatsapp", "facebook", "x", "telegram", "email"}


def test_mcp_server_registers_every_tool():
    from mcp_server.server import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {"register_cat", "apply_vaccine_dose", "add_medical_record", "share_card", "show_card",
            "cat_photo_upload_link", "calendar_subscription", "find_veterinaries", "mood_guide", "care_plan",
            "list_reminders", "update_reminder", "delete_reminder", "share_cats_with",
            "accept_family_invitation", "family_activity", "family_status"} <= names


def test_family_shares_cats_between_mia_users(store):
    from catlife.family import Family

    family = Family(store.db)
    mishi = store.add_cat("ana", name="Mishi")
    store.add_cat("bruno", name="Tom")

    invite = family.invite_email("ana", "Ana", "ana@mia.co", "Bruno@MIA.co")
    household = family.space("ana")
    assert household != "ana" and [c["name"] for c in store.cats(household)] == ["Mishi"]
    assert family.pending("bruno@mia.co")[0]["cats"] == ["Mishi"]
    with pytest.raises(ValueError):
        family.invite_email("ana", "Ana", "ana@mia.co", "ana@mia.co")
    with pytest.raises(PermissionError):
        family.join("carla", "Carla", invite["code"], True, "carla@mia.co")

    joined = family.join("bruno", "Bruno", invite["code"], True, "bruno@mia.co")
    assert joined["moved"]["cats"] == 1 and family.pending("bruno@mia.co") == []
    assert family.space("bruno") == household
    assert sorted(c["name"] for c in store.cats(household)) == ["Mishi", "Tom"]
    assert [m["name"] for m in family.status("ana")["members"]] == ["Ana", "Bruno"]

    family.log(household, "bruno", "Bruno", "aplicó la vacuna", mishi["id"], "Rabia")
    entry = family.activity(household, "ana")[0]
    assert entry["who"] == "Bruno" and entry["cat"] == "Mishi" and not entry["is_you"]

    code = family.invite("ana", "Ana")["code"]
    family.join("carla", "Carla", code, False, "carla@mia.co")
    store.add_cat("carla", name="Privado")
    assert "Privado" not in [c["name"] for c in store.cats(household)]
    with pytest.raises(PermissionError):
        family.remove("bruno", "carla")
    family.remove("ana", "carla")
    assert family.space("carla") == "carla" and store.cats("carla")[0]["name"] == "Privado"

    assert family.leave("ana")["cats_stay_with_family"]
    assert family.status("bruno")["your_role"] == "admin"
    assert sorted(family.leave("bruno")["took_cats"]) and family.space("bruno") == "bruno"
    assert len(store.cats("bruno")) == 2 and store.cats("ana") == []


def test_invitation_email_names_cats_and_code():
    from catlife import notify

    message = notify.invitation("bruno@mia.co", "Ana", ["Mishi"], "ABCD2345", "https://mia.test")
    assert message["Subject"] == "Ana te invitó a cuidar a Mishi en MIA"
    assert "ABCD2345" in message.get_body(("plain",)).get_content()
