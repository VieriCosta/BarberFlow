from datetime import datetime, timedelta
from sqlalchemy import select
from app.models import Barbershop, Service, User
from test_booking import setup_schedule, booking_payload, ZONE


def registration(client, name='Nova Barbearia', username='admin'):
    response = client.post('/api/public/barbershops', json=dict(name=name, description='Cortes e barba', city='Fortaleza',
        address='Rua de Teste, 100', phone='85999990000', owner_name='Novo Dono', username=username, password='shop-password-123'))
    assert response.status_code == 201, response.text
    result = response.json()
    return result['shop']['id'], {'Authorization': 'Bearer '+result['token']}, result


def path(shop_id, suffix):
    return f'/api/shops/{shop_id}/{suffix}'


def test_registration_creates_empty_draft_with_own_admin(client):
    shop_id, headers, result = registration(client)
    assert shop_id != 1 and result['user']['shop_id'] == shop_id
    assert result['shop']['published'] is False
    assert result['user']['role'] == 'admin'
    assert client.get(path(shop_id, 'services'), headers=headers).json() == []
    assert client.get(path(shop_id, 'customers'), headers=headers).json() == []
    assert client.get(path(shop_id, 'auth/users'), headers=headers).json()[0]['username'] == 'admin'
    assert shop_id not in [s['id'] for s in client.get('/api/public/barbershops').json()['items']]
    assert client.get('/api/public/barbershops/by-slug/'+result['shop']['slug']).json()['id'] == shop_id


def test_sessions_and_all_private_records_are_scoped_to_shop(client):
    service_id, professional_id = setup_schedule(client)
    start = datetime.combine(datetime.now(ZONE).date()+timedelta(days=2), datetime.min.time(), ZONE).replace(hour=10)
    appointment = client.post('/api/public/appointments', json=booking_payload(service_id, professional_id, start)).json()
    shop_id, headers, result = registration(client)
    assert client.get(path(shop_id, 'auth/me')).status_code == 401
    assert client.get(path(1, 'auth/me'), headers=headers).status_code == 401
    assert client.get(path(shop_id, 'services'), headers=headers).json() == []
    assert client.patch(path(shop_id, f'services/{service_id}'), json={'price':'90'}, headers=headers).status_code == 404
    assert client.post(path(shop_id, 'professionals'), json={'name':'Other', 'service_ids':[service_id]}, headers=headers).status_code == 422
    assert client.post(path(shop_id, 'auth/users'), json={'name':'Barber', 'username':'barber', 'password':'shop-password-123', 'role':'barber', 'professional_id':professional_id}, headers=headers).status_code == 422
    assert client.get(path(shop_id, f'customers/{1}/appointments'), headers=headers).status_code == 404
    assert client.patch(path(shop_id, f"appointments/{appointment['id']}/status"), json={'status':'cancelled'}, headers=headers).status_code == 404
    assert client.post(path(shop_id, f"appointments/{appointment['id']}/payment"), json={'method':'pix'}, headers=headers).status_code == 404
    assert client.get(path(shop_id, 'notifications'), headers=headers).json()['items'] == []
    assert client.get(path(shop_id, 'appointments'), params={'day':start.date().isoformat()}, headers=headers).json() == []
    # Alternating shops exercises SQLAlchemy's query cache with different tenant values.
    for _ in range(3):
        assert len(client.get('/api/services').json()) == 1
        assert client.get(path(shop_id, 'services'), headers=headers).json() == []
    assert client.get(path(shop_id, 'public/availability'), params={'service_id':service_id,'day':'2026-10-20'}).status_code == 404


def test_same_customer_phone_and_cash_day_work_independently(client):
    customer = {'name':'Cliente', 'phone':'85988887777'}
    assert client.post('/api/customers', json=customer).status_code == 201
    shop_id, headers, _ = registration(client)
    response = client.post(path(shop_id, 'customers'), json=customer, headers=headers)
    assert response.status_code == 201, response.text
    assert len(client.get('/api/customers').json()) == 1
    assert len(client.get(path(shop_id, 'customers'), headers=headers).json()) == 1
    day = datetime.now(ZONE).date().isoformat()
    assert client.post('/api/finance/close', json={'day':day,'cash_counted':'0'}).status_code == 201
    assert client.get(path(shop_id, 'finance/daily'), headers=headers).json()['close'] is None
    assert client.post(path(shop_id, 'finance/expenses'), json={'description':'Despesa própria','amount':'5','method':'pix'}, headers=headers).status_code == 201
    assert client.get('/api/finance/daily').json()['expenses_total'] == '0.00'
    assert client.get(path(shop_id, 'finance/daily'), headers=headers).json()['expenses_total'] == '5.00'
    assert client.post(path(shop_id, 'finance/close'), json={'day':day,'cash_counted':'0'}, headers=headers).status_code == 201


def test_publish_requires_schedule_and_directory_search_finds_shop(client):
    shop_id, headers, result = registration(client, 'Barbearia do Bairro')
    profile = {k:result['shop'][k] for k in ('name','description','city','address','phone','published')}
    profile['published'] = True
    assert client.put(path(shop_id, 'profile'), json=profile, headers=headers).status_code == 409
    service = client.post(path(shop_id, 'services'), json={'name':'Corte','price':'40','duration_minutes':30}, headers=headers).json()
    professional = client.post(path(shop_id, 'professionals'), json={'name':'Barbeiro','service_ids':[service['id']]}, headers=headers).json()
    assert client.put(path(shop_id, f"professionals/{professional['id']}/work-periods"), json=[{'weekday':d,'starts_at':'09:00','ends_at':'18:00'} for d in range(7)], headers=headers).status_code == 200
    start = datetime.combine(datetime.now(ZONE).date()+timedelta(days=2), datetime.min.time(), ZONE).replace(hour=10)
    payload = booking_payload(service['id'], professional['id'], start)
    assert client.post(path(shop_id, 'public/appointments'), json=payload).status_code == 409
    assert client.put(path(shop_id, 'profile'), json=profile, headers=headers).status_code == 200
    items = client.get('/api/public/barbershops', params={'q':'Bairro'}).json()['items']
    assert len(items) == 1 and items[0]['id'] == shop_id
    booked = client.post(path(shop_id, 'public/appointments'), json=payload)
    assert booked.status_code == 201, booked.text
    token = {'Authorization':'Bearer '+booked.json()['manage_token']}
    assert client.get(path(shop_id, 'public/reservation'), headers=token).json()['shop_id'] == shop_id
    assert client.get(path(1, 'public/reservation'), headers=token).status_code == 404
    assert len(client.get(path(shop_id, 'customers'), headers=headers).json()) == 1
    assert client.get('/api/customers').json() == []
