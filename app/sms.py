"""SMS sending through Africa's Talking."""
import requests
from flask import current_app

from . import db
from .models import SmsLog

AT_URLS = {
    "sandbox": "https://api.sandbox.africastalking.com/version1/messaging",
    "production": "https://api.africastalking.com/version1/messaging",
}


def send_sms(phone, message, client_id=None, payment_id=None):
    cfg = current_app.config
    to = "+" + phone.lstrip("+")
    log = SmsLog(client_id=client_id, payment_id=payment_id, phone=to, message=message)
    mode = cfg["SMS_MODE"]
    if mode == "mock":
        log.status = "MOCK_SENT"
        current_app.logger.info("[MOCK SMS] to %s: %s", to, message)
    else:
        try:
            data = {"username": cfg["AT_USERNAME"], "to": to, "message": message}
            if cfg["AT_SENDER_ID"]:
                data["from"] = cfg["AT_SENDER_ID"]
            r = requests.post(
                AT_URLS[mode],
                data=data,
                headers={"apiKey": cfg["AT_API_KEY"], "Accept": "application/json"},
                timeout=30,
            )
            log.provider_response = r.text[:2000]
            recipients = (r.json().get("SMSMessageData", {}) or {}).get("Recipients", []) if r.ok else []
            log.status = recipients[0].get("status", "UNKNOWN") if recipients else f"HTTP_{r.status_code}"
        except Exception as exc:  # network / JSON errors must not break payment flow
            log.status = "ERROR"
            log.provider_response = str(exc)[:2000]
    db.session.add(log)
    db.session.commit()
    return log
