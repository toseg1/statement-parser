"""BoursoBank "Avis d'opéré" for a fund order (OPERATION SUR OPC):
one subscription or redemption, with ISIN, units, NAV, and the
gross -> charges -> net breakdown."""

import re
from decimal import Decimal

from ..models import ZERO, Movement, StatementDocument
from ..text import DATE, FR_AMOUNT, FR_NUMBER, fr_date, fr_decimal

DOC_TYPE = "boursobank_avis_opere"
BROKER = "BoursoBank"

OPERATION_RE = re.compile(r"^(SOUSCRIPTION|RACHAT)\b.*$", re.M)
ACCOUNT_RE = re.compile(r"Références de votre compte titres\s+(\d{5} \d{5} \d{11}) Compte (.+)")
EXECUTION_RE = re.compile(
    rf"^{DATE} ({FR_NUMBER}) (.+?) Référence : (\d+)\s*$", re.M
)
ISIN_RE = re.compile(r"Code ISIN : ([A-Z]{2}[A-Z0-9]{9}\d)")
NAV_RE = re.compile(rf"Valeur liquidative : ({FR_NUMBER}) ([A-Z]{{3}})")
AMOUNTS_RE = re.compile(rf"Montant brut.*?\n((?:{FR_AMOUNT} [A-Z]{{3}}\s*)+)")
# NAV is printed to 2 decimals and units to 5: allow a cent, or 0.1%.
RECONCILE_ABS = Decimal("0.02")
RECONCILE_REL = Decimal("0.001")


def detect(doc):
    return "OPERATION SUR OPC" in doc.text and "Code ISIN" in doc.text and "Boursorama" in doc.text


def parse(doc):
    text = doc.text
    result = StatementDocument(source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE)

    account = ACCOUNT_RE.search(text)
    if account:
        result.account_ref = account.group(1)
        result.account_label = account.group(2).strip()

    operation = OPERATION_RE.search(text)
    execution = EXECUTION_RE.search(text)
    isin = ISIN_RE.search(text)
    nav = NAV_RE.search(text)
    amounts = AMOUNTS_RE.search(text)
    missing = [n for n, m in (("operation", operation), ("execution line", execution),
                              ("ISIN", isin), ("NAV", nav), ("amounts", amounts)) if m is None]
    if missing:
        result.warnings.append(f"could not find: {', '.join(missing)}")
        return result

    values = [fr_decimal(v) for v in re.findall(FR_AMOUNT, amounts.group(1))]
    # Montant brut | Droits d'entrée | Frais H.T. | [T.V.A.] | Montant net —
    # T.V.A. is left blank when zero, so 4 or 5 figures.
    gross, net = values[0], values[-1]
    charges = sum(values[1:-1], ZERO)

    is_redemption = operation.group(1) == "RACHAT"
    quantity = fr_decimal(execution.group(2))
    price = fr_decimal(nav.group(1))
    if abs(quantity * price - gross) > max(RECONCILE_ABS, gross * RECONCILE_REL):
        result.warnings.append(
            f"quantity x NAV = {quantity * price:.2f} does not reconcile with gross {gross}"
        )

    trade_date = fr_date(execution.group(1))
    result.period_start = result.period_end = trade_date
    result.movements.append(
        Movement(
            date=trade_date,
            label=operation.group(0).strip(),
            amount=net if is_redemption else -net,
            currency=nav.group(2),
            kind="REDEMPTION" if is_redemption else "SUBSCRIPTION",
            quantity=-quantity if is_redemption else quantity,
            isin=isin.group(1),
            security_name=re.sub(r"\s+(FCP|SICAV|FCPE)\b.*$", "", execution.group(3)).strip(),
            price=price,
            gross=gross,
            fee=charges,
            reference=execution.group(4),
        )
    )
    return result

