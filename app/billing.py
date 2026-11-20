import calendar
from datetime import date

from . import db
from .models import Client, Contract, Invoice


def _months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def first_month_amount(fee, start):
    """Pro-rate the first month by the days left in it (contract Ingingo 8)."""
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    if start.day == 1:
        return fee
    remaining = days_in_month - start.day + 1
    return int(round(fee * remaining / days_in_month))


def ensure_invoices(contract, today=None):
    """Create any missing monthly charges up to the current month. Returns number created."""
    today = today or date.today()
    if contract.status != "active":
        end = contract.end_date or today
    else:
        end = min(today, contract.end_date) if contract.end_date else today
    existing = {i.period for i in contract.invoices}
    created = 0
    for y, m in _months(contract.start_date, end):
        period = f"{y:04d}-{m:02d}"
        if period in existing:
            continue
        first = (y, m) == (contract.start_date.year, contract.start_date.month)
        amount = first_month_amount(contract.monthly_fee, contract.start_date) if first else contract.monthly_fee
        note = "Pro-rated first month" if first and amount != contract.monthly_fee else None
        db.session.add(Invoice(contract=contract, period=period, amount=amount, note=note))
        created += 1
    if created:
        db.session.commit()
    return created


def bill_all(today=None):
    return sum(ensure_invoices(c, today) for c in Contract.query.filter_by(status="active").all())


def next_client_code(year=None):
    year = year or date.today().year
    seq = (db.session.query(db.func.max(Client.id)).scalar() or 0) + 1
    return f"{seq:05d}/AGRUNI/{year}"


def next_contract_number(contract_type, year=None):
    year = year or date.today().year
    prefix = "HH" if contract_type == "household" else "BS"
    seq = (db.session.query(db.func.max(Contract.id)).scalar() or 0) + 1
    return f"{prefix}-{year}-{seq:05d}"
