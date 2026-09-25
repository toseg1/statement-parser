"""Synthetic documents for tests — no real statement ever enters this repo.

`positioned_pdf` lays lines out the way BoursoBank's PDFs do: label words
from the left margin, and each amount right-aligned under its Débit or
Crédit column header (right edges measured on real statements: debit
amounts end at x~479 under a "Débit" header ending at x~465, credits at
x~546 under "Crédit" ending at x~533).
"""

from statement_parser.text import Line, RawDocument, Word

DEBIT_RIGHT, CREDIT_RIGHT = 479.5, 546.0
HEADER = [("Date", 46, 66), ("Libellé", 100, 125), ("Valeur", 380, 405),
          ("Débit", 442, 465), ("Crédit", 506, 533)]
CHAR_WIDTH = 5.0


def _words(text, x=46.0):
    words = []
    for token in text.split():
        width = CHAR_WIDTH * len(token)
        words.append(Word(x, x + width, token))
        x += width + CHAR_WIDTH
    return words


def line(text, debit=None, credit=None, top=0.0):
    words = _words(text)
    if debit is not None:
        words.append(Word(DEBIT_RIGHT - CHAR_WIDTH * len(debit), DEBIT_RIGHT, debit))
    if credit is not None:
        words.append(Word(CREDIT_RIGHT - CHAR_WIDTH * len(credit), CREDIT_RIGHT, credit))
    return Line(top, words)


def header_line():
    return Line(0.0, [Word(x0, x1, t) for t, x0, x1 in HEADER])


def positioned_pdf(pages, preamble="", path="synthetic.pdf"):
    """pages: list of lists of Line (header_line() included where the
    real document has one). `preamble` is extra plain text prepended to
    doc.text for detection/metadata regexes."""
    text = "\n".join([preamble, *(ln.text for page in pages for ln in page)])
    return RawDocument(path, text, pages=pages)


def text_doc(text, path="synthetic.pdf"):
    return RawDocument(path, text, pages=[])


def workbook_doc(sheets, path="synthetic.xlsx"):
    """sheets: {name: list of rows}, cell values as load_document gives
    them (str, Decimal, date or None)."""
    from statement_parser.text import sheets_text

    return RawDocument(path, sheets_text(sheets), sheets=sheets)
