"""Row extraction for statements whose debit and credit amounts sit in
two columns told apart only by x position (BoursoBank)."""

import re
from dataclasses import dataclass, field

from ..text import DATE, FR_AMOUNT, classify_amount, column_edges, fr_decimal

HEADER_LABELS = {"debit": r"Débit", "credit": r"Crédit"}
DATE_START = re.compile(rf"^{DATE}\b")


@dataclass
class Row:
    page: int
    line_no: int
    words: list  # label words, amount removed
    amount: object  # signed Decimal: credit > 0, debit < 0 — None if no amount found
    details: list = field(default_factory=list)

    @property
    def text(self):
        return " ".join(w.text for w in self.words)


def signed_amount(line, edges):
    """(signed amount, remaining words) for the line's debit/credit
    amount, or (None, words) when it has none in those columns."""
    for i in range(len(line.words) - 1, -1, -1):
        word = line.words[i]
        if not re.fullmatch(FR_AMOUNT, word.text):
            continue
        column = classify_amount(word, edges)
        if column is None:
            continue
        value = fr_decimal(word.text)
        rest = line.words[:i] + line.words[i + 1:]
        return (value if column == "credit" else -value), rest
    return None, line.words


def rows(doc, stop=None):
    """Every line from the Débit/Crédit header down to `stop` (a regex on
    the line text) on each page, as Rows. Lines not starting with a date
    are continuation lines and go to the previous row's `details`."""
    out = []
    for page_no, lines in enumerate(doc.pages, start=1):
        edges = None
        for line_no, line in enumerate(lines, start=1):
            text = line.text
            if edges is None:
                found = column_edges(line, HEADER_LABELS)
                if len(found) == 2:
                    edges = found
                continue
            if stop is not None and re.search(stop, text):
                break
            amount, rest = signed_amount(line, edges)
            if DATE_START.match(text) or amount is not None:
                out.append(Row(page_no, line_no, rest, amount))
            elif out and out[-1].page == page_no:
                out[-1].details.append(text)
    return out
