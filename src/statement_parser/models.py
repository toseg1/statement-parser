"""Typed records a parser returns. Amounts are Decimal, never float.

Sign convention: `Movement.amount` is the signed *net* cash effect on the
account the document is about (credit > 0, debit < 0). `gross`, `fee`
and `tax` are the positive magnitudes the document shows, when it shows
them separately. A movement with no cash effect (a security received for
free, a switch inside an insurance contract) has amount == 0, except
Trade Republic crypto deliveries, whose amount is in coin units with the
coin symbol as currency.

`currency` on every record is the one the document prints; the "EUR"
defaults below only stand when a document states none.
"""

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

ZERO = Decimal("0")


@dataclass
class Movement:
    date: date
    label: str
    amount: Decimal
    currency: str = "EUR"
    kind: Optional[str] = None  # parser-level type, e.g. "SUBSCRIPTION", TR "BUY"
    value_date: Optional[date] = None
    details: list = field(default_factory=list)  # continuation lines, as printed
    quantity: Optional[Decimal] = None  # signed: > 0 received, < 0 delivered
    isin: Optional[str] = None
    security_name: Optional[str] = None
    price: Optional[Decimal] = None
    gross: Optional[Decimal] = None
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    reference: Optional[str] = None
    extra: dict = field(default_factory=dict)  # source-specific raw fields
    page: Optional[int] = None
    line_no: Optional[int] = None


@dataclass
class CashBalance:
    as_of: date
    balance: Decimal
    kind: str  # "opening" | "closing"
    currency: str = "EUR"


@dataclass
class Position:
    as_of: date
    security_name: str
    value: Decimal
    quantity: Optional[Decimal] = None  # None for a unitless euro fund
    price: Optional[Decimal] = None
    isin: Optional[str] = None
    currency: str = "EUR"
    section: Optional[str] = None  # heading the row sat under
    snapshot: str = "closing"  # "before" | "after" | "closing"


@dataclass
class StatementDocument:
    source_file: str
    broker: str
    doc_type: str
    account_ref: Optional[str] = None  # account number / IBAN / contract number as printed
    account_label: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: str = "EUR"
    movements: list = field(default_factory=list)
    balances: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def balance(self, kind):
        return next((b for b in self.balances if b.kind == kind), None)

    def check_balance(self):
        """opening + sum(movements) == closing, to the cent. Returns None
        when the document doesn't print both balances (nothing to check)."""
        opening, closing = self.balance("opening"), self.balance("closing")
        if opening is None or closing is None:
            return None
        return opening.balance + sum((m.amount for m in self.movements), ZERO) == closing.balance

    def to_dict(self):
        return dataclasses.asdict(self)

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=_json_default)


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


class StatementParseError(Exception):
    """The document was recognized but could not be parsed reliably —
    e.g. its balances don't chain. Never swallowed into a partial result."""
