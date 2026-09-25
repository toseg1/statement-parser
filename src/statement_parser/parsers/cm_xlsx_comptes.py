"""Crédit Mutuel "comptes.xlsx" export (web banking -> Télécharger ->
Excel): one workbook for several accounts. A "Vos comptes" summary sheet
lists every account with its RIB and balance, and each account whose
movements were exported gets its own "Cpt <guichet> <compte>" sheet:
Date | Valeur | Libellé | Débit | Crédit | Solde | Dev, closed by a
"Solde au DD/MM/YYYY" row.

Returns one StatementDocument per account. The opening balance ("Solde
initial") and the running "Solde" column are formulas the export leaves
uncomputed, so only the closing balance is known: check_balance() is
None, and the closing balance is cross-checked against the summary
instead. An account listed in the summary without a sheet of its own (a
loan, typically) comes back with its balance and no movements.
"""

import re
from datetime import date
from decimal import Decimal

from ..models import CashBalance, Movement, StatementDocument
from ..text import DATE, fr_date

DOC_TYPE = "cm_xlsx_comptes"
BROKER = "Crédit Mutuel"

SUMMARY_SHEET = "Vos comptes"
SUMMARY_TITLE_RE = re.compile(rf"^Votre situation financière au {DATE}")
TITLE_RE = re.compile(rf"^Situation de votre compte (.+) \(([A-Z]{{3}})\) au {DATE}$")
RIB_RE = re.compile(r"^R\.I\.B\. : (\d[\d ]*\d)")
CLOSING_RE = re.compile(rf"^Solde au {DATE}")
CENT = Decimal("0.01")


def detect(doc):
    return (
        doc.sheets is not None
        and SUMMARY_SHEET in doc.sheets
        and "Situation de votre compte" in doc.text
    )


def _key(rib):
    return rib.replace(" ", "")


def _strings(row):
    return [v for v in row if isinstance(v, str)]


def _header(rows, required):
    """(row index, {column name: column index}) of the first row holding
    every `required` column name."""
    for i, row in enumerate(rows):
        columns = {v.strip(): j for j, v in enumerate(row) if isinstance(v, str)}
        if required <= set(columns):
            return i, columns
    return None, {}


def _cell(row, columns, name):
    j = columns.get(name)
    return row[j] if j is not None and j < len(row) else None


def _money(row, columns, name):
    """An amount cell to the cent (the export stores 652.4, not 652.40)."""
    value = _cell(row, columns, name)
    return value.quantize(CENT) if isinstance(value, Decimal) else None


def _date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(DATE, value.strip()):
        return fr_date(value.strip())
    return None


def _summary(rows):
    """(as-of date, {RIB key: (label, rib, balance, currency)}) from the
    "Vos comptes" sheet, in listing order."""
    as_of = next(
        (fr_date(m.group(1)) for row in rows for v in _strings(row) if (m := SUMMARY_TITLE_RE.match(v))),
        None,
    )
    start, columns = _header(rows, {"Compte", "R.I.B.", "Solde"})
    accounts = {}
    if start is None:
        return as_of, accounts
    for row in rows[start + 1:]:
        label, rib = _cell(row, columns, "Compte"), _cell(row, columns, "R.I.B.")
        if not isinstance(label, str) or not isinstance(rib, str):
            continue
        accounts[_key(rib)] = (label.strip(), rib.strip(), _money(row, columns, "Solde"),
                               _cell(row, columns, "Dev") or "EUR")
    return as_of, accounts


def _account(doc, name, rows):
    """The StatementDocument for one account sheet, or None if the sheet
    isn't one."""
    title = next((m for row in rows[:3] for v in _strings(row) if (m := TITLE_RE.match(v.strip()))), None)
    if title is None:
        return None
    result = StatementDocument(
        source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE,
        account_label=title.group(1).strip(), currency=title.group(2),
    )
    rib = next((m for row in rows[:4] for v in _strings(row) if (m := RIB_RE.match(v.strip()))), None)
    if rib:
        result.account_ref = rib.group(1)

    start, columns = _header(rows, {"Date", "Libellé", "Débit", "Crédit"})
    if start is None:
        result.warnings.append(f"{name}: no Date/Libellé/Débit/Crédit header row")
        return result
    for row_no, row in enumerate(rows[start + 1:], start=start + 2):
        closing = next((m for v in _strings(row) if (m := CLOSING_RE.match(v.strip()))), None)
        if closing:
            balance = _money(row, columns, "Solde")
            if balance is None:
                result.warnings.append(f"{name}: closing balance row has no amount")
            else:
                result.balances.append(CashBalance(fr_date(closing.group(1)), balance, "closing",
                                                   currency=result.currency))
            result.period_end = fr_date(closing.group(1))
            break
        when = _date(_cell(row, columns, "Date"))
        if when is None:
            continue
        debit, credit = _money(row, columns, "Débit"), _money(row, columns, "Crédit")
        if (debit is None) == (credit is None):
            result.warnings.append(f"{name} row {row_no}: expected exactly one of Débit / Crédit")
            continue
        if (debit is not None and debit > 0) or (credit is not None and credit < 0):
            result.warnings.append(f"{name} row {row_no}: Débit printed positive or Crédit negative")
        label = str(_cell(row, columns, "Libellé") or "").strip()
        result.movements.append(
            Movement(
                date=when, label=label, amount=debit if debit is not None else credit,
                currency=_cell(row, columns, "Dev") or result.currency,
                kind=label.split()[0] if label else None,
                value_date=_date(_cell(row, columns, "Valeur")),
                line_no=row_no, extra={"sheet": name},
            )
        )
    else:
        result.warnings.append(f"{name}: no 'Solde au' closing row")

    if result.movements:
        result.period_start = min(m.date for m in result.movements)
    return result


def parse(doc):
    as_of, summary = _summary(doc.sheets[SUMMARY_SHEET])
    documents = {}
    for name, rows in doc.sheets.items():
        if name == SUMMARY_SHEET:
            continue
        account = _account(doc, name, rows)
        if account is not None:
            documents[_key(account.account_ref or name)] = account

    results = []
    for key, (label, rib, balance, currency) in summary.items():
        account = documents.pop(key, None)
        if account is None:  # listed, but no movements exported (e.g. a loan)
            account = StatementDocument(
                source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE,
                account_ref=rib, account_label=label, currency=currency,
                period_end=as_of,
            )
            if balance is not None and as_of is not None:
                account.balances.append(CashBalance(as_of, balance, "closing", currency=currency))
            else:
                account.warnings.append("summary gives no balance or date for this account")
        else:
            closing = account.balance("closing")
            if balance is not None and closing is not None and closing.balance != balance:
                account.warnings.append(
                    f"closing balance {closing.balance} != 'Vos comptes' balance {balance}"
                )
        results.append(account)
    for account in documents.values():  # a sheet the summary doesn't list
        account.warnings.append("account not listed in 'Vos comptes'")
        results.append(account)
    return results
