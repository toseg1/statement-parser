"""BoursoBank "Extrait de votre compte" — the monthly statement of a bank
account (current account, LDDS, Livret A...). Multi-line entries: the
first line has date, label, value date and amount; any following lines
(counterparty, reference, FX rate) belong to it."""

import re

from ..models import CashBalance, Movement, StatementDocument
from ..text import DATE, FR_AMOUNT, classify_amount, fr_date, fr_decimal
from . import _columns

DOC_TYPE = "boursobank_releve_compte"
BROKER = "BoursoBank"

IBAN_RE = re.compile(r"I\.B\.A\.N\.\s*(FR[\d ]{20,40}\d)")
PERIOD_RE = re.compile(rf"du {DATE} ?au {DATE}")
LABEL_RE = re.compile(r"Compte d'épargne ?: ?(.+)")
OPENING_RE = re.compile(rf"SOLDE ?AU ?: ?{DATE}")
CLOSING_RE = re.compile(r"Nouveau ?solde ?en ?EUR")
# "Réf" comes out as "Rèf": the statement font's glyph mapping is lossy
REFERENCE_RE = re.compile(r"R[éèe]f ?: ?(\S+)")
# The footer that closes the movements table on every page
STOP = r"^A réception|^A défaut|^\* Montant"
VALUE_DATE_END = re.compile(rf"\s{DATE}$")


def detect(doc):
    return "MOUVEMENTS EN EUR" in doc.text and "Extrait de votre compte" in doc.text


def _closing_amount(doc):
    """"Nouveau solde en EUR :" — its amount is sometimes a couple of
    points off the label's baseline, so look on the nearest line too."""
    for lines in doc.pages:
        edges = None
        for i, line in enumerate(lines):
            if edges is None:
                found = _columns.column_edges(line, _columns.HEADER_LABELS)
                edges = found if len(found) == 2 else None
            if edges and CLOSING_RE.search(line.text):
                for candidate in lines[i:i + 2]:
                    for word in reversed(candidate.words):
                        if re.fullmatch(FR_AMOUNT, word.text):
                            column = classify_amount(word, edges)
                            if column:
                                value = fr_decimal(word.text)
                                return value if column == "credit" else -value
    return None


def parse(doc):
    result = StatementDocument(source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE)
    iban = IBAN_RE.search(doc.text)
    if iban:
        result.account_ref = iban.group(1).replace(" ", "")
    label = LABEL_RE.search(doc.text)
    result.account_label = label.group(1).strip() if label else "Compte courant"
    period = PERIOD_RE.search(doc.text)
    if period:
        result.period_start, result.period_end = fr_date(period.group(1)), fr_date(period.group(2))

    for row in _columns.rows(doc, stop=STOP):
        text = row.text
        opening = OPENING_RE.search(text)
        if opening and row.amount is not None:
            result.balances.append(CashBalance(fr_date(opening.group(1)), row.amount, "opening"))
            continue
        if CLOSING_RE.search(text) or row.amount is None or not _columns.DATE_START.match(text):
            continue

        when = fr_date(row.words[0].text)
        rest = " ".join(w.text for w in row.words[1:])
        value_date = None
        vd = VALUE_DATE_END.search(rest)
        if vd:
            value_date = fr_date(vd.group(1))
            rest = rest[:vd.start()].strip()
        reference = next((m.group(1) for d in row.details if (m := REFERENCE_RE.search(d))), None)
        result.movements.append(
            Movement(
                date=when, label=rest, amount=row.amount, kind=rest.split()[0] if rest else None,
                value_date=value_date, details=row.details, reference=reference,
                page=row.page, line_no=row.line_no,
            )
        )

    closing = _closing_amount(doc)
    if closing is not None and result.period_end:
        result.balances.append(CashBalance(result.period_end, closing, "closing"))
    if result.check_balance() is False:
        result.warnings.append("opening balance + movements != closing balance")
    return result
