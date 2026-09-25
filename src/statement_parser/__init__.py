"""statement-parser: regex-only parsing of broker/bank statements into
typed records (no LLM, no API keys)."""

from pathlib import Path

from .models import CashBalance, Movement, Position, StatementDocument, StatementParseError
from .parsers import PARSERS, find_parser
from .text import RawDocument, load_document

SUPPORTED_SUFFIXES = {".pdf", ".csv"}

__all__ = [
    "CashBalance", "Movement", "Position", "StatementDocument", "StatementParseError",
    "PARSERS", "RawDocument", "parse_document", "parse_statement", "parse_statements",
]


def parse_document(doc, strict=True):
    """Parse an already-loaded RawDocument. With strict=True (the
    default), a document whose balances don't chain raises instead of
    returning a result that is silently wrong."""
    parser = find_parser(doc)
    if parser is None:
        raise StatementParseError(f"{doc.name}: no parser recognizes this document")
    result = parser.parse(doc)
    if strict and result.check_balance() is False:
        raise StatementParseError(
            f"{doc.name}: opening balance + movements != closing balance — "
            f"a movement was missed or mis-signed"
        )
    return result


def parse_statement(path, strict=True):
    return parse_document(load_document(path), strict=strict)


def _iter_paths(paths):
    if isinstance(paths, (str, Path)):
        path = Path(paths)
        if path.is_dir():
            yield from sorted(
                p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES
            )
        else:
            yield path
        return
    for item in paths:
        yield from _iter_paths(item)


def parse_statements(paths, strict=True):
    """Parse a directory (recursively), a file, or an iterable of either.
    Returns (documents, errors): one unreadable file never hides the
    others."""
    documents, errors = [], []
    for path in _iter_paths(paths):
        try:
            documents.append(parse_statement(path, strict=strict))
        except (StatementParseError, ValueError) as exc:
            errors.append(str(exc))
    return documents, errors
