from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement_parser import StatementParseError, parse_document, parse_file, parse_statement
from statement_parser.parsers import (
    boursobank_avis_opere,
    boursobank_releve_compte,
    boursobank_releve_especes,
    bourso_vie_arbitrage,
    cm_av_arbitrage,
    cm_xlsx_comptes,
    find_parser,
)
from statement_parser.text import load_document
from tests.builders import header_line, line, positioned_pdf, text_doc, workbook_doc

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal


# --- Trade Republic CSV ------------------------------------------------------

def test_trade_republic_csv():
    doc = parse_statement(FIXTURES / "trade_republic_export.csv")

    assert doc.doc_type == "trade_republic_csv"
    assert (doc.period_start, doc.period_end) == (date(2026, 7, 20), date(2026, 8, 17))
    by_ref = {m.reference: m for m in doc.movements}

    assert by_ref["tx-0001"].amount == D("250")
    # fee lives in its own column, amount excludes it: net effect is -5
    assert (by_ref["tx-0002"].amount, by_ref["tx-0002"].fee) == (D("-5.00"), D("5.00"))
    # a free receipt moves units, not cash
    free = by_ref["tx-0003"]
    assert (free.amount, free.quantity, free.kind) == (0, D("1.2620300000"), "FREE_RECEIPT")
    # interest 0.22 with 0.07 withheld -> 0.15 net
    assert (by_ref["tx-0005"].amount, by_ref["tx-0005"].tax) == (D("0.15"), D("0.07"))
    buy = by_ref["tx-0006"]
    assert (buy.kind, buy.isin, buy.quantity, buy.amount) == ("BUY", "IE00BK5BCH80", D("3.3902900000"), D("-50.00"))
    assert buy.extra["category"] == "TRADING" and buy.extra["asset_class"] == "FUND"


# --- BoursoBank avis d'opéré ---------------------------------------------------

AVIS = """Service Clientèle : 01 00 00 00 00 – www.boursobank.com
Boursorama S.A. au capital de 1 000,00 €
OPERATION SUR OPC
(Organisme de Placement Collectif)
le 08/10/2025
Références de votre compte titres
12345 67890 00011122233 Compte PEA
Résident Français
SOUSCRIPTION F.C.P.P
Date Quantité Informations sur la valeur Informations sur l'exécution
06/10/2025 0,74627 PEA PROF.OFFENS.RESP.C FCP 5D5 Référence : 042145031672
Code ISIN : FR001400AED5 Valeur liquidative : 134,00 EUR
Montant brut Droits d'entrée Frais H.T. T.V.A. Montant net au débit de votre compte
100,00 EUR 0,00 EUR 0,00 EUR 100,00 EUR
"""


def test_boursobank_avis_opere_subscription():
    doc = parse_document(text_doc(AVIS))

    assert doc.doc_type == boursobank_avis_opere.DOC_TYPE
    assert (doc.account_ref, doc.account_label) == ("12345 67890 00011122233", "PEA")
    [m] = doc.movements
    assert m.kind == "SUBSCRIPTION"
    assert m.date == date(2025, 10, 6)
    assert (m.isin, m.security_name) == ("FR001400AED5", "PEA PROF.OFFENS.RESP.C")
    assert (m.quantity, m.price, m.gross, m.fee, m.amount) == (D("0.74627"), D("134.00"), D("100.00"), 0, D("-100.00"))
    assert m.reference == "042145031672"
    assert doc.warnings == []


def test_boursobank_avis_opere_with_charges_and_redemption():
    text = AVIS.replace("SOUSCRIPTION F.C.P.P", "RACHAT F.C.P.P").replace(
        "100,00 EUR 0,00 EUR 0,00 EUR 100,00 EUR", "100,00 EUR 1,50 EUR 0,50 EUR 0,10 EUR 97,90 EUR"
    )
    [m] = parse_document(text_doc(text)).movements
    assert m.kind == "REDEMPTION"
    assert (m.quantity, m.fee, m.amount) == (D("-0.74627"), D("2.10"), D("97.90"))


# --- BoursoBank relevé espèces (PEA cash) ----------------------------------------

ESPECES_PREAMBLE = """Boursorama S.A.
RELEVE COMPTE ESPECES : SEPTEMBRE 2025
Extrait au 30/09/2025
Références de votre compte espèces
12345 67890 00099988877 Compte PEA"""


def especes(rows):
    return positioned_pdf([[header_line(), *rows]], preamble=ESPECES_PREAMBLE)


def test_boursobank_releve_especes():
    doc = parse_document(especes([
        line("31/08/2025 ANCIEN SOLDE", credit="116,38"),
        line("09/09/2025 SOUSCRIPTION D'OPC 0,776 PEA PROF.OFFENS.RE", debit="100,00"),
        line("10/09/2025 VIR Versement Plan Epargne", credit="250,00"),
        line("12/09/2025 SOUSCRIPTION D'OPC 0,450 BOURSO I.BOURSO EU", debit="50,00"),
        line("30/09/2025 NOUVEAU SOLDE", credit="216,38"),
    ]))

    assert doc.doc_type == boursobank_releve_especes.DOC_TYPE
    assert doc.account_ref == "12345 67890 00099988877"
    assert (doc.period_start, doc.period_end) == (date(2025, 8, 31), date(2025, 9, 30))
    assert doc.check_balance() is True
    sub, vir, sub2 = doc.movements
    assert (sub.kind, sub.quantity, sub.security_name, sub.amount) == ("SUBSCRIPTION", D("0.776"), "PEA PROF.OFFENS.RE", D("-100.00"))
    assert (vir.kind, vir.amount) == ("VIR", D("250.00"))


def test_mis_signed_amount_fails_the_balance_check():
    # the 250,00 transfer printed under Débit instead of Crédit
    doc = especes([
        line("31/08/2025 ANCIEN SOLDE", credit="116,38"),
        line("10/09/2025 VIR Versement Plan Epargne", debit="250,00"),
        line("30/09/2025 NOUVEAU SOLDE", credit="366,38"),
    ])
    with pytest.raises(StatementParseError, match="closing balance"):
        parse_document(doc)
    assert parse_document(doc, strict=False).check_balance() is False


# --- BoursoBank relevé de compte (current account / livret) -----------------------

COMPTE_PREAMBLE = """Date N° de RIB Devise Période
01/09/2026 12345 67890 00011111111 55 EUR du 01/08/2026 au 31/08/2026 0,00 € 1/2
Extrait de votre compte en EUR
Compte d'épargne: Livret Developpement Durable Solidaire
B.I.C. BOUSFRPPXXX I.B.A.N. FR76 1234 5678 9000 1111 1111 155
MOUVEMENTS EN EUR"""


def test_boursobank_releve_compte_multi_page_with_continuations():
    page1 = [
        header_line(),
        line("SOLDE AU : 31/07/2026", credit="6.000,00"),
        line("03/08/2026 VIR Virement depuis LDDS 03/08/2026", debit="500,00"),
        line("M DUPONT JEAN"),
        line("Réf : SCT000000000000000001"),
        line("05/08/2026 INTERETS CREDITEURS 05/08/2026", credit="12,34"),
        line("A réception d'un extrait de compte vous disposez d'un délai"),
        line("Boursorama - SA au capital de 1 000,00 €", credit="1.000,00"),  # footer: ignored
    ]
    page2 = [
        line("Date N° de RIB Devise Période"),
        header_line(),
        line("28/08/2026 VIR Virement depuis LDDS 28/08/2026", debit="1.500,00"),
        line("Nouveau solde en EUR :", credit="4.012,34"),
    ]
    doc = parse_document(positioned_pdf([page1, page2], preamble=COMPTE_PREAMBLE))

    assert doc.doc_type == boursobank_releve_compte.DOC_TYPE
    assert doc.account_ref == "FR7612345678900011111111155"
    assert doc.account_label == "Livret Developpement Durable Solidaire"
    assert (doc.period_start, doc.period_end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert [b.balance for b in doc.balances] == [D("6000.00"), D("4012.34")]
    first, interest, last = doc.movements
    assert (first.label, first.value_date, first.amount) == ("VIR Virement depuis LDDS", date(2026, 8, 3), D("-500.00"))
    assert first.details == ["M DUPONT JEAN", "Réf : SCT000000000000000001"]
    assert first.reference == "SCT000000000000000001"
    assert (interest.kind, interest.amount) == ("INTERETS", D("12.34"))
    assert last.amount == D("-1500.00")


# --- Crédit Mutuel AV arbitrage ------------------------------------------------------

ARBITRAGE = """Votre contrat :
N° Contrat : G7 00000001
Vous êtes titulaire d'un contrat ESSENTIEL et nous vous remercions de votre confiance.
Gestion Pilotée
qu'une opération d'arbitrage a ainsi été réalisée en date du 20 mars 2026 au sein de votre profil de gestion,
Objet : Opération d'arbitrage au sein de votre profil de Gestion Pilotée
Situation de votre profil de Gestion Pilotée PILOTE DURABLE avant l'opération d'arbitrage
Valeur de la part Valeur au 20/03/2026
Catégories / Supports Nombre de parts
en euros en euros
ACTIONS INTERNATIONALES
FUND ALPHA RC 2,956250 87,640000 259,09
FUND BETA 1,000000 100,000000 100,00
FONDS EN EUROS
ACTIF SECURITE 1 049,46
TOTAL 1 408,55
Situation de votre profil de Gestion Pilotée PILOTE DURABLE après l'opération d'arbitrage
Valeur de la part Valeur au 20/03/2026
Catégories / Supports Nombre de parts
en euros en euros
ACTIONS INTERNATIONALES
FUND ALPHA RC 2,475126 87,640000 216,92
FUND GAMMA 1,500000 100,000000 150,00
FONDS EN EUROS
ACTIF SECURITE 1 041,63
TOTAL 1 408,55
"""


def test_cm_av_arbitrage_positions_and_switches():
    doc = parse_document(text_doc(ARBITRAGE))

    assert doc.doc_type == cm_av_arbitrage.DOC_TYPE
    assert (doc.account_ref, doc.account_label) == ("G7 00000001", "ESSENTIEL")
    assert doc.period_end == date(2026, 3, 20)
    assert doc.warnings == []

    after = {p.security_name: p for p in doc.positions if p.snapshot == "after"}
    assert (after["FUND ALPHA RC"].quantity, after["FUND ALPHA RC"].price) == (D("2.475126"), D("87.640000"))
    assert after["FUND ALPHA RC"].section == "ACTIONS INTERNATIONALES"
    assert (after["ACTIF SECURITE"].quantity, after["ACTIF SECURITE"].value) == (None, D("1041.63"))

    switches = {m.security_name: m for m in doc.movements}
    assert switches["FUND ALPHA RC"].kind == "SWITCH_OUT"
    assert switches["FUND ALPHA RC"].quantity == D("-0.481124")
    assert (switches["FUND BETA"].kind, switches["FUND BETA"].quantity) == ("SWITCH_OUT", D("-1.000000"))
    assert (switches["FUND GAMMA"].kind, switches["FUND GAMMA"].quantity) == ("SWITCH_IN", D("1.500000"))
    assert switches["ACTIF SECURITE"].extra["value_delta"] == D("-7.83")
    assert all(m.amount == 0 for m in doc.movements)


def test_cm_av_arbitrage_total_mismatch_is_a_warning():
    doc = parse_document(text_doc(ARBITRAGE.replace("TOTAL 1 408,55\nSituation", "TOTAL 1 500,00\nSituation")))
    assert any("before" in w for w in doc.warnings)


# --- Bourso Vie arbitrage --------------------------------------------------------------

BOURSO_VIE = """Madame JEANNE DUPONT
- Références à rappeler -
Bourso Vie
Contrat n° 10000001
OBJET : Arbitrage
Par la présente lettre avenant, nous vous détaillons ci-dessous le changement de répartition de votre épargne,
Arbitrage d'un montant de : 1 200,50 Euros en date du 05/05/2026
- Désinvestissement :
- Fonds en Euros
- Fonds Euro Exemple
Valeur au 06/05/2026 : 1 200,50 Euros
- Réinvestissement :
du fait de la gratuité de votre arbitrage
- Unités de Compte
- *Compartiment SICAV FUND ALPHA -A-ACC (ISIN : LU0000000001)
Valeur au 06/05/2026 : 4,0000 Parts à 200,00 Euros l'unité soit 800,00 Euros
- *Compartiment SICAV FUND BETA RC Eur (ISIN : LU0000000002)
Valeur au 06/05/2026 : 2,0010 Parts à 200,00 Euros l'unité soit 400,50 Euros
1/2
Madame JEANNE DUPONT
- Références à rappeler -
Bourso Vie
Contrat n° 10000001
OBJET : Valeur atteinte après arbitrage
- Unités de Compte
- *Compartiment SICAV FUND ALPHA -A-ACC (ISIN : LU0000000001)
Nombre de parts : 4,0000 Parts
Valeur de la part au 06/05/2026 : 200,00 Euros
Contre-valeur en Euros : 799,99 Euros
- *Compartiment SICAV FUND BETA RC Eur (ISIN : LU0000000002)
Nombre de parts : 2,0010 Parts
Valeur de la part au 06/05/2026 : 200,00 Euros
Contre-valeur en Euros : 400,50 Euros
Epargne atteinte totale : 1 200,50 Euros
"""


def test_bourso_vie_arbitrage_switches_and_positions():
    doc = parse_document(text_doc(BOURSO_VIE))

    assert doc.doc_type == bourso_vie_arbitrage.DOC_TYPE
    assert (doc.account_ref, doc.account_label) == ("10000001", "Bourso Vie")
    assert doc.period_start == doc.period_end == date(2026, 5, 5)
    assert doc.warnings == []  # 799,99 vs 800,00 is within tolerance

    euro, alpha, beta = doc.movements
    assert (euro.kind, euro.security_name, euro.quantity, euro.gross) == ("SWITCH", "Fonds Euro Exemple", None, D("1200.50"))
    assert euro.extra == {"value_delta": D("-1200.50"), "unitless": True}
    assert (alpha.kind, alpha.isin, alpha.quantity, alpha.price, alpha.gross) == (
        "SWITCH_IN", "LU0000000001", D("4.0000"), D("200.00"), D("800.00"))
    assert alpha.security_name == "Compartiment SICAV FUND ALPHA -A-ACC"
    assert alpha.value_date == date(2026, 5, 6)
    assert (beta.kind, beta.quantity) == ("SWITCH_IN", D("2.0010"))
    assert all(m.amount == 0 for m in doc.movements)

    first, second = doc.positions
    assert (first.snapshot, first.section, first.isin) == ("after", "Unités de Compte", "LU0000000001")
    assert (first.quantity, first.price, first.value, first.as_of) == (D("4.0000"), D("200.00"), D("799.99"), date(2026, 5, 6))
    assert second.value == D("400.50")


def test_bourso_vie_arbitrage_unit_fund_sold_and_mismatch_warning():
    text = BOURSO_VIE.replace("- Fonds en Euros\n- Fonds Euro Exemple\nValeur au 06/05/2026 : 1 200,50 Euros", (
        "- Unités de Compte\n- *Compartiment SICAV FUND GAMMA (ISIN : FR0000000003)\n"
        "Valeur au 06/05/2026 : 10,0000 Parts à 120,00 Euros l'unité soit 1 200,00 Euros"))
    doc = parse_document(text_doc(text))

    gamma = doc.movements[0]
    assert (gamma.kind, gamma.isin, gamma.quantity) == ("SWITCH_OUT", "FR0000000003", D("-10.0000"))
    assert any("désinvestissement" in w for w in doc.warnings)


# --- Crédit Mutuel comptes.xlsx --------------------------------------------------------

def cm_sheet(label, rib, rows, closing="Solde au 25/09/2026 : ", balance=None):
    title = f"Situation de votre compte {label} (EUR) au 25/09/2026"
    return [
        [title] * 6,
        [f"R.I.B. : {rib}"] * 6,
        [None, None, None, "Solde initial : ", "Solde initial : ", None, "EUR"],
        ["Liste de vos comptes"] * 6,
        ["Date", "Valeur", "Libellé", "Débit", "Crédit", "Solde", "Dev"],
        *[[d, v, lib, deb, cred, None, "EUR"] for d, v, lib, deb, cred in rows],
        [None] * 7,
        [None, None, None, closing, closing, balance, "EUR"],
        ["Liste de vos comptes"] * 6,
    ]


def cm_workbook(summary_livret=D("1100")):
    return {
        "Vos comptes": [
            ["Votre situation financière au 25/09/2026", None, None, None],
            [None, None, None, None],
            ["Compte", "R.I.B.", "Solde", "Dev"],
            ["LIVRET BLEU MME DUPONT", "10000 00001 00000000001", summary_livret, "EUR"],
            ["PRET IMMO", "10000 00001 00000000002", D("-50000.5"), "EUR"],
            ["COMPTE COURANT MME DUPONT", "10000 00001 00000000003", D("42.1"), "EUR"],
        ],
        "Cpt 00001 00000000003": cm_sheet("COMPTE COURANT MME DUPONT", "10000 00001 00000000003", [
            (date(2026, 9, 1), date(2026, 9, 1), "PAIEMENT CB 0109 PARIS BOULANGERIE CARTE 0000", D("-7.9"), None),
            (date(2026, 9, 2), date(2026, 9, 3), "VIR DE MME DUPONT", None, D("50")),
        ], balance=D("42.1")),
        "Cpt 00001 00000000001": cm_sheet("LIVRET BLEU MME DUPONT", "10000 00001 00000000001", [
            (date(2026, 8, 30), date(2026, 9, 1), "VIR DE MME DUPONT", None, D("100")),
        ], balance=D("1100")),
    }


def test_cm_xlsx_one_document_per_account():
    livret, loan, current = parse_document(workbook_doc(cm_workbook()))

    assert {d.doc_type for d in (livret, loan, current)} == {cm_xlsx_comptes.DOC_TYPE}
    assert (livret.account_ref, livret.account_label) == ("10000 00001 00000000001", "LIVRET BLEU MME DUPONT")

    assert (current.period_start, current.period_end) == (date(2026, 9, 1), date(2026, 9, 25))
    card, transfer = current.movements
    assert (card.date, card.amount, card.kind, card.line_no) == (date(2026, 9, 1), D("-7.90"), "PAIEMENT", 6)
    assert (transfer.value_date, transfer.amount, transfer.extra) == (date(2026, 9, 3), D("50.00"), {"sheet": "Cpt 00001 00000000003"})
    assert [(b.kind, b.as_of, b.balance) for b in current.balances] == [("closing", date(2026, 9, 25), D("42.10"))]
    assert current.check_balance() is None  # no opening balance in the export
    assert current.warnings == []

    # listed in the summary only: balance, no movements
    assert (loan.account_ref, loan.account_label, loan.movements) == ("10000 00001 00000000002", "PRET IMMO", [])
    assert [(b.as_of, b.balance) for b in loan.balances] == [(date(2026, 9, 25), D("-50000.50"))]


def test_cm_xlsx_summary_mismatch_is_a_warning():
    livret = parse_document(workbook_doc(cm_workbook(summary_livret=D("999"))))[0]
    assert any("Vos comptes" in w for w in livret.warnings)


def test_xlsx_loader_skips_hidden_sheets_and_parse_file(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in cm_workbook().items():
        ws = workbook.create_sheet(name)
        for row in rows:
            ws.append([float(v) if isinstance(v, Decimal) else v for v in row])
    hidden = workbook.create_sheet("hidden_data")
    hidden.append(["Situation de votre compte STALE (EUR) au 01/01/2021"])
    hidden.sheet_state = "veryHidden"
    path = tmp_path / "comptes.xlsx"
    workbook.save(path)

    raw = load_document(path)
    assert "hidden_data" not in raw.sheets
    row = raw.sheets["Cpt 00001 00000000003"][5]
    assert (row[0], row[3]) == (date(2026, 9, 1), D("-7.9"))  # a date, and a Decimal without float noise

    documents = parse_file(path)
    assert [d.account_label for d in documents] == ["LIVRET BLEU MME DUPONT", "PRET IMMO", "COMPTE COURANT MME DUPONT"]
    with pytest.raises(ValueError, match="use parse_file"):
        parse_statement(path)


# --- registry ----------------------------------------------------------------------------

def test_unrecognized_document_raises():
    with pytest.raises(StatementParseError, match="no parser"):
        parse_document(text_doc("just some text"))


def test_each_fixture_matches_exactly_one_parser():
    for doc in (text_doc(AVIS), text_doc(ARBITRAGE), especes([]),
                positioned_pdf([], preamble=COMPTE_PREAMBLE), text_doc(BOURSO_VIE),
                workbook_doc(cm_workbook())):
        assert find_parser(doc) is not None
