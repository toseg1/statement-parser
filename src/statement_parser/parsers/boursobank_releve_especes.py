"""BoursoBank "Relevé compte espèces" — the monthly cash statement of a
PEA / CTO securities account: opening and closing balance, cash
transfers in and out, and one line per order (with units and a
*truncated* security name — the matching Avis d'opéré has the ISIN)."""

import re

from ..models import CashBalance, Movement, StatementDocument
from ..text import DATE, FR_NUMBER, fr_date, fr_decimal
from . import _columns

DOC_TYPE = "boursobank_releve_especes"
BROKER = "BoursoBank"

ACCOUNT_RE = re.compile(r"Références de votre compte espèces\s+(\d{5} \d{5} \d{11}) Compte (\S+)")
EXTRACT_DATE_RE = re.compile(rf"Extrait au {DATE}")
ORDER_RE = re.compile(
    rf"^(SOUSCRIPTION D'OPC|RACHAT D'OPC|ACHAT COMPTANT|VENTE COMPTANT|ACHAT|VENTE)"
    rf"\s+({FR_NUMBER}|\d+)\s+(.+)$"
)
SELLS = ("RACHAT", "VENTE")


def detect(doc):
    return "RELEVE COMPTE ESPECES" in doc.text and "Boursorama" in doc.text


def parse(doc):
    result = StatementDocument(source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE)
    account = ACCOUNT_RE.search(doc.text)
    if account:
        result.account_ref, result.account_label = account.group(1), account.group(2)
    extract = EXTRACT_DATE_RE.search(doc.text)
    if extract:
        result.period_end = fr_date(extract.group(1))

    for row in _columns.rows(doc):
        if not row.words or row.amount is None:
            continue
        when = fr_date(row.words[0].text)
        label = " ".join(w.text for w in row.words[1:])
        if label.startswith("ANCIEN SOLDE"):
            result.balances.append(CashBalance(when, row.amount, "opening"))
            result.period_start = when
            continue
        if label.startswith("NOUVEAU SOLDE"):
            result.balances.append(CashBalance(when, row.amount, "closing"))
            result.period_end = result.period_end or when
            continue

        movement = Movement(
            date=when, label=label, amount=row.amount, kind=label.split()[0],
            details=row.details, page=row.page, line_no=row.line_no,
        )
        order = ORDER_RE.match(label)
        if order:
            quantity = fr_decimal(order.group(2)) if "," in order.group(2) else int(order.group(2))
            movement.kind = "REDEMPTION" if order.group(1).startswith(SELLS) else "SUBSCRIPTION"
            movement.quantity = -quantity if movement.kind == "REDEMPTION" else quantity
            movement.security_name = order.group(3).strip()
            movement.gross = abs(row.amount)
        result.movements.append(movement)

    if result.check_balance() is False:
        result.warnings.append("opening balance + movements != closing balance")
    return result
