# statement-parser

Regex-only parser for broker and bank statements — no LLM, no API keys.
Reads PDF statements (via `pdfplumber`, keeping each word's position),
CSV exports and XLSX workbooks (via `openpyxl`), and returns typed
`StatementDocument`s: movements, cash balances and positions, with every
amount as a `Decimal`.

It knows nothing about any portfolio tool; mapping movements onto your own
ledger is the caller's job.

## Install

```bash
pip install "statement-parser @ git+https://github.com/toseg1/statement-parser.git@v0.2.0"
```

## Usage

```python
from statement_parser import parse_file, parse_statement, parse_statements

doc = parse_statement("Releve-compte-31-08-2026.pdf")
doc.doc_type          # "boursobank_releve_compte"
doc.account_ref       # the IBAN printed on the statement
doc.check_balance()   # True: opening + movements == closing, to the cent
for m in doc.movements:
    m.date, m.label, m.amount   # amount is signed: credit > 0, debit < 0

accounts = parse_file("comptes.xlsx")   # always a list: one StatementDocument per account

docs, errors = parse_statements("statements/")   # recursive; one bad file never hides the others
```

A multi-account file (e.g. XLSX export) gives one document
per account: use `parse_file` or `parse_statements` for it.
`parse_statement` expects a file that holds a single document, and raises
`ValueError` otherwise.

Every attribute of `StatementDocument`, `Movement`, `CashBalance` and
`Position`, and which ones each document type fills: see
[docs/api.md](docs/api.md).

```bash
statement-parser statements/              # one summary line per document
statement-parser statements/ --json       # full JSON to stdout
```

## Safety net

Any document that prints an opening and closing balance must reconcile:
opening + Σ movements == closing, to the cent. Otherwise `parse_statement`
raises `StatementParseError` (pass `strict=False` to inspect the partial
result). A regex that misses a line, or reads a debit as a credit, can't
slip through silently.

## Supported documents

| `doc_type` | Document |
| --- | --- |
| `trade_republic_csv` | Trade Republic transaction export (CSV) |
| `boursobank_avis_opere` | BoursoBank *Avis d'opéré*: fund subscription/redemption (ISIN, units, NAV, charges) |
| `boursobank_releve_especes` | BoursoBank *Relevé compte espèces* (PEA/CTO cash statement) |
| `boursobank_releve_compte` | BoursoBank *Extrait de compte* (current account, LDDS, Livret A…) |
| `cm_av_arbitrage` | Crédit Mutuel / ACM Vie *Opération d'arbitrage* (managed life-insurance switch: positions before/after) |
| `bourso_vie_arbitrage` | Bourso Vie (Generali) *Arbitrage* letter (life-insurance switch with ISINs, plus the holdings after it) |
| `cm_xlsx_comptes` | Crédit Mutuel `comptes.xlsx` export: every account in the workbook, one document each |

Detection uses a text fingerprint on the document itself, never the file
name.

## Adding a document type

Add a module under `src/statement_parser/parsers/` exposing `DOC_TYPE`,
`BROKER`, `detect(doc)` and `parse(doc)`, register it in
`parsers/__init__.py`, and add a test built from **synthetic** fixtures
(`tests/builders.py` lays out positioned lines for column-based PDFs, and
builds in-memory workbooks with `workbook_doc`). `parse` returns a
`StatementDocument`, or a list of them when one file holds several
accounts. Never commit a real statement: `*.pdf` and `*.xlsx` are
gitignored outside `tests/fixtures/`.
