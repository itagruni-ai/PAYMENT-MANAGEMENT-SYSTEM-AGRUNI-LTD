import csv
import io
import json
import os
import zipfile
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import db
from .billing import ensure_invoices, first_month_amount, next_client_code, next_contract_number
from .models import WEEKDAYS, Client, Contract, Payment, SmsLog, User
from .payments import apply_status, record_manual_payment, refresh_payment, start_momo_payment
from .utils import fill_dots

bp = Blueprint("main", __name__)

with open(os.path.join(os.path.dirname(__file__), "contract_articles.json"), encoding="utf-8") as f:
    ARTICLES = json.load(f)


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def visible_clients():
    q = Client.query
    if not current_user.is_admin:
        q = q.filter_by(collector_id=current_user.id)
    return q


def get_client_or_404(client_id):
    client = db.session.get(Client, client_id) or abort(404)
    if not current_user.is_admin and client.collector_id != current_user.id:
        abort(403)
    return client


def _int(value, default=None):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and user.active and user.check_password(request.form.get("password", "")):
            login_user(user)
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("main.login"))


@bp.route("/")
@login_required
def dashboard():
    clients = visible_clients().all()
    for c in clients:
        if c.contract:
            ensure_invoices(c.contract)
    contracts = [c.contract for c in clients if c.contract]
    pq = Payment.query.join(Contract).join(Client)
    if not current_user.is_admin:
        pq = pq.filter(Client.collector_id == current_user.id)
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    ok = pq.filter(Payment.status == "SUCCESSFUL")
    stats = {
        "clients": len(clients),
        "outstanding": sum(max(c.balance, 0) for c in contracts),
        "collected_today": sum(p.amount for p in ok.filter(Payment.confirmed_at >= datetime(today.year, today.month, today.day))),
        "collected_month": sum(p.amount for p in ok.filter(Payment.confirmed_at >= month_start)),
        "pending": pq.filter(Payment.status == "PENDING").count(),
    }
    recent = pq.order_by(Payment.id.desc()).limit(10).all()
    return render_template("dashboard.html", stats=stats, recent=recent)


@bp.route("/clients")
@login_required
def clients():
    q = visible_clients()
    s = request.args.get("q", "").strip()
    if s:
        like = f"%{s}%"
        q = q.filter(
            db.or_(Client.first_name.ilike(like), Client.second_name.ilike(like), Client.phone.ilike(like), Client.code.ilike(like))
        )
    return render_template("clients.html", clients=q.order_by(Client.id.desc()).all(), q=s)


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    collectors = User.query.filter_by(active=True).order_by(User.name).all()
    if request.method == "POST":
        f = request.form
        ctype = f.get("client_type", "household")
        fee = _int(f.get("monthly_fee"))
        start = date.fromisoformat(f.get("start_date") or date.today().isoformat())
        errors = []
        if not f.get("first_name", "").strip():
            errors.append("First name is required")
        if not f.get("phone", "").strip():
            errors.append("Phone is required")
        if not fee or fee <= 0:
            errors.append("Monthly fee must be a positive number")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("client_form.html", form=f, weekdays=WEEKDAYS, collectors=collectors, today=date.today())

        collector_id = _int(f.get("collector_id")) if current_user.is_admin else current_user.id
        client = Client(
            code=next_client_code(start.year),
            client_type=ctype,
            first_name=f["first_name"].strip(),
            second_name=f.get("second_name", "").strip(),
            phone=f["phone"].strip(),
            email=f.get("email", "").strip(),
            district=f.get("district", "").strip(),
            sector=f.get("sector", "").strip(),
            cell=f.get("cell", "").strip(),
            village=f.get("village", "").strip(),
            collector_id=collector_id or current_user.id,
        )
        db.session.add(client)
        db.session.flush()
        end = f.get("end_date")
        contract = Contract(
            number=next_contract_number(ctype, start.year),
            client=client,
            contract_type=ctype,
            monthly_fee=fee,
            collection_days=",".join(f.getlist("collection_days")),
            pickups_per_month=_int(f.get("pickups_per_month")),
            volume=f.get("volume", "").strip(),
            bag_price=_int(f.get("bag_price")),
            due_day=_int(f.get("due_day"), 10),
            payment_method=f.get("payment_method", "momo"),
            momo_code=f.get("momo_code", "").strip(),
            bank_account=f.get("bank_account", "").strip(),
            dump_site=f.get("dump_site", "").strip(),
            duration=f.get("duration", "").strip(),
            start_date=start,
            end_date=date.fromisoformat(end) if end else None,
            created_by=current_user,
        )
        db.session.add(contract)
        db.session.commit()
        ensure_invoices(contract)
        flash(f"Client {client.code} registered and contract {contract.number} created", "success")
        return redirect(url_for("main.client_detail", client_id=client.id))
    return render_template("client_form.html", form={}, weekdays=WEEKDAYS, collectors=collectors, today=date.today())


@bp.route("/clients/<int:client_id>")
@login_required
def client_detail(client_id):
    client = get_client_or_404(client_id)
    contract = client.contract
    if contract:
        ensure_invoices(contract)
        for p in contract.payments:
            if p.status == "PENDING":
                refresh_payment(p)
    sms = SmsLog.query.filter_by(client_id=client.id).order_by(SmsLog.id.desc()).limit(20).all()
    return render_template("client_detail.html", client=client, contract=contract, sms=sms)


@bp.route("/clients/<int:client_id>/pay", methods=["POST"])
@login_required
def client_pay(client_id):
    client = get_client_or_404(client_id)
    contract = client.contract or abort(400)
    amount = _int(request.form.get("amount"))
    if not amount or amount <= 0:
        flash("Enter a valid amount", "danger")
        return redirect(url_for("main.client_detail", client_id=client.id))
    method = request.form.get("method", "momo")
    if method == "momo":
        payment = start_momo_payment(contract, amount, request.form.get("phone") or client.phone, current_user)
        if payment.status == "FAILED":
            flash(f"MoMo request failed: {payment.reason}", "danger")
        else:
            flash("Payment request sent. Ask the client to approve it with their MoMo PIN.", "info")
    else:
        if not current_user.is_admin:
            abort(403)
        record_manual_payment(contract, amount, method, current_user, request.form.get("note"))
        flash("Payment recorded and SMS sent", "success")
    return redirect(url_for("main.client_detail", client_id=client.id))


@bp.route("/payments/<int:payment_id>/status")
@login_required
def payment_status(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    get_client_or_404(payment.contract.client_id)
    refresh_payment(payment)
    return jsonify(
        status=payment.status,
        reason=payment.reason,
        balance=payment.contract.balance,
        sms_sent=payment.sms_sent,
    )


@bp.route("/momo/callback", methods=["POST", "PUT"])
def momo_callback():
    data = request.get_json(silent=True) or {}
    ext = data.get("externalId")
    payment = Payment.query.filter_by(external_id=ext).first() if ext else None
    if payment and payment.status == "PENDING":
        # Never trust the callback body alone: re-check status with MTN before crediting.
        refresh_payment(payment)
    return "", 200


@bp.route("/clients/<int:client_id>/contract")
@login_required
def contract_print(client_id):
    client = get_client_or_404(client_id)
    contract = client.contract or abort(404)
    articles = []
    for a in ARTICLES[contract.contract_type]:
        body = a["body"]
        if "KIMOTERI" in body:
            body = fill_dots(body, [contract.dump_site or "……………………"])
        if "AZAMARA IGIHE" in body:
            body = fill_dots(
                body,
                [
                    contract.duration or "……………",
                    contract.start_date.strftime("%d/%m/%Y"),
                    contract.end_date.strftime("%d/%m/%Y") if contract.end_date else "……………",
                ],
            )
        articles.append({"title": a["title"], "body": body})
    return render_template(
        "contract_print.html",
        client=client,
        contract=contract,
        articles=articles,
        weekdays=WEEKDAYS,
        first_amount=first_month_amount(contract.monthly_fee, contract.start_date),
    )


@bp.route("/payments")
@login_required
def payments():
    q = Payment.query.join(Contract).join(Client)
    if not current_user.is_admin:
        q = q.filter(Client.collector_id == current_user.id)
    status = request.args.get("status")
    if status:
        q = q.filter(Payment.status == status)
    return render_template("payments.html", payments=q.order_by(Payment.id.desc()).limit(500).all(), status=status)


@bp.route("/sms")
@admin_required
def sms_log():
    return render_template("sms.html", logs=SmsLog.query.order_by(SmsLog.id.desc()).limit(500).all())


@bp.route("/backup")
@admin_required
def backup():
    """Download every table as CSV files (Excel-friendly) in one zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in db.metadata.sorted_tables:
            cols = [c.name for c in table.columns if c.name != "password_hash"]
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(cols)
            for row in db.session.execute(table.select().order_by(*table.primary_key.columns)).mappings():
                w.writerow([row[c] for c in cols])
            zf.writestr(f"{table.name}.csv", "\ufeff" + out.getvalue())
    name = f"agruni-backup-{datetime.now():%Y-%m-%d-%H%M}.zip"
    return Response(
        buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename={name}"}
    )


@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        f = request.form
        if User.query.filter_by(username=f.get("username", "").strip()).first():
            flash("Username already exists", "danger")
        elif not f.get("username") or not f.get("password") or not f.get("name"):
            flash("Name, username and password are required", "danger")
        else:
            u = User(name=f["name"].strip(), username=f["username"].strip(), phone=f.get("phone", "").strip(), role=f.get("role", "collector"))
            u.set_password(f["password"])
            db.session.add(u)
            db.session.commit()
            flash(f"User {u.username} created", "success")
        return redirect(url_for("main.users"))
    return render_template("users.html", users=User.query.order_by(User.id).all())


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def user_toggle(user_id):
    u = db.session.get(User, user_id) or abort(404)
    if u.id != current_user.id:
        u.active = not u.active
        db.session.commit()
    return redirect(url_for("main.users"))
