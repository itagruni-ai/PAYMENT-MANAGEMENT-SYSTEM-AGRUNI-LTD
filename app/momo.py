"""MTN MoMo Collections API client (Request to Pay)."""
import base64
import threading
import time
import uuid

import requests
from flask import current_app

from .utils import normalize_msisdn

_token_lock = threading.Lock()
_token_cache = {"token": None, "expires": 0}
_mock_requests = {}


class MomoError(Exception):
    pass


def _cfg(key):
    return current_app.config[key]


def _headers(extra=None):
    h = {"Ocp-Apim-Subscription-Key": _cfg("MOMO_SUBSCRIPTION_KEY")}
    if extra:
        h.update(extra)
    return h


def get_token():
    with _token_lock:
        if _token_cache["token"] and _token_cache["expires"] > time.time() + 60:
            return _token_cache["token"]
        creds = f"{_cfg('MOMO_API_USER')}:{_cfg('MOMO_API_KEY')}".encode()
        r = requests.post(
            f"{_cfg('MOMO_BASE_URL')}/collection/token/",
            headers=_headers({"Authorization": "Basic " + base64.b64encode(creds).decode()}),
            timeout=30,
        )
        if r.status_code != 200:
            raise MomoError(f"Token request failed ({r.status_code}): {r.text}")
        data = r.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires"] = time.time() + int(data.get("expires_in", 3600))
        return _token_cache["token"]


def request_to_pay(amount, phone, external_id, payer_message, payee_note, callback_url=None):
    """Send a payment prompt to the client's phone. Returns the X-Reference-Id."""
    reference_id = str(uuid.uuid4())
    msisdn = normalize_msisdn(phone)
    if _cfg("MOMO_MODE") == "mock":
        _mock_requests[reference_id] = {"created": time.time(), "msisdn": msisdn}
        return reference_id

    headers = _headers(
        {
            "Authorization": f"Bearer {get_token()}",
            "X-Reference-Id": reference_id,
            "X-Target-Environment": _cfg("MOMO_TARGET_ENV"),
            "Content-Type": "application/json",
        }
    )
    if callback_url:
        headers["X-Callback-Url"] = callback_url
    body = {
        "amount": str(int(amount)),
        "currency": _cfg("MOMO_CURRENCY"),
        "externalId": str(external_id),
        "payer": {"partyIdType": "MSISDN", "partyId": msisdn},
        "payerMessage": payer_message[:160],
        "payeeNote": payee_note[:160],
    }
    r = requests.post(
        f"{_cfg('MOMO_BASE_URL')}/collection/v1_0/requesttopay", json=body, headers=headers, timeout=30
    )
    if r.status_code != 202:
        raise MomoError(f"Request to pay failed ({r.status_code}): {r.text}")
    return reference_id


def get_status(reference_id):
    """Return dict with status (PENDING|SUCCESSFUL|FAILED), financialTransactionId, reason."""
    if _cfg("MOMO_MODE") == "mock":
        req = _mock_requests.get(reference_id)
        if not req:
            return {"status": "FAILED", "reason": "UNKNOWN_REFERENCE"}
        if time.time() - req["created"] < 6:
            return {"status": "PENDING"}
        if req["msisdn"].endswith("000"):
            return {"status": "FAILED", "reason": "PAYER_REJECTED"}
        return {"status": "SUCCESSFUL", "financialTransactionId": "MOCK" + reference_id[:8].upper()}

    r = requests.get(
        f"{_cfg('MOMO_BASE_URL')}/collection/v1_0/requesttopay/{reference_id}",
        headers=_headers(
            {"Authorization": f"Bearer {get_token()}", "X-Target-Environment": _cfg("MOMO_TARGET_ENV")}
        ),
        timeout=30,
    )
    if r.status_code != 200:
        raise MomoError(f"Status request failed ({r.status_code}): {r.text}")
    data = r.json()
    reason = data.get("reason")
    if isinstance(reason, dict):
        reason = reason.get("code") or reason.get("message")
    return {
        "status": data.get("status", "PENDING"),
        "financialTransactionId": data.get("financialTransactionId"),
        "reason": reason,
    }


def create_sandbox_user(subscription_key, base_url, callback_host):
    """Provision an API user + key in the MoMo sandbox. Returns (api_user, api_key)."""
    api_user = str(uuid.uuid4())
    h = {"Ocp-Apim-Subscription-Key": subscription_key, "X-Reference-Id": api_user}
    r = requests.post(
        f"{base_url}/v1_0/apiuser", json={"providerCallbackHost": callback_host}, headers=h, timeout=30
    )
    if r.status_code != 201:
        raise MomoError(f"Create API user failed ({r.status_code}): {r.text}")
    r = requests.post(
        f"{base_url}/v1_0/apiuser/{api_user}/apikey",
        headers={"Ocp-Apim-Subscription-Key": subscription_key},
        timeout=30,
    )
    if r.status_code != 201:
        raise MomoError(f"Create API key failed ({r.status_code}): {r.text}")
    return api_user, r.json()["apiKey"]
