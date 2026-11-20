import time
from datetime import date

import pytest

from app import create_app, db
from app.billing import ensure_invoices, first_month_amount
from app.models import Contract, Payment, SmsLog


class TestConfig:
    TESTING = True
    SECRET_KEY = "t"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    PUBLIC_BASE_URL = ""
    MOMO_MODE = "mock"
    SMS_MODE = "mock"
    MOMO_POLL_SECONDS = 1
    SMS_TEMPLATE = "Murakoze {name}. Twakiriye {paid} RWF. Asigaye: {balance} RWF. {code} {ref}"


@pytest.fixture
def client():
    app = create_app(TestConfig, start_poller=False)
    with app.test_client() as c, app.app_context():
        c.post("/login", data={"username": "admin", "password": "admin123"})
        yield c


def test_prorating():
    assert first_month_amount(3000, date(2026, 11, 1)) == 3000
    assert first_month_amount(3000, date(2026, 11, 16)) == 1500


def register(c, phone="0788123456", start=None):
    r = c.post(
        "/clients/new",
        data={
            "client_type": "household", "first_name": "Uwase", "second_name": "Alice", "phone": phone,
            "district": "Gasabo", "sector": "Gisozi", "cell": "Musezero", "village": "Ruhango",
            "collection_days": ["mon", "thu"], "monthly_fee": "3000", "due_day": "10",
            "start_date": (start or date.today().replace(day=1)).isoformat(), "payment_method": "momo",
        },
    )
    assert r.status_code == 302
    return Contract.query.order_by(Contract.id.desc()).first()


def test_register_creates_contract_and_invoice(client):
    k = register(client)
    assert k.client.code.endswith(f"/AGRUNI/{date.today().year}")
    assert k.balance == 3000
    assert client.get(f"/clients/{k.client_id}/contract").status_code == 200


def test_momo_payment_success_sends_sms(client, monkeypatch):
    k = register(client)
    client.post(f"/clients/{k.client_id}/pay", data={"method": "momo", "amount": "2000", "phone": "0788123456"})
    p = Payment.query.one()
    assert p.status == "PENDING" and p.phone == "250788123456"
    import app.momo as momo
    momo._mock_requests[p.reference_id]["created"] -= 10
    d = client.get(f"/payments/{p.id}/status").get_json()
    assert d["status"] == "SUCCESSFUL" and d["balance"] == 1000 and d["sms_sent"]
    sms = SmsLog.query.one()
    assert "2,000 RWF" in sms.message and "1,000 RWF" in sms.message and sms.phone == "+250788123456"
    client.get(f"/payments/{p.id}/status")
    assert SmsLog.query.count() == 1


def test_momo_payment_rejected(client):
    k = register(client, phone="0788000000")
    client.post(f"/clients/{k.client_id}/pay", data={"method": "momo", "amount": "3000", "phone": "0788000000"})
    p = Payment.query.one()
    import app.momo as momo
    momo._mock_requests[p.reference_id]["created"] -= 10
    assert client.get(f"/payments/{p.id}/status").get_json()["status"] == "FAILED"
    assert SmsLog.query.count() == 0
    assert k.balance == 3000


def test_collector_sees_only_own_clients(client):
    k = register(client)
    client.post("/users", data={"name": "Jean", "username": "jean", "password": "pw", "role": "collector"})
    client.get("/logout")
    client.post("/login", data={"username": "jean", "password": "pw"})
    assert client.get(f"/clients/{k.client_id}").status_code == 403


def test_momo_safe_text():
    from app.momo import safe_text
    assert safe_text("AGRUNI w'isuku 00001/AGRUNI/2026 <x>") == "AGRUNI wisuku 00001/AGRUNI/2026 x"


def test_pindo_sms(client, monkeypatch):
    import app.sms as sms
    from flask import current_app
    sent = {}

    class R:
        ok = True
        status_code = 201
        text = '{"sms_id": 1}'

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return R()

    monkeypatch.setattr(sms.requests, "post", fake_post)
    current_app.config.update(SMS_MODE="pindo", PINDO_API_TOKEN="tok", PINDO_SENDER="PindoTest")
    log = sms.send_sms("250788123456", "hello")
    assert log.status == "SENT"
    assert sent["json"] == {"to": "+250788123456", "text": "hello", "sender": "PindoTest"}
    assert sent["headers"]["Authorization"] == "Bearer tok"


def test_backup_download(client):
    import io
    import zipfile

    register(client)
    r = client.get("/backup")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    assert {"user.csv", "client.csv", "contract.csv", "invoice.csv", "payment.csv", "sms_log.csv"} == set(zf.namelist())
    assert "password_hash" not in zf.read("user.csv").decode()
    client.post("/users", data={"name": "Jean", "username": "jean", "password": "pw", "role": "collector"})
    client.get("/logout")
    client.post("/login", data={"username": "jean", "password": "pw"})
    assert client.get("/backup").status_code == 403
