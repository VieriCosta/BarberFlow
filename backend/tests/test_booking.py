from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Fortaleza")


def setup_schedule(client):
    service = client.post("/api/services", json={
        "name": "Corte", "description": "", "price": "35.00", "duration_minutes": 30,
    })
    assert service.status_code == 201, service.text
    service_id = service.json()["id"]
    professional = client.post("/api/professionals", json={"name": "Ana", "service_ids": [service_id]})
    assert professional.status_code == 201, professional.text
    professional_id = professional.json()["id"]
    schedule = client.put(f"/api/professionals/{professional_id}/work-periods", json=[
        {"weekday": day, "starts_at": "09:00", "ends_at": "12:00"} for day in range(7)
    ])
    assert schedule.status_code == 200, schedule.text
    return service_id, professional_id


def booking_payload(service_id, professional_id, start):
    return {"service_id": service_id, "professional_id": professional_id,
            "starts_at": start.isoformat(), "customer_name": "Cliente Teste", "customer_phone": "(85) 99999-1234"}


def test_first_milestone_and_conflict(client):
    assert client.get("/api/services").status_code == 200
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    available = client.get("/api/public/availability", params={"service_id": service_id, "day": day.isoformat()})
    assert available.status_code == 200
    assert any(slot["starts_at"] == start.isoformat() for slot in available.json())

    first = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start))
    assert first.status_code == 201, first.text
    assert first.json()["price"] == "35.00"
    assert first.json()["customer_phone"] == "85999991234"
    overlap = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start + timedelta(minutes=15)))
    assert overlap.status_code == 409
    next_slot = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start + timedelta(minutes=30)))
    assert next_slot.status_code == 201, next_slot.text
    agenda = client.get("/api/appointments", params={"day": day.isoformat()})
    assert len(agenda.json()) == 2


def test_schedule_boundaries_and_past(client):
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=11, minute=45)
    outside = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start))
    assert outside.status_code == 409
    past = client.post("/api/public/appointments", json=booking_payload(
        service_id, professional_id, datetime.now(ZONE) - timedelta(days=1)))
    assert past.status_code == 422


def test_simultaneous_reservations_only_accept_one(client):
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=3)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    payload = booking_payload(service_id, professional_id, start)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/public/appointments", json=payload).status_code, range(2)))
    assert sorted(results) == [201, 409]


def test_customer_registry_and_service_snapshot(client):
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    booked = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start))
    assert booked.status_code == 201, booked.text
    customers = client.get("/api/customers")
    assert customers.status_code == 200
    assert len(customers.json()) == 1
    customer = customers.json()[0]
    assert customer["phone"] == "85999991234"
    assert customer["appointments_count"] == 1

    updated_service = client.patch(f"/api/services/{service_id}",
                                   json={"price": "42.00", "duration_minutes": 45, "name": "Corte premium"})
    assert updated_service.status_code == 200, updated_service.text
    assert client.patch(f"/api/services/{service_id}", json={"active": False}).status_code == 409
    assert client.patch(f"/api/professionals/{professional_id}", json={"active": False}).status_code == 409
    alternative = client.post("/api/services",
                              json={"name": "Barba", "description": "", "price": "25.00", "duration_minutes": 20})
    assert alternative.status_code == 201
    assert client.patch(f"/api/professionals/{professional_id}",
                        json={"service_ids": [alternative.json()["id"]]}).status_code == 409
    agenda = client.get("/api/appointments", params={"day": day.isoformat()}).json()
    assert agenda[0]["price"] == "35.00"
    assert agenda[0]["service_name"] == "Corte"
    assert agenda[0]["ends_at"].startswith(f"{day.isoformat()}T10:30")

    edited_customer = client.patch(f"/api/customers/{customer['id']}",
                                   json={"name": "Cliente Corrigido", "phone": "(85) 98888-1234", "email": "cliente@example.com"})
    assert edited_customer.status_code == 200, edited_customer.text
    assert edited_customer.json()["appointments_count"] == 1
    history = client.get(f"/api/customers/{customer['id']}/appointments").json()
    assert len(history) == 1
    assert history[0]["customer_phone"] == "85988881234"


def test_edit_and_inactivate_without_future_booking(client):
    service_id, professional_id = setup_schedule(client)
    second = client.post("/api/services",
                         json={"name": "Barba", "description": "", "price": "25.00", "duration_minutes": 20})
    assert second.status_code == 201
    second_id = second.json()["id"]
    professional = client.patch(f"/api/professionals/{professional_id}",
                                json={"name": "Ana Silva", "service_ids": [service_id, second_id]})
    assert professional.status_code == 200, professional.text
    assert professional.json()["service_ids"] == [service_id, second_id]
    assert client.patch(f"/api/services/{second_id}", json={"active": False}).status_code == 200
    renamed = client.patch(f"/api/professionals/{professional_id}",
                           json={"name": "Ana Atualizada", "service_ids": [service_id, second_id]})
    assert renamed.status_code == 200, renamed.text
    assert client.patch(f"/api/professionals/{professional_id}", json={"active": False}).status_code == 200
    assert all(item["id"] != second_id for item in client.get("/api/public/services").json())
    assert all(item["id"] != professional_id for item in client.get("/api/public/professionals").json())

    created = client.post("/api/customers",
                          json={"name": "Novo Cliente", "phone": "85 97777-1234", "email": None, "notes": "Prefere manhã"})
    assert created.status_code == 201, created.text
    assert len(client.get("/api/customers", params={"q": "97777"}).json()) == 1
    assert client.post("/api/customers",
                       json={"name": "Duplicado", "phone": "85977771234"}).status_code == 409


def test_blocks_hide_slots_and_can_be_removed(client):
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    payload = {"professional_id": professional_id, "starts_at": start.isoformat(),
               "ends_at": (start + timedelta(minutes=45)).isoformat(), "reason": "Almoço"}
    assert client.get("/api/blocks", params={"day": day.isoformat()}).status_code == 200
    created = client.post("/api/blocks", json=payload)
    assert created.status_code == 201, created.text
    assert client.post("/api/blocks", json=payload).status_code == 409
    slots = client.get("/api/public/availability", params={"service_id": service_id, "day": day.isoformat()}).json()
    assert all(slot["starts_at"] != start.isoformat() for slot in slots)
    assert client.post("/api/appointments",
                       json=booking_payload(service_id, professional_id, start)).status_code == 409
    blocks = client.get("/api/blocks", params={"day": day.isoformat()}).json()
    assert len(blocks) == 1 and blocks[0]["reason"] == "Almoço"
    assert client.delete(f"/api/blocks/{created.json()['id']}").status_code == 204
    assert client.post("/api/appointments",
                       json=booking_payload(service_id, professional_id, start)).status_code == 201
    assert client.post("/api/blocks", json=payload).status_code == 409


def test_reschedule_status_and_week_filter(client):
    service_id, professional_id = setup_schedule(client)
    other = client.post("/api/professionals", json={"name": "Bia", "service_ids": [service_id]})
    assert other.status_code == 201
    other_id = other.json()["id"]
    assert client.put(f"/api/professionals/{other_id}/work-periods", json=[
        {"weekday": day, "starts_at": "09:00", "ends_at": "12:00"} for day in range(7)]).status_code == 200
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    original = client.post("/api/appointments", json=booking_payload(service_id, professional_id, start))
    assert original.status_code == 201, original.text
    appointment_id = original.json()["id"]
    second = client.post("/api/appointments",
                         json=booking_payload(service_id, other_id, start + timedelta(minutes=30)))
    assert second.status_code == 201, second.text
    conflict = client.post(f"/api/appointments/{appointment_id}/reschedule",
                           json={"starts_at": (start + timedelta(minutes=30)).isoformat(), "professional_id": other_id})
    assert conflict.status_code == 409
    moved = client.post(f"/api/appointments/{appointment_id}/reschedule",
                        json={"starts_at": start.isoformat(), "professional_id": other_id})
    assert moved.status_code == 200, moved.text
    assert moved.json()["price"] == original.json()["price"]
    assert moved.json()["ends_at"] == original.json()["ends_at"]
    assert client.post("/api/appointments",
                       json=booking_payload(service_id, professional_id, start)).status_code == 201
    weekly = client.get("/api/appointments", params={
        "day": day.isoformat(), "view": "week", "professional_id": other_id})
    assert weekly.status_code == 200 and len(weekly.json()) == 2
    assert client.patch(f"/api/appointments/{appointment_id}/status",
                        json={"status": "completed"}).status_code == 409
    assert client.patch(f"/api/appointments/{appointment_id}/status",
                        json={"status": "no_show"}).status_code == 409
    assert client.patch(f"/api/appointments/{appointment_id}/status",
                        json={"status": "in_progress"}).status_code == 200
    assert client.patch(f"/api/appointments/{appointment_id}/status",
                        json={"status": "completed"}).status_code == 200
    assert client.patch(f"/api/appointments/{appointment_id}/status",
                        json={"status": "cancelled"}).status_code == 409


def test_cancel_releases_slot(client):
    service_id, professional_id = setup_schedule(client)
    day = datetime.now(ZONE).date() + timedelta(days=2)
    start = datetime.combine(day, datetime.min.time(), ZONE).replace(hour=10)
    booked = client.post("/api/public/appointments", json=booking_payload(service_id, professional_id, start))
    assert booked.status_code == 201
    cancelled = client.patch(f"/api/appointments/{booked.json()['id']}/status",
                             json={"status": "cancelled"})
    assert cancelled.status_code == 200
    assert client.post("/api/public/appointments",
                       json=booking_payload(service_id, professional_id, start)).status_code == 201
