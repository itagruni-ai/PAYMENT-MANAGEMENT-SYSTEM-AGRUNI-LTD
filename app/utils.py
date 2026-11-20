import re


def money(value):
    try:
        return f"{int(round(value or 0)):,}"
    except (TypeError, ValueError):
        return str(value)


def normalize_msisdn(phone):
    """Return a Rwandan MSISDN like 2507XXXXXXXX (no plus sign)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("250") and len(digits) == 12:
        return digits
    if digits.startswith("07") and len(digits) == 10:
        return "250" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "250" + digits
    return digits


def fill_dots(text, values):
    """Replace successive runs of dotted placeholders in template text with values."""
    values = list(values)

    def repl(match):
        return values.pop(0) if values else match.group(0)

    return re.sub(r"[.…]{3,}", repl, text)
