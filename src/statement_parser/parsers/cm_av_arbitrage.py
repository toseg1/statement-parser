"""Crédit Mutuel / ACM Vie "Opération d'arbitrage" letter for a managed
(Gestion Pilotée) life-insurance contract: the full allocation before
and after a switch, as (fund, units, NAV, value) rows, plus a
unit-less euro fund row (value only).

Movements are derived: one per fund whose units changed, amount 0 (the
switch moves money between funds inside the contract, not in or out).
"""

import re

from ..models import ZERO, Movement, Position, StatementDocument
from ..text import currency_code, fr_decimal, fr_long_date

DOC_TYPE = "cm_av_arbitrage"
BROKER = "Crédit Mutuel"

CONTRACT_RE = re.compile(r"N° Contrat : (\S+ \d+)")
CONTRACT_NAME_RE = re.compile(r"titulaire d'un contrat (\S+)")
DATE_RE = re.compile(r"réalisée en date du (\d{1,2} \w+ \d{4})")
SNAPSHOT_RE = re.compile(r"(avant|après) l'opération d'arbitrage")
UNITS = r"\d{1,3}(?: \d{3})*,\d+"
VALUE = r"\d{1,3}(?: \d{3})*,\d{2}"
FUND_ROW_RE = re.compile(rf"^(.+?) ({UNITS}) ({UNITS}) ({VALUE})$")
VALUE_ONLY_RE = re.compile(rf"^(.+?) ({VALUE})$")
TOTAL_RE = re.compile(rf"^TOTAL ({VALUE})$")
# Column header lines between a snapshot title and its first row
HEADER_RE = re.compile(r"^(Valeur de la part|Catégories / Supports|en (?:euros|[A-Z]{3})\b)")
# "en euros en euros": the unit of the NAV and value columns
CURRENCY_RE = re.compile(r"^en (euros|[A-Z]{3})\b")
TOLERANCE = fr_decimal("0,05")


def detect(doc):
    return "Opération d'arbitrage" in doc.text and "Gestion Pilotée" in doc.text


def parse(doc):
    result = StatementDocument(source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE)
    contract = CONTRACT_RE.search(doc.text)
    if contract:
        result.account_ref = contract.group(1)
    name = CONTRACT_NAME_RE.search(doc.text)
    result.account_label = name.group(1) if name else None
    when = DATE_RE.search(doc.text)
    as_of = fr_long_date(when.group(1)) if when else None
    if as_of is None:
        result.warnings.append("arbitrage date not found")
        return result
    result.period_start = result.period_end = as_of

    snapshot, section, currency = None, None, None
    totals = {}
    for raw in doc.text.splitlines():
        line = raw.strip()
        m = SNAPSHOT_RE.search(line)
        if m:
            snapshot = "before" if m.group(1) == "avant" else "after"
            section = None
            continue
        if snapshot is None or not line or HEADER_RE.match(line):
            if m := CURRENCY_RE.match(line):
                currency = result.currency = currency_code(m.group(1))
            continue
        total = TOTAL_RE.match(line)
        if total:
            totals[snapshot] = fr_decimal(total.group(1))
            snapshot = None
            continue
        row = FUND_ROW_RE.match(line)
        if row:
            result.positions.append(
                Position(
                    as_of=as_of, security_name=row.group(1).strip(), value=fr_decimal(row.group(4)),
                    quantity=fr_decimal(row.group(2)), price=fr_decimal(row.group(3)),
                    currency=result.currency, section=section, snapshot=snapshot,
                )
            )
            continue
        value_only = VALUE_ONLY_RE.match(line)
        if value_only:  # the euro fund: a value, no units
            result.positions.append(
                Position(
                    as_of=as_of, security_name=value_only.group(1).strip(),
                    value=fr_decimal(value_only.group(2)), currency=result.currency,
                    section=section, snapshot=snapshot,
                )
            )
            continue
        if line.isupper() and not re.search(r"\d", line):
            section = line

    if currency is None:
        result.warnings.append("no 'en euros' column header: currency assumed EUR")
    for key in ("before", "after"):
        listed = sum((p.value for p in result.positions if p.snapshot == key), ZERO)
        if key not in totals:
            result.warnings.append(f"no TOTAL line for the {key} snapshot")
        elif abs(listed - totals[key]) > TOLERANCE:
            result.warnings.append(f"{key}: rows sum to {listed}, TOTAL says {totals[key]}")

    result.movements = _switches(result.positions, as_of, result.currency)
    return result


def _switches(positions, as_of, currency):
    before = {p.security_name: p for p in positions if p.snapshot == "before"}
    after = {p.security_name: p for p in positions if p.snapshot == "after"}
    movements = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if (b and b.quantity is None) or (a and a.quantity is None):
            delta_value = (a.value if a else ZERO) - (b.value if b else ZERO)
            if delta_value:
                movements.append(
                    Movement(date=as_of, label=f"Arbitrage {name}", amount=ZERO, currency=currency,
                             kind="SWITCH",
                             security_name=name, gross=abs(delta_value),
                             extra={"value_delta": delta_value, "unitless": True})
                )
            continue
        delta = (a.quantity if a else ZERO) - (b.quantity if b else ZERO)
        if not delta:
            continue
        price = (a or b).price
        movements.append(
            Movement(
                date=as_of, label=f"Arbitrage {name}", amount=ZERO, currency=currency,
                kind="SWITCH_IN" if delta > 0 else "SWITCH_OUT",
                quantity=delta, security_name=name, price=price,
                gross=abs(delta * price).quantize(fr_decimal("0,01")),
            )
        )
    return movements
