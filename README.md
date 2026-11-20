# AGRUNI Pay

Payment management for AGRUNI Ltd waste-collection clients (Rwanda).

- Collectors register clients; a household or business contract (from AGRUNI's templates) is created automatically.
- Monthly charges are generated per contract (first month pro-rated, Ingingo 8).
- The **PAY** button sends an MTN MoMo *Request to Pay* to the client's phone; the client approves with their PIN.
- When MTN confirms (callback + background status polling), the payment is recorded and an SMS thanks the client with the amount paid and remaining balance (Africa's Talking).
- Admins manage collectors, see all clients/payments/SMS, and can record cash/bank payments.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # edit values, then: set -a; . ./.env; set +a
gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 wsgi:app
```

Default login: `admin` / `admin123` (set `ADMIN_USERNAME` / `ADMIN_PASSWORD` before first run).
Run with a single worker so only one background payment poller runs.

Monthly billing also happens automatically when a client is viewed; to bill everyone (e.g. daily cron): `flask --app wsgi bill`.

## MTN MoMo

1. On https://momodeveloper.mtn.com subscribe to **Collections** and copy the Primary key into `MOMO_SUBSCRIPTION_KEY`.
2. Sandbox: `MOMO_MODE=sandbox flask --app wsgi momo-sandbox-user --callback-host your-domain` prints `MOMO_API_USER` / `MOMO_API_KEY`. Sandbox only accepts `MOMO_CURRENCY=EUR`.
3. Production (after MTN Rwanda go-live approval): `MOMO_MODE=production`, `MOMO_BASE_URL=https://proxy.momoapi.mtn.com`, `MOMO_TARGET_ENV=mtnrwanda`, `MOMO_CURRENCY=RWF`, with the API user/key from the MoMo partner portal.
4. Set `PUBLIC_BASE_URL` so MTN can call `/momo/callback`. The callback is always re-verified against MTN before crediting.

`MOMO_MODE=mock` simulates approval after ~6 seconds (numbers ending in `000` are rejected).

## SMS

Pindo (Rwanda): `SMS_MODE=pindo`, `PINDO_API_TOKEN`, `PINDO_SENDER` (default `PindoTest`; request an `AGRUNI` sender ID from Pindo).

Africa's Talking: `SMS_MODE=sandbox|production`, `AT_USERNAME`, `AT_API_KEY`, optional `AT_SENDER_ID`. Message wording: `SMS_TEMPLATE` in `config.py` (placeholders `{name} {paid} {balance} {code} {ref}`).

## Tests

```bash
pip install pytest && python -m pytest -q
```
