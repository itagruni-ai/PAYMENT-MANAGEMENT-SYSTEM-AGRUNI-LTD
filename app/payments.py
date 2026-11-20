import time
from datetime import datetime

from flask import current_app, url_for

from . import db
from .billing import ensure_invoices
from .models import Payment
from .momo import MomoError, get_status, request_to_pay
from .sms import send_sms
from .utils import money, normalize_msisdn


def start_momo_payment(contract, amount, phone, user):
    ensure_invoices(contract)
    client = contract.client
    payment = Payment(
        contract=contract,
        amount=int(amount),
        phone=normalize_msisdn(phone),
        method="momo",
        status="PENDING",
        initiated_by=user,
    )
    db.session.add(payment)
    db.session.flush()
    payment.external_id = f"PAY{payment.id:08d}"
    callback = None
    base = current_app.config.get("PUBLIC_BASE_URL")
    if base:
        callback = base.rstrip("/") + url_for("main.momo_callback")
    try:
        payment.reference_id = request_to_pay(
            amount=amount,
            phone=payment.phone,
            external_id=payment.external_id,
            payer_message=f"AGRUNI umusanzu w'isuku {client.code}",
            payee_note=f"{client.full_name} {client.code}",
            callback_url=callback,
        )
    except MomoError as exc:
        payment.status = "FAILED"
        payment.reason = str(exc)[:255]
    db.session.commit()
    return payment


def record_manual_payment(contract, amount, method, user, note=None):
    ensure_invoices(contract)
    payment = Payment(
        contract=contract,
        amount=int(amount),
        phone=normalize_msisdn(contract.client.phone),
        method=method,
        status="SUCCESSFUL",
        initiated_by=user,
        reason=note,
        confirmed_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()
    send_thank_you(payment)
    return payment


def apply_status(payment, result):
    """Update a payment from an MTN status result; send the SMS once on success."""
    status = result.get("status")
    if payment.status != "PENDING" or status not in ("SUCCESSFUL", "FAILED"):
        return payment
    payment.status = status
    payment.financial_transaction_id = result.get("financialTransactionId")
    payment.reason = result.get("reason")
    payment.confirmed_at = datetime.utcnow()
    db.session.commit()
    if status == "SUCCESSFUL":
        send_thank_you(payment)
    return payment


def refresh_payment(payment):
    if payment.status != "PENDING" or not payment.reference_id:
        return payment
    try:
        return apply_status(payment, get_status(payment.reference_id))
    except MomoError as exc:
        current_app.logger.warning("MoMo status check failed for %s: %s", payment.id, exc)
        return payment


def send_thank_you(payment):
    if payment.sms_sent:
        return
    contract = payment.contract
    client = contract.client
    balance = contract.balance
    message = current_app.config["SMS_TEMPLATE"].format(
        name=client.first_name,
        paid=money(payment.amount),
        balance=money(max(balance, 0)),
        credit=money(max(-balance, 0)),
        code=client.code,
        ref=payment.financial_transaction_id or payment.external_id or payment.id,
    )
    if balance < 0:
        message += f" Mufite avansi ya {money(-balance)} RWF."
    send_sms(normalize_msisdn(client.phone), message, client_id=client.id, payment_id=payment.id)
    payment.sms_sent = True
    db.session.commit()


def poll_pending_forever(app):
    """Background safety net: confirm pending MoMo payments even if no callback arrives."""
    while True:
        time.sleep(app.config["MOMO_POLL_SECONDS"])
        try:
            with app.app_context():
                for p in Payment.query.filter_by(status="PENDING", method="momo").all():
                    refresh_payment(p)
                db.session.remove()
        except Exception:  # keep the poller alive
            app.logger.exception("Payment poller error")
