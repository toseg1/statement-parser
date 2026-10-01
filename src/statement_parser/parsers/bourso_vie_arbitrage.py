"""Bourso Vie (Generali) "Arbitrage" letter for a life-insurance
contract: what was sold (désinvestissement) and bought
(réinvestissement), each support with its units, NAV and value, then a
"Valeur atteinte après arbitrage" page listing the resulting holdings.

Movements are one per support in the switch, amount 0 (the money moves
between supports inside the contract, not in or out) — the same shape
as cm_av_arbitrage, so callers can treat both alike.
"""

import re

from ..models import ZERO, Movement, Position, StatementDocument
from ..text import DATE, currency_code, fr_date, fr_decimal

DOC_TYPE = "bourso_vie_arbitrage"
BROKER = "Bourso Vie"

UNITS = r"\d{1,3}(?: \d{3})*,\d+"
VALUE = r"\d{1,3}(?: \d{3})*,\d{2}"
CONTRACT_RE = re.compile(r"Contrat n° (\d+)")
AMOUNT_RE = re.compile(rf"Arbitrage d'un montant de : ({VALUE}) (Euros) en date du {DATE}")
SECTION_RE = re.compile(r"^- (Désinvestissement|Réinvestissement) :$")
VALEUR_ATTEINTE_RE = re.compile(r"^OBJET : Valeur atteinte")
CATEGORY_RE = re.compile(r"^- (Fonds en Euros|Unités de Compte)$")
# "- *Compartiment SICAV NAME (ISIN : LU0000000000)" or "- Fonds Euro Exclusif";
# "- Références à rappeler -" (the letter heading) ends with a dash and isn't one.
SUPPORT_RE = re.compile(r"^- \*?(.+?[^-\s])(?: \(ISIN : ([A-Z]{2}[A-Z0-9]{9}\d)\))?$")
UNIT_VALUE_RE = re.compile(
    rf"^Valeur au {DATE} : ({UNITS}) Parts à ({UNITS}) Euros l'unité soit ({VALUE}) Euros$"
)
EURO_VALUE_RE = re.compile(rf"^Valeur au {DATE} : ({VALUE}) Euros$")
PARTS_RE = re.compile(rf"^Nombre de parts : ({UNITS}) Parts$")
NAV_RE = re.compile(rf"^Valeur de la part au {DATE} : ({UNITS}) Euros$")
COUNTER_VALUE_RE = re.compile(rf"^Contre-valeur en Euros : ({VALUE}) Euros$")
TOTAL_RE = re.compile(rf"^Epargne atteinte totale : ({VALUE}) Euros$")
# Values are printed to the cent and units x NAV is rounded per line.
TOLERANCE = fr_decimal("0,05")


def detect(doc):
    return "Bourso Vie" in doc.text and "OBJET : Arbitrage" in doc.text


def parse(doc):
    result = StatementDocument(
        source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE, account_label="Bourso Vie"
    )
    contract = CONTRACT_RE.search(doc.text)
    if contract:
        result.account_ref = contract.group(1)
    amount = AMOUNT_RE.search(doc.text)
    if amount is None:
        result.warnings.append("arbitrage amount and date not found")
        return result
    stated = fr_decimal(amount.group(1))
    result.currency = currency_code(amount.group(2))
    when = fr_date(amount.group(3))
    result.period_start = result.period_end = when

    state, category, support = None, None, None
    held = {}  # the "valeur atteinte" block: units / NAV / NAV date of the current support
    total = None
    for raw in doc.text.splitlines():
        line = raw.strip()
        if VALEUR_ATTEINTE_RE.match(line):
            state, category, support = "after", None, None
            continue
        section = SECTION_RE.match(line)
        if section:
            state = "out" if section.group(1) == "Désinvestissement" else "in"
            category, support = None, None
            continue
        if state is None:
            continue
        cat = CATEGORY_RE.match(line)
        if cat:
            category = cat.group(1)
            continue
        sup = SUPPORT_RE.match(line)
        if sup:
            support = (sup.group(1).strip(), sup.group(2))
            held = {}
            continue
        if state == "after":
            total_line = TOTAL_RE.match(line)
            if total_line:
                total = fr_decimal(total_line.group(1))
                continue
            if support is None:
                continue
            if m := PARTS_RE.match(line):
                held["quantity"] = fr_decimal(m.group(1))
            elif m := NAV_RE.match(line):
                held["as_of"], held["price"] = fr_date(m.group(1)), fr_decimal(m.group(2))
            elif (m := COUNTER_VALUE_RE.match(line)) or (m := EURO_VALUE_RE.match(line)):
                value = fr_decimal(m.group(m.lastindex))
                result.positions.append(
                    Position(
                        as_of=held.get("as_of", when), security_name=support[0], value=value,
                        quantity=held.get("quantity"), price=held.get("price"),
                        isin=support[1], currency=result.currency, section=category, snapshot="after",
                    )
                )
                support = None
            continue
        if support is None:
            continue
        movement = _switch(line, state, support, when, result.currency)
        if movement:
            result.movements.append(movement)
            support = None

    _reconcile(result, stated, total)
    return result


def _switch(line, state, support, when, currency):
    """The movement for a "Valeur au ..." line under a support, or None
    if the line isn't one."""
    name, isin = support
    sign = -1 if state == "out" else 1
    units = UNIT_VALUE_RE.match(line)
    if units:
        return Movement(
            date=when, label=f"Arbitrage {name}", amount=ZERO, currency=currency,
            kind="SWITCH_OUT" if state == "out" else "SWITCH_IN",
            value_date=fr_date(units.group(1)), quantity=sign * fr_decimal(units.group(2)),
            isin=isin, security_name=name, price=fr_decimal(units.group(3)),
            gross=fr_decimal(units.group(4)),
        )
    euro = EURO_VALUE_RE.match(line)
    if euro:  # the euro fund: a value, no units
        value = fr_decimal(euro.group(2))
        return Movement(
            date=when, label=f"Arbitrage {name}", amount=ZERO, currency=currency, kind="SWITCH",
            value_date=fr_date(euro.group(1)), isin=isin, security_name=name, gross=value,
            extra={"value_delta": sign * value, "unitless": True},
        )
    return None


def _signed_value(movement):
    if movement.extra.get("unitless"):
        return movement.extra["value_delta"]
    return movement.gross if movement.quantity > 0 else -movement.gross


def _reconcile(result, stated, total):
    if not result.movements:
        result.warnings.append("no switched support found")
        return
    sold = -sum((_signed_value(m) for m in result.movements if _signed_value(m) < 0), ZERO)
    bought = sum((_signed_value(m) for m in result.movements if _signed_value(m) > 0), ZERO)
    for side, value in (("désinvestissement", sold), ("réinvestissement", bought)):
        if abs(value - stated) > TOLERANCE:
            result.warnings.append(f"{side} supports sum to {value}, arbitrage amount says {stated}")
    if total is not None:
        listed = sum((p.value for p in result.positions), ZERO)
        if abs(listed - total) > TOLERANCE:
            result.warnings.append(f"after: positions sum to {listed}, total says {total}")
