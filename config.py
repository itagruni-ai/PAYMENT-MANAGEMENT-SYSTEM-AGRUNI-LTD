import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///agruni.db")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

    COMPANY_NAME = "AGRUNI Ltd"
    COMPANY_PHONES = "0788435111 / 0788308655"
    CURRENCY = "RWF"

    MOMO_MODE = os.environ.get("MOMO_MODE", "mock")
    MOMO_SUBSCRIPTION_KEY = os.environ.get("MOMO_SUBSCRIPTION_KEY", "")
    MOMO_API_USER = os.environ.get("MOMO_API_USER", "")
    MOMO_API_KEY = os.environ.get("MOMO_API_KEY", "")
    MOMO_BASE_URL = os.environ.get("MOMO_BASE_URL", "https://sandbox.momodeveloper.mtn.com")
    MOMO_CURRENCY = os.environ.get("MOMO_CURRENCY", "EUR")
    MOMO_TARGET_ENV = os.environ.get("MOMO_TARGET_ENV", "sandbox")
    MOMO_POLL_SECONDS = int(os.environ.get("MOMO_POLL_SECONDS", "10"))

    SMS_MODE = os.environ.get("SMS_MODE", "mock")
    AT_USERNAME = os.environ.get("AT_USERNAME", "sandbox")
    AT_API_KEY = os.environ.get("AT_API_KEY", "")
    AT_SENDER_ID = os.environ.get("AT_SENDER_ID", "")
    SMS_TEMPLATE = os.environ.get(
        "SMS_TEMPLATE",
        "AGRUNI Ltd: Murakoze {name} kwishyura umusanzu w'isuku. "
        "Twakiriye {paid} RWF. Asigaye kwishyura: {balance} RWF. "
        "Code: {code}. Ref: {ref}. Ikibazo: 0788435111",
    )
