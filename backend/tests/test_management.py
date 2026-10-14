from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.models import Appointment, AuditEvent, BookingAccess, LoginSession, Notification, User
from app.auth import token_hash
from test_booking import setup_schedule, booking_payload, ZONE


def book(client, hour=10):
    service_id, professional_id = setup_schedule(client)
    start = datetime.combine(datetime.now(ZONE).date()+timedelta(days=2), datetime.min.time(), ZONE).replace(hour=hour)
    response = client.post('/api/public/appointments', json=booking_payload(service_id, professional_id, start))
    assert response.status_code == 201, response.text
    return response.json(), service_id, professional_id, start


def create_account(client, role, professional_id=None):
    username = role + str(professional_id or '')
    response = client.post('/api/auth/users', json=dict(username=username, name='Test Account', password='test-password-123', role=role, professional_id=professional_id))
    assert response.status_code == 201, response.text
    login = client.post('/api/auth/login', json=dict(username=username, password='test-password-123'))
    assert login.status_code == 200, login.text
    return {'Authorization': 'Bearer '+login.json()['token']}


def session(client):
    return client.db_factory()


def test_private_routes_require_login(client):
    saved = client.headers.pop('Authorization')
    for path in ('/api/appointments', '/api/blocks', '/api/agenda-hours?day=2026-10-14', '/api/customers', '/api/services', '/api/professionals', '/api/finance/daily', '/api/dashboard', '/api/auth/users', '/api/auth/audit'):
        assert client.get(path).status_code == 401, path
    assert client.get('/api/public/services').status_code == 200
    client.headers['Authorization'] = saved


def test_barber_cannot_read_or_change_other_agenda(client):
    appointment, service_id, first_id, start = book(client)
    other = client.post('/api/professionals', json=dict(name='Other Barber', service_ids=[service_id])).json()['id']
    headers = create_account(client, 'barber', other)
    assert client.get('/api/appointments', params=dict(day=start.date().isoformat()), headers=headers).json() == []
    assert client.get('/api/appointments', params=dict(day=start.date().isoformat(), professional_id=first_id), headers=headers).status_code == 403
    assert client.get('/api/blocks', params=dict(professional_id=first_id), headers=headers).status_code == 403
    assert client.patch(f"/api/appointments/{appointment['id']}/status", json=dict(status='cancelled'), headers=headers).status_code == 403
    assert client.post(f"/api/appointments/{appointment['id']}/reschedule", json=dict(starts_at=start.isoformat(), professional_id=other), headers=headers).status_code == 403
    for path in ('/api/customers', '/api/finance/daily', '/api/dashboard', '/api/auth/users', '/api/schedule-exceptions'):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post('/api/services', json=dict(name='Corte', price='30', duration_minutes=30), headers=headers).status_code == 403


def test_reception_cannot_administer_or_close_cash(client):
    headers = create_account(client, 'reception')
    assert client.get('/api/finance/daily', headers=headers).status_code == 200
    assert client.post('/api/finance/close', json=dict(day=datetime.now(ZONE).date().isoformat(), cash_counted='0'), headers=headers).status_code == 403
    assert client.post('/api/auth/users', json=dict(username='extra', name='Extra', password='test-password-123', role='admin'), headers=headers).status_code == 403


def test_payment_is_independent_and_duplicate_is_rejected(client):
    appointment, _, _, start = book(client)
    path = f"/api/appointments/{appointment['id']}"
    payload = dict(method='cash', discount='5.00', commission_percent='10')
    assert client.post(path+'/payment', json=payload).status_code == 409
    assert client.patch(path+'/status', json=dict(status='in_progress')).status_code == 200
    assert client.patch(path+'/status', json=dict(status='completed')).status_code == 200
    assert client.post(path+'/payment', json=dict(method='pix', discount='100')).status_code == 422
    paid = client.post(path+'/payment', json=payload)
    assert paid.status_code == 201, paid.text
    assert paid.json()['amount'] == '30.00'
    assert paid.json()['commission'] == '3.00'
    assert client.post(path+'/payment', json=payload).status_code == 409
    summary = client.get('/api/finance/daily').json()
    assert summary['received'] == '30.00'
    assert summary['cash_expected'] == '30.00'


def test_cash_close_prevents_payments_and_expenses(client):
    appointment, _, _, _ = book(client)
    path = f"/api/appointments/{appointment['id']}"
    client.patch(path+'/status', json=dict(status='in_progress'))
    client.patch(path+'/status', json=dict(status='completed'))
    today = datetime.now(ZONE).date().isoformat()
    result = client.post('/api/finance/close', json=dict(day=today, cash_counted='0'))
    assert result.status_code == 201, result.text
    assert client.post(path+'/payment', json=dict(method='pix')).status_code == 409
    assert client.post('/api/finance/expenses', json=dict(description='Coffee', amount='5', method='cash')).status_code == 409
    assert client.post('/api/finance/close', json=dict(day=today, cash_counted='0')).status_code == 409


def test_simultaneous_payments_accept_only_one(client):
    appointment, _, _, _ = book(client)
    path = f"/api/appointments/{appointment['id']}"
    client.patch(path+'/status', json=dict(status='in_progress'))
    client.patch(path+'/status', json=dict(status='completed'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(path+'/payment', json=dict(method='pix')).status_code, range(2)))
    assert sorted(results) == [201, 409]


def test_customer_link_is_scoped_and_hash_is_stored(client):
    appointment, _, _, _ = book(client)
    headers = {'Authorization': 'Bearer '+appointment['manage_token']}
    assert client.get('/api/public/reservation', headers=headers).json()['id'] == appointment['id']
    assert client.get('/api/appointments', headers=headers).status_code == 401
    assert client.get('/api/public/reservation', headers={'Authorization':'Bearer wrong'}).status_code == 404
    db = session(client)
    with db:
        assert db.get(BookingAccess, token_hash(appointment['manage_token'])) is not None
    result = client.post('/api/public/reservation/cancel', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'cancelled'
    assert client.post('/api/public/reservation/cancel', headers=headers).status_code == 409


def test_customer_reschedule_keeps_price_and_checks_conflict(client):
    appointment, service_id, professional_id, start = book(client)
    headers = {'Authorization': 'Bearer '+appointment['manage_token']}
    client.post('/api/public/appointments', json=booking_payload(service_id, professional_id, start+timedelta(minutes=30)))
    result = client.post('/api/public/reservation/reschedule', headers=headers, json=dict(starts_at=(start+timedelta(minutes=30)).isoformat(), professional_id=professional_id))
    assert result.status_code == 409
    result = client.post('/api/public/reservation/reschedule', headers=headers, json=dict(starts_at=(start+timedelta(hours=1)).isoformat(), professional_id=professional_id))
    assert result.status_code == 200, result.text
    assert result.json()['price'] == appointment['price']


def test_customer_change_deadline(client):
    appointment, _, _, _ = book(client)
    db = session(client)
    with db:
        row = db.get(Appointment, appointment['id'])
        row.starts_at = datetime.now(timezone.utc)+timedelta(minutes=30)
        row.ends_at = row.starts_at+timedelta(minutes=30)
        db.commit()
    assert client.post('/api/public/reservation/cancel', headers={'Authorization':'Bearer '+appointment['manage_token']}).status_code == 409


def test_exception_replaces_schedule_and_protects_bookings(client):
    appointment, service_id, professional_id, start = book(client)
    payload = dict(professional_id=professional_id, day=start.date().isoformat(), reason='Holiday', periods=[])
    assert client.put('/api/schedule-exceptions', json=payload).status_code == 409
    client.patch(f"/api/appointments/{appointment['id']}/status", json=dict(status='cancelled'))
    assert client.put('/api/schedule-exceptions', json=payload).status_code == 200
    assert client.get('/api/public/availability', params=dict(service_id=service_id, day=start.date().isoformat())).json() == []
    payload['periods'] = [dict(starts_at='14:00', ends_at='16:00')]
    assert client.put('/api/schedule-exceptions', json=payload).status_code == 200
    afternoon = start.replace(hour=14)
    assert client.post('/api/public/appointments', json=booking_payload(service_id, professional_id, afternoon)).status_code == 201
    exception_id = client.get('/api/schedule-exceptions').json()[0]['id']
    assert client.delete(f'/api/schedule-exceptions/{exception_id}').status_code == 409


def test_phone_change_preserves_customer_identity(client):
    appointment, _, _, _ = book(client)
    customer_id = appointment['customer_id']
    assert client.patch(f'/api/customers/{customer_id}', json=dict(phone='85988887777')).status_code == 200
    history = client.get(f'/api/customers/{customer_id}/appointments').json()
    assert history[0]['customer_id'] == customer_id


def test_reset_password_revokes_sessions(client):
    headers = create_account(client, 'reception')
    user_id = client.get('/api/auth/me', headers=headers).json()['id']
    assert client.patch(f'/api/auth/users/{user_id}', json=dict(password='new-password-123')).status_code == 200
    assert client.get('/api/auth/me', headers=headers).status_code == 401


def test_logout_revokes_token(client):
    assert client.post('/api/auth/logout').status_code == 204
    assert client.get('/api/auth/me').status_code == 401


def test_bootstrap_is_secret_and_concurrent_calls_create_one_admin(client, monkeypatch):
    monkeypatch.setenv('BARBERFLOW_BOOTSTRAP_KEY', 'test-bootstrap-key-123')
    with session(client) as db:
        db.execute(delete(LoginSession))
        db.execute(delete(AuditEvent))
        db.execute(delete(User))
        db.commit()
    client.headers.pop('Authorization')
    payload = dict(username='owner', name='Owner', password='test-password-123', role='admin')
    assert client.post('/api/auth/bootstrap', json=payload).status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.post('/api/auth/bootstrap', json=payload, headers={'Bootstrap-Key': 'test-bootstrap-key-123'}).status_code, range(2)))
    assert sorted(statuses) == [201, 409]
    assert client.post('/api/auth/login', json=dict(username='owner', password='test-password-123')).status_code == 200


def test_login_rate_limit_is_enforced(client):
    for _ in range(19):
        assert client.post('/api/auth/login', json=dict(username='admin', password='invalid-password')).status_code == 401
    response = client.post('/api/auth/login', json=dict(username='admin', password='test-password-123'))
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '900'


def test_notifications_delivery_and_failure_are_persisted(client):
    from app.worker import deliver_once
    appointment, _, _, _ = book(client)
    db = session(client)
    engine = db.bind
    db.close()
    factory = lambda: Session(engine, expire_on_commit=False)
    sent = []
    assert deliver_once(factory, sent.append)
    assert len(sent) == 1
    with factory() as db:
        assert db.scalar(select(Notification).where(Notification.kind == 'confirmation')).state == 'sent'
        reminder = db.scalar(select(Notification).where(Notification.kind == 'reminder'))
        reminder.due_at = datetime.now(timezone.utc)-timedelta(minutes=1)
        db.commit()
    def failure(payload):
        raise RuntimeError('provider secret must never be stored')
    assert deliver_once(factory, failure)
    with factory() as db:
        reminder = db.scalar(select(Notification).where(Notification.kind == 'reminder'))
        assert reminder.attempts == 1 and reminder.state == 'pending'
        assert 'secret' not in reminder.last_error
