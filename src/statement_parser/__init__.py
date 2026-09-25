"""statement-parser: regex-only parsing of broker/bank statements into
typed records (no LLM, no API keys)."""

from pathlib import Path

from .models import CashBalance, Movement, Position, StatementDocument, StatementParseError
from .parsers import PARSERS, find_parser
from .text import RawDocument, load_document

SUPPORTED_SUFFIXES = {".pdf", ".csv", ".xlsx"}

__all__ = [
    "CashBalance", "Movement", "Position", "StatementDocument", "StatementParseError",
    "PARSERS", "RawDocument", "parse_document", "parse_file", "parse_statement", "parse_statements",
]


def _check(doc, result, strict):
    if strict and result.check_balance() is False:
        label = f" ({result.account_ref})" if result.account_ref else ""
        raise StatementParseError(
            f"{doc.name}{label}: opening balance + movements != closing balance — "
            f"a movement was missed or mis-signed"
        )
    return result


def parse_document(doc, strict=True):
    """Parse an already-loaded RawDocument. With strict=True (the
    default), a document whose balances don't chain raises instead of
    returning a result that is silently wrong.

    Returns a StatementDocument, or a list of them when the file holds
    several accounts (e.g. a multi-account XLSX export)."""
    parser = find_parser(doc)
    if parser is None:
        raise StatementParseError(f"{doc.name}: no parser recognizes this document")
    result = parser.parse(doc)
    if isinstance(result, list):
        return [_check(doc, r, strict) for r in result]
    return _check(doc, result, strict)


def parse_file(path, strict=True):
    """Every document in one file, always as a list: one entry for a
    single statement, one per account for a multi-account export."""
    result = parse_document(load_document(path), strict=strict)
    return result if isinstance(result, list) else [result]


def parse_statement(path, strict=True):
    """The one document in `path`. A file holding several accounts
    raises ValueError: use parse_file() for those."""
    documents = parse_file(path, strict=strict)
    if len(documents) != 1:
        raise ValueError(
            f"{Path(path).name}: contains {len(documents)} accounts — use parse_file()"
        )
    return documents[0]


def _iter_paths(paths):
    if isinstance(paths, (str, Path)):
        path = Path(paths)
        if path.is_dir():
            yield from sorted(
                p for p in path.rglob("*")
                # "~$..." is the lock file Excel leaves next to an open workbook
                if p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~$")
            )
        else:
            yield path
        return
    for item in paths:
        yield from _iter_paths(item)


def parse_statements(paths, strict=True):
    """Parse a directory (recursively), a file, or an iterable of either.
    Returns (documents, errors): one unreadable file never hides the
    others. A multi-account file contributes one document per account."""
    documents, errors = [], []
    for path in _iter_paths(paths):
        try:
            documents.extend(parse_file(path, strict=strict))
        except (StatementParseError, ValueError) as exc:
            errors.append(str(exc))
    return documents, errors
