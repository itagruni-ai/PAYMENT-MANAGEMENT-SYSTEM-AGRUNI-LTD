from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

WEEKDAYS = [
    ("mon", "Kuwa Mbere"),
    ("tue", "Kuwa Kabiri"),
    ("wed", "Kuwa Gatatu"),
    ("thu", "Kuwa Kane"),
    ("fri", "Kuwa Gatanu"),
    ("sat", "Kuwa Gatandatu"),
]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(64), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), nullable=False, default="collector")  # admin | collector
    active = db.Column(db.Boolean, default=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_active(self):
        return bool(self.active)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True)
    client_type = db.Column(db.String(20), nullable=False, default="household")  # household | business
    first_name = db.Column(db.String(120), nullable=False)
    second_name = db.Column(db.String(120))
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    district = db.Column(db.String(80))  # Akarere
    sector = db.Column(db.String(80))  # Umurenge
    cell = db.Column(db.String(80))  # Akagari
    village = db.Column(db.String(80))  # Umudugudu
    collector_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    collector = db.relationship("User")
    contracts = db.relationship("Contract", back_populates="client", order_by="Contract.id.desc()")

    @property
    def full_name(self):
        return " ".join(p for p in [self.first_name, self.second_name] if p)

    @property
    def contract(self):
        active = [c for c in self.contracts if c.status == "active"]
        return active[0] if active else (self.contracts[0] if self.contracts else None)


class Contract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    contract_type = db.Column(db.String(20), nullable=False)  # household | business
    monthly_fee = db.Column(db.Integer, nullable=False)
    collection_days = db.Column(db.String(40), default="")  # csv of mon..sat
    pickups_per_month = db.Column(db.Integer)
    volume = db.Column(db.String(200))  # Ingano y'ibitwarwa
    bag_price = db.Column(db.Integer)
    due_day = db.Column(db.Integer, default=10)
    payment_method = db.Column(db.String(20), default="momo")  # system | momo | bank | cash
    momo_code = db.Column(db.String(40))
    bank_account = db.Column(db.String(60))
    dump_site = db.Column(db.String(120))
    duration = db.Column(db.String(60))  # business only
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="active")  # active | terminated
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", back_populates="contracts")
    created_by = db.relationship("User")
    invoices = db.relationship("Invoice", back_populates="contract", order_by="Invoice.period")
    payments = db.relationship("Payment", back_populates="contract", order_by="Payment.id.desc()")

    @property
    def days_list(self):
        return [d for d in (self.collection_days or "").split(",") if d]

    @property
    def total_billed(self):
        return sum(i.amount for i in self.invoices)

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments if p.status == "SUCCESSFUL")

    @property
    def balance(self):
        return self.total_billed - self.total_paid


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contract.id"), nullable=False)
    period = db.Column(db.String(7), nullable=False)  # YYYY-MM
    amount = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contract = db.relationship("Contract", back_populates="invoices")
    __table_args__ = (db.UniqueConstraint("contract_id", "period"),)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contract.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    phone = db.Column(db.String(20))
    method = db.Column(db.String(20), default="momo")  # momo | cash | bank
    status = db.Column(db.String(20), default="PENDING")  # PENDING | SUCCESSFUL | FAILED
    reference_id = db.Column(db.String(64), unique=True)  # X-Reference-Id sent to MTN
    external_id = db.Column(db.String(64))
    financial_transaction_id = db.Column(db.String(64))
    reason = db.Column(db.String(255))
    sms_sent = db.Column(db.Boolean, default=False)
    initiated_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime)

    contract = db.relationship("Contract", back_populates="payments")
    initiated_by = db.relationship("User")


class SmsLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"))
    phone = db.Column(db.String(20))
    message = db.Column(db.Text)
    status = db.Column(db.String(40))
    provider_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client")


def ensure_admin(app):
    if User.query.filter_by(role="admin").first():
        return
    import os

    admin = User(
        name="Administrator",
        username=os.environ.get("ADMIN_USERNAME", "admin"),
        role="admin",
    )
    admin.set_password(os.environ.get("ADMIN_PASSWORD", "admin123"))
    db.session.add(admin)
    db.session.commit()
