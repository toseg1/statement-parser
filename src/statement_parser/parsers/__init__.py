"""Parser registry. Each module exposes DOC_TYPE, BROKER, detect(doc) and
parse(doc). Detection is a regex/text fingerprint on the document itself,
never the filename — broker downloads are named inconsistently
("AffichageDocument (7).pdf")."""

from . import (
    boursobank_avis_opere,
    boursobank_releve_compte,
    boursobank_releve_especes,
    cm_av_arbitrage,
    trade_republic_csv,
)

PARSERS = [
    trade_republic_csv,
    boursobank_avis_opere,
    boursobank_releve_especes,
    boursobank_releve_compte,
    cm_av_arbitrage,
]


def find_parser(doc):
    matches = [p for p in PARSERS if p.detect(doc)]
    if len(matches) > 1:
        names = ", ".join(p.DOC_TYPE for p in matches)
        raise ValueError(f"{doc.name}: ambiguous document, matched {names}")
    return matches[0] if matches else None
