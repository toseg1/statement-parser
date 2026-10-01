# API reference

Everything `parse_statement` / `parse_file` / `parse_statements` return,
and which fields each document type fills.

```python
from statement_parser import parse_file, parse_statement, parse_statements

doc = parse_statement(path, strict=True)            # -> StatementDocument
docs = parse_file(path, strict=True)                # -> list[StatementDocument]
docs, errors = parse_statements(paths, strict=True) # -> (list[StatementDocument], list[str])
```

## Entry points

### `parse_statement(path, strict=True)`

Parses one `.pdf`, `.csv` or `.xlsx` file and returns its
`StatementDocument`.

Raises `StatementParseError` when:

- no parser recognizes the document;
- `strict=True` and the document prints both an opening and a closing
  balance that don't reconcile (`doc.check_balance() is False`).

With `strict=False`, a mismatched document is returned anyway, with a
line in `doc.warnings` explaining what failed.

Raises `ValueError` when more than one parser matches the document, or
when the file holds several accounts (a `cm_xlsx_comptes` workbook). Use
`parse_file` for those.

### `parse_file(path, strict=True)`

Same as `parse_statement`, but always returns a
`list[StatementDocument]`. The list has one entry for a single statement,
and one per account for a multi-account file. With `strict=True`, every
document in the file must pass the balance check.

### `parse_statements(paths, strict=True)`

`paths` can be a directory, a file, or an iterable of directories and
files. Directories are searched recursively for `.pdf`, `.csv` and
`.xlsx` files (case-insensitive), in sorted order. Excel lock files
(`~$…`) are skipped.

Returns a `(documents, errors)` tuple:

- `documents`: `list[StatementDocument]` for every file that parsed, with
  one entry per account for a multi-account file;
- `errors`: `list[str]`, one message per file that raised
  `StatementParseError` or `ValueError`. Each message starts with the file
  name.

Other exceptions still propagate, such as a missing file or a PDF that
`pdfplumber` can't open.

### `parse_document(raw_doc, strict=True)`

Same as `parse_statement`, but takes a `RawDocument` that is already
loaded (see `statement_parser.text.load_document`). Use it to parse
in-memory content or to test with synthetic documents. It returns
whatever the parser returns: a `StatementDocument`, or a list of them for
a multi-account document.

## `StatementDocument`

| Attribute | Type | Meaning |
| --- | --- | --- |
| `source_file` | `str` | Path of the parsed file (shared by every account of a multi-account file) |
| `broker` | `str` | `"Trade Republic"`, `"BoursoBank"`, `"Bourso Vie"`, `"Crédit Mutuel"` |
| `doc_type` | `str` | Parser that handled it (see [per-type fields](#fields-by-document-type)) |
| `account_ref` | `str \| None` | Account number, IBAN or contract number, as printed |
| `account_label` | `str \| None` | Account or contract name (`"PEA"`, `"Livret A"`, …) |
| `period_start` | `date \| None` | First day the document covers |
| `period_end` | `date \| None` | Last day the document covers |
| `currency` | `str` | Account currency as printed on the document (ISO code, e.g. `"EUR"`) |
| `movements` | `list[Movement]` | Cash / security movements, in document order |
| `balances` | `list[CashBalance]` | Opening and/or closing balances, when printed |
| `positions` | `list[Position]` | Holdings snapshots, when printed |
| `warnings` | `list[str]` | Non-fatal issues: missing fields, sums that don't add up |

### Methods

| Method | Returns |
| --- | --- |
| `doc.balance("opening")` / `doc.balance("closing")` | The matching `CashBalance`, or `None` |
| `doc.check_balance()` | `True` if opening + Σ `movement.amount` == closing, to the cent; `False` if not; `None` if the document doesn't print both balances |
| `doc.to_dict()` | Nested plain dict (`Decimal` and `date` kept as-is) |
| `doc.to_json(indent=2)` | JSON string; `Decimal` → string (`"12.50"`), `date` → ISO string (`"2026-08-31"`) |

## `Movement`

One line of the statement: a transfer, a card payment, a fund order, a
switch…

**Sign convention:** `amount` is the signed **net** cash effect on the
account the document is about (credit > 0, debit < 0). `gross`, `fee`
and `tax` are **positive** magnitudes. A movement with no cash effect
(e.g. a switch inside a life-insurance contract) has `amount == 0`.

| Attribute | Type | Meaning |
| --- | --- | --- |
| `date` | `date` | Operation date |
| `label` | `str` | Main label, as printed |
| `amount` | `Decimal` | Signed net cash effect |
| `currency` | `str` | As printed on the document; `"EUR"` only when it states none |
| `kind` | `str \| None` | Movement type assigned by the parser (see per-type table) |
| `value_date` | `date \| None` | Value date, when printed |
| `details` | `list[str]` | Continuation lines under the label (counterparty, reference, FX…) |
| `quantity` | `Decimal \| int \| None` | Units, signed: > 0 received, < 0 delivered |
| `isin` | `str \| None` | ISIN of the security |
| `security_name` | `str \| None` | Security / fund name |
| `price` | `Decimal \| None` | Unit price or NAV |
| `gross` | `Decimal \| None` | Gross amount, before fees and taxes |
| `fee` | `Decimal` | Fees, positive; `0` when not shown |
| `tax` | `Decimal` | Taxes, positive; `0` when not shown |
| `reference` | `str \| None` | Transaction / order reference |
| `extra` | `dict` | Fields specific to the source (see per-type table) |
| `page` | `int \| None` | PDF page the line was on |
| `line_no` | `int \| None` | Line number within the page, or the CSV line number |

## `CashBalance`

| Attribute | Type | Meaning |
| --- | --- | --- |
| `as_of` | `date` | Balance date |
| `balance` | `Decimal` | Signed balance |
| `kind` | `str` | `"opening"` or `"closing"` |
| `currency` | `str` | As printed on the document; `"EUR"` only when it states none |

## `Position`

| Attribute | Type | Meaning |
| --- | --- | --- |
| `as_of` | `date` | Valuation date |
| `security_name` | `str` | Fund / security name |
| `value` | `Decimal` | Value in currency |
| `quantity` | `Decimal \| None` | Units; `None` for a unitless euro fund |
| `price` | `Decimal \| None` | Unit price / NAV |
| `isin` | `str \| None` | ISIN, when printed |
| `currency` | `str` | As printed on the document; `"EUR"` only when it states none |
| `section` | `str \| None` | Heading the row was listed under |
| `snapshot` | `str` | `"before"`, `"after"` or `"closing"` |

## Fields by document type

Each parser fills only what its document prints. Any field not listed
here keeps its default (`None`, `0`, `[]` or `{}`).

### `trade_republic_csv`: Trade Republic CSV export

- **Document:** `account_ref = "TR"`, no `account_label`.
  `period_start`/`period_end` are the first and last movement dates.
  No balances, so `check_balance()` returns `None`. No positions.
- **Movements:** one per CSV row, sorted by `(date, line_no)`.
  - `kind`: TR's `type` column (`BUY`, `SELL`, `CARD_TRANSACTION`,
    `CARD_ORDERING_FEE`, `DELIVERY_OUTBOUND`, `TRANSFER_OUT`, …).
  - `amount` = TR amount + fee + tax, i.e. the net cash effect.
    Exception: a `CRYPTO` row with an empty TR amount (e.g. `FREE_RECEIPT`)
    gets `amount` = signed shares and `currency` = the coin symbol (`"SOL"`).
    Filter on `currency` before summing amounts.
  - `gross` = |TR amount|, or `None` when it is 0. `fee`, `tax` are filled.
  - `quantity`, `security_name`, `price`, `currency` come from the
    corresponding columns. `quantity` is negative for `SELL`,
    `DELIVERY_OUTBOUND` and `TRANSFER_OUT`.
  - `isin`: the `symbol` column, when it is a valid ISIN.
  - `reference`: TR's `transaction_id`, stable across exports, so you can
    use it to dedupe.
  - `line_no`: CSV line number (the header is line 1).
  - `extra`: `category`, `account_type`, `asset_class`, `symbol`,
    `counterparty_name`, `counterparty_iban`, `original_amount`,
    `original_currency` (raw strings; `""` when empty).

### `boursobank_avis_opere`: BoursoBank *Avis d'opéré* (fund order)

- **Document:** `account_ref` is the securities account number
  (`"00000 00000 00000000000"`), and `account_label` is the account type.
  `period_start == period_end ==` trade date. No balances, no positions.
- **Movements:** exactly one.
  - `kind`: `"SUBSCRIPTION"` or `"REDEMPTION"`.
  - `amount`: −net for a subscription, +net for a redemption.
  - `quantity` (signed), `isin`, `security_name` (with the `FCP`/`SICAV`
    suffix removed), `price` (NAV), `currency` (the NAV currency), `gross`,
    `reference` (order reference).
  - `fee`: all charges combined (entry fees + fees excl. VAT + VAT).
- **Warnings:** if a required block can't be found, `movements` is empty
  and `warnings` says what is missing. There are no balances to check, so
  this does **not** raise even in strict mode, and you should check
  `doc.warnings`. A warning is also added when quantity × NAV doesn't
  match the gross amount.

### `boursobank_releve_especes`: BoursoBank cash statement (PEA/CTO)

- **Document:** `account_ref` (account number), `account_label`
  (e.g. `"PEA"`). `period_start` = opening-balance date;
  `period_end` = "Extrait au" date (or closing-balance date).
- **Balances:** `opening` and `closing`, so the document is reconciled.
- **Movements:** one per table line.
  - `details`, `page`, `line_no` always filled.
  - `kind`: first word of the label, except for fund / stock orders.
  - Orders (`SOUSCRIPTION D'OPC`, `RACHAT D'OPC`, `ACHAT [COMPTANT]`,
    `VENTE [COMPTANT]`): `kind` becomes `"SUBSCRIPTION"` / `"REDEMPTION"`,
    with `quantity` (signed), `security_name` (**truncated** as printed,
    and no ISIN; the matching *Avis d'opéré* has both), and `gross`.

### `boursobank_releve_compte`: BoursoBank bank account statement

- **Document:** `account_ref` is the IBAN without spaces. `account_label` is
  the savings account name (`"Livret A"`, `"LDDS"`…), or
  `"Compte courant"`. `period_start`/`period_end` come from "du … au …".
  `currency` comes from "MOUVEMENTS EN …" (`EUR`, `USD`…) and is carried
  by every movement and balance.
- **Balances:** `opening` and `closing` (the closing one is dated
  `period_end`), so the document is reconciled.
- **Movements:** one per entry.
  - `kind`: first word of the label (e.g. `VIR`, `PRLV`, `CARTE`).
  - `value_date`, `details` (counterparty, reference and FX lines as
    printed), `page`, `line_no`.
  - `reference`: taken from a `Réf :` line in `details`, when present.

### `cm_av_arbitrage`: Crédit Mutuel / ACM Vie arbitrage letter

- **Document:** `account_ref` is the contract number, and `account_label` is
  the contract name. `period_start == period_end ==` arbitrage date.
  No balances.
- **Positions:** the full allocation twice, with `snapshot="before"` and
  `snapshot="after"`. Each row has `security_name`, `value`, `quantity`,
  `price` and `section` (category heading). The euro fund row has
  `quantity=None` and `price=None`. No ISIN.
- **Movements:** derived from the before/after difference, one per fund
  that changed, always with `amount == 0` (the money stays inside the
  contract).
  - Unit funds: `kind` is `"SWITCH_IN"` / `"SWITCH_OUT"`, `quantity` is
    the unit delta, and `price` and `gross` (|Δunits × price|) are set.
  - Euro fund: `kind="SWITCH"`, `gross` = |value delta|, and
    `extra = {"value_delta": Decimal, "unitless": True}`.
- **Warnings:** a warning is added when a snapshot has no `TOTAL` line
  or its rows don't sum to it (±0.05).

### `bourso_vie_arbitrage`: Bourso Vie (Generali) arbitrage letter

- **Document:** `account_ref` is the contract number (`"Contrat n° …"`),
  `account_label = "Bourso Vie"`. `period_start == period_end ==` the
  operation date ("en date du …"). No balances.
- **Movements:** one per support listed under *Désinvestissement* or
  *Réinvestissement*, always with `amount == 0`. `date` is the operation
  date and `value_date` the valuation date ("Valeur au …").
  - Unit-linked funds: `kind` is `"SWITCH_OUT"` (sold) or `"SWITCH_IN"`
    (bought). `quantity` is signed, and `price`, `gross` (the value
    printed after "soit") and `isin` are set. `security_name` is printed
    as-is, without the leading `*` (e.g.
    `"Compartiment SICAV … -A-ACC"`).
  - Euro fund: `kind="SWITCH"`, `gross` = value, `quantity=None`, and
    `extra = {"value_delta": Decimal, "unitless": True}` (negative when
    sold). This is the same shape as `cm_av_arbitrage`.
- **Positions:** the *Valeur atteinte après arbitrage* page, with
  `snapshot="after"`. Each row has `isin`, `quantity`, `price`, `value`
  (the contre-valeur) and `section` (`"Unités de Compte"` /
  `"Fonds en Euros"`), dated with the NAV date.
- **Warnings:** added when the sold or bought supports don't sum to the
  "Arbitrage d'un montant de" figure, or when the positions don't sum to
  "Epargne atteinte totale". The tolerance is ±0.05.

### `cm_xlsx_comptes`: Crédit Mutuel `comptes.xlsx` export

One workbook, several accounts: `parse` returns **a list**, with one
document per account listed on the *Vos comptes* summary sheet, in that
order. Hidden sheets are ignored.

- **Document:** `account_ref` is the RIB as printed
  (`"00000 00000 00000000000"`), and `account_label` is the account name as
  printed (it includes the holder's name). `period_start` is the first
  movement date and `period_end` is the "Solde au" date.
- **Balances:** `closing` only. The export's opening balance and running
  *Solde* column are uncomputed formulas, so no opening balance is known,
  and `check_balance()` returns `None`. The closing balance is
  cross-checked against the *Vos comptes* summary instead.
- **Movements:** one per sheet row.
  - `date`, `value_date` (the *Valeur* column), `label` (*Libellé*) and
    `amount` (*Débit* is negative, *Crédit* positive, in cents).
  - `kind` is the first word of the label (`VIR`, `PAIEMENT`, `PRLV`, …).
  - `line_no` is the sheet row number, and `extra = {"sheet": <sheet name>}`.
- **Accounts without a sheet** (typically a loan, which the export lists
  on the summary only): a document with no movements and one `closing`
  balance, dated at the summary date. A loan's balance is negative.
- **Warnings:** added when the summary balance differs from the sheet's
  closing balance, when a row has both or neither of *Débit* / *Crédit*,
  when an amount has the wrong sign, when the "Solde au" row is missing,
  or when an account sheet isn't listed on the summary.

## Examples

```python
from collections import defaultdict
from statement_parser import parse_file, parse_statements

docs, errors = parse_statements("statements/")
for e in errors:
    print("skipped:", e)

# Everything that needs a look
for doc in docs:
    if doc.warnings:
        print(doc.source_file, doc.warnings)

# Net cash flow per account
flow = defaultdict(int)
for doc in docs:
    for m in doc.movements:
        flow[doc.account_ref] += m.amount

# All fund orders with their ISIN
orders = [
    (m.date, m.isin, m.quantity, m.price, m.fee)
    for doc in docs if doc.doc_type == "boursobank_avis_opere"
    for m in doc.movements
]

# Current allocation after the latest arbitrage
arb = max((d for d in docs if d.doc_type == "cm_av_arbitrage"), key=lambda d: d.period_end)
after = [p for p in arb.positions if p.snapshot == "after"]

# Latest balance of every Crédit Mutuel account (one workbook, several accounts)
balances = {
    d.account_ref: d.balance("closing").balance
    for d in parse_file("comptes.xlsx")
}

# Export
open("out.json", "w").write(docs[0].to_json())
```
