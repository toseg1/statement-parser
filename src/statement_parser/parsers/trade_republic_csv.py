"""Trade Republic "Exportation de transactions" CSV (app -> Profile ->
Transaction export). Structured already, so no regex beyond ISIN
detection: every row carries a stable transaction_id, signed amounts,
and a category/type pair (CASH/CARD_TRANSACTION, TRADING/BUY, ...).

TR prints fee and tax as negative numbers in their own columns, with the
row's `amount` excluding them (e.g. CARD_ORDERING_FEE: amount 0.00,
fee -5.00). Movement.amount is the net cash effect, amount + fee + tax.
Crypto rows with no amount (FREE_RECEIPT of SOL, ETH, ...) instead carry
the signed shares as amount, with the coin symbol as currency.
"""

import re
from datetime import date
from decimal import Decimal

from ..models import ZERO, Movement, StatementDocument

DOC_TYPE = "trade_republic_csv"
BROKER = "Trade Republic"
REQUIRED_COLUMNS = {"transaction_id", "category", "type", "amount", "date", "account_type"}
ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")


def detect(doc):
    return doc.rows is not None and REQUIRED_COLUMNS <= set(doc.text.split(","))


def _dec(value):
    value = (value or "").strip()
    return Decimal(value) if value else None


def parse(doc):
    result = StatementDocument(source_file=doc.path, broker=BROKER, doc_type=DOC_TYPE, account_ref="TR")
    for line_no, row in enumerate(doc.rows, start=2):  # line 1 is the header
        raw_amount = _dec(row["amount"])
        amount = raw_amount or ZERO
        fee = _dec(row.get("fee")) or ZERO
        tax = _dec(row.get("tax")) or ZERO
        shares = _dec(row.get("shares"))
        symbol = (row.get("symbol") or "").strip()
        kind = row["type"].strip()
        asset_class = row.get("asset_class", "").strip()
        currency = (row.get("currency") or "EUR").strip()

        quantity = None
        if shares is not None:
            # TR prints shares unsigned; direction follows the type.
            quantity = -shares if kind in {"SELL", "DELIVERY_OUTBOUND", "TRANSFER_OUT"} else shares

        net = amount + fee + tax
        if raw_amount is None and asset_class == "CRYPTO" and quantity is not None:
            # e.g. FREE_RECEIPT SOL: no cash amount, so count it in coin units.
            net = quantity
            currency = symbol or currency

        result.movements.append(
            Movement(
                date=date.fromisoformat(row["date"]),
                label=(row.get("description") or row.get("name") or kind).strip(),
                amount=net,
                currency=currency,
                kind=kind,
                quantity=quantity,
                isin=symbol if ISIN_RE.fullmatch(symbol) else None,
                security_name=(row.get("name") or "").strip() or None,
                price=_dec(row.get("price")),
                gross=abs(amount) if amount else None,
                fee=abs(fee),
                tax=abs(tax),
                reference=row["transaction_id"].strip(),
                extra={
                    "category": row.get("category", "").strip(),
                    "account_type": row.get("account_type", "").strip(),
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "counterparty_name": (row.get("counterparty_name") or "").strip(),
                    "counterparty_iban": (row.get("counterparty_iban") or "").strip(),
                    "original_amount": (row.get("original_amount") or "").strip(),
                    "original_currency": (row.get("original_currency") or "").strip(),
                },
                line_no=line_no,
            )
        )
    result.movements.sort(key=lambda m: (m.date, m.line_no))
    if result.movements:
        result.period_start = result.movements[0].date
        result.period_end = result.movements[-1].date
    return result
