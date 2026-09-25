import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from core.modell import Eingabedaten
from core.bedarf import zapfprofil_minutenwerte
from core.katalog import lade_wp_katalog, lade_speicher_katalog, KatalogFehler
from core.investition import (
    optimiere, guenstigste_zulaessige, Kombination,
    materialschonendste_zulaessige, pareto_front, kompromiss_zulaessige,
)


def _wp_excel(tmp_path):
    """Nachgebildete Herstellerpreisliste (z. B. alpha innotec): Leistung/COP an
    zwei Betriebspunkten, Abmessungen H/B/L, Listenpreis+Inbetriebnahme.
    Transportkosten bewusst weggelassen (real oft nicht separat ausgewiesen
    -> optional)."""
    pfad = tmp_path / "wp.xlsx"
    pd.DataFrame({
        "Hersteller": ["A", "A", "B"],
        "Produkt": ["WP-30", "WP-50", "WP-80"],
        "Leistung B0/W35 [kW]": [34.0, 57.0, 90.0],
        "COP B0/W35": [4.8, 4.7, 4.6],
        "Leistung B0/W55 [kW]": [30.0, 50.0, 80.0],
        "COP B0/W55": [3.2, 3.1, 3.0],
        "max. Vorlauftemperatur [°C]": [65, 65, 70],
        "Höhe [mm]": [1500, 1500, 1900],
        "Breite [mm]": [600, 600, 650],
        "Länge [mm]": [650, 650, 700],
        "Listenpreis 2026 [Euro]": [10000, 14000, 20000],
        "Inbetriebnahme 2026 [Euro]": [500, 500, 600],
    }).to_excel(pfad, index=False)
    return pfad


def _speicher_excel(tmp_path):
    pfad = tmp_path / "speicher.xlsx"
    pd.DataFrame({
        "Hersteller": ["C", "C", "C", "D"],
        "Produktname": ["S-1000", "S-2000", "S-3000", "S-2000E"],
        "Nennvolumen [l]": [1000, 2000, 3000, 2000],
        "Material Speicher": ["Stahl, emailliert", "Stahl, emailliert", "Stahl, emailliert", "Edelstahl"],
        "Gesamthöhe [mm]": [1200, 1600, 1900, 1600],
        "Durchmesser [mm]": [600, 790, 950, 790],
        "Nettokosten [Euro]": [2500, 4000, 5500, 5200],
        "Warmhalteverlust [W]": [50, 70, 90, 75],
    }).to_excel(pfad, index=False)
    return pfad


def test_kataloge_laden(tmp_path):
    wp = lade_wp_katalog(_wp_excel(tmp_path)).katalog  # Default-Betriebspunkt W55
    assert list(wp["leistung_kw"]) == [30, 50, 80]
    # keine Transportkosten-Spalte vorhanden -> optional, geht mit 0 in die Investkosten ein
    assert wp.loc[wp["produkt"] == "WP-30", "investkosten"].iloc[0] == pytest.approx(10000 + 500 + 0)

    sp = lade_speicher_katalog(_speicher_excel(tmp_path)).katalog
    assert set(sp["material"]) == {"Stahl, emailliert", "Edelstahl"}
    assert sp.loc[sp["produkt"] == "S-1000", "investkosten"].iloc[0] == 2500
    # Warmhalteverlust (Gl. 7) je Modell statt einem globalen manuellen Wert
    assert sp.loc[sp["produkt"] == "S-1000", "q_sb_sto"].iloc[0] == pytest.approx(50 * 0.024)


def test_falsche_spalte_wp(tmp_path):
    pfad = tmp_path / "wp_falsch.xlsx"
    pd.DataFrame({"Hersteller": ["A"], "Produkt": ["X"]}).to_excel(pfad, index=False)
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(pfad)


def test_optimierung_findet_guenstigste_zulaessige_kombination(tmp_path):
    daten = Eingabedaten(speicher_typ="Speicherladesystem")
    zapf = zapfprofil_minutenwerte(daten)

    wp = lade_wp_katalog(_wp_excel(tmp_path)).katalog
    sp = lade_speicher_katalog(_speicher_excel(tmp_path)).katalog

    kombis = optimiere(daten, zapf, wp, sp)
    assert len(kombis) == 3 * 4

    beste = guenstigste_zulaessige(kombis)
    if beste is not None:
        # günstigste zulässige Kombination muss unter allen zulässigen minimal sein
        zulaessige = [k for k in kombis if k.zulaessig]
        assert beste.gesamtkosten == min(k.gesamtkosten for k in zulaessige)


def test_material_filter(tmp_path):
    daten = Eingabedaten()
    zapf = zapfprofil_minutenwerte(daten)
    wp = lade_wp_katalog(_wp_excel(tmp_path)).katalog
    sp = lade_speicher_katalog(_speicher_excel(tmp_path)).katalog

    kombis = optimiere(daten, zapf, wp, sp, material="Edelstahl")
    assert all(k.speicher_material == "Edelstahl" for k in kombis)
    assert len(kombis) == 3 * 1


def test_material_filter_ist_komma_tolerant(tmp_path):
    """'Stahl, emailliert' (reale Herstellerschreibweise) und 'Stahl
    emailliert' (Auswahl in der Oberfläche) müssen als gleich gelten."""
    daten = Eingabedaten()
    zapf = zapfprofil_minutenwerte(daten)
    wp = lade_wp_katalog(_wp_excel(tmp_path)).katalog
    sp = lade_speicher_katalog(_speicher_excel(tmp_path)).katalog

    kombis = optimiere(daten, zapf, wp, sp, material="Stahl emailliert")
    assert all(k.speicher_material == "Stahl, emailliert" for k in kombis)
    assert len(kombis) == 3 * 3


def _kombi(kosten: float, zyklen: int, zulaessig: bool = True, id_: str = "X") -> Kombination:
    """Minimale synthetische Kombination für die Modus-F-Auswahlfunktionen
    (materialschonendste_zulaessige/pareto_front/kompromiss_zulaessige), die
    nur auf gesamtkosten/zyklen/zulaessig arbeiten - der Rest der Felder ist
    für diese Tests irrelevant und wird nur plausibel befüllt."""
    return Kombination(
        wp_hersteller=f"WP-{id_}", wp_produkt="P", wp_leistung_kw=10.0, wp_kosten=kosten / 2,
        wp_platzbedarf_m3=1.0,
        speicher_hersteller=f"SP-{id_}", speicher_produkt="Q", speicher_volumen_l=1000.0,
        speicher_material="Edelstahl", speicher_kosten=kosten / 2,
        gesamtkosten=float(kosten), zulaessig=zulaessig, soc_min_kwh=10.0, q_sto_min_kwh=5.0,
        zyklen=zyklen, laufzeit_min=zyklen * 30,
    )


def test_materialschonendste_zulaessige_waehlt_min_zyklen():
    kombis = [_kombi(5000, 2, id_="A"), _kombi(3000, 4, id_="B"), _kombi(2000, 8, id_="C")]
    beste = materialschonendste_zulaessige(kombis)
    assert beste.wp_hersteller == "WP-A"
    assert beste.zyklen == 2


def test_pareto_front_filtert_dominierte_kombinationen():
    a = _kombi(5000, 2, id_="A")
    b = _kombi(3000, 4, id_="B")
    c = _kombi(2000, 8, id_="C")
    d = _kombi(4000, 8, id_="D")  # von C dominiert (günstiger, gleich viele Zyklen)
    e = _kombi(6000, 6, id_="E")  # von A dominiert (günstiger, weniger Zyklen)
    f = _kombi(1000, 1, zulaessig=False, id_="F")  # unzulässig, muss ignoriert werden

    front = pareto_front([a, b, c, d, e, f])
    assert [k.wp_hersteller for k in front] == ["WP-C", "WP-B", "WP-A"]  # nach Gesamtkosten sortiert


def test_kompromiss_zulaessige_gewichtung():
    a = _kombi(5000, 2, id_="A")  # teuer, wenig Zyklen
    b = _kombi(3000, 4, id_="B")  # mittig
    c = _kombi(2000, 8, id_="C")  # günstig, viele Zyklen
    kombis = [a, b, c]

    assert kompromiss_zulaessige(kombis, gewicht_kosten=1.0).wp_hersteller == "WP-C"  # rein ökonomisch
    assert kompromiss_zulaessige(kombis, gewicht_kosten=0.0).wp_hersteller == "WP-A"  # rein technisch
    assert kompromiss_zulaessige(kombis, gewicht_kosten=0.5).wp_hersteller == "WP-B"  # ausgewogen


def test_modus_f_funktionen_ohne_zulaessige_kombination():
    kombis = [_kombi(1000, 1, zulaessig=False)]
    assert pareto_front(kombis) == []
    assert kompromiss_zulaessige(kombis) is None
    assert materialschonendste_zulaessige(kombis) is None


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_kataloge_laden(tmp)
        test_falsche_spalte_wp(tmp)
        test_optimierung_findet_guenstigste_zulaessige_kombination(tmp)
        test_material_filter(tmp)
        test_material_filter_ist_komma_tolerant(tmp)
    test_materialschonendste_zulaessige_waehlt_min_zyklen()
    test_pareto_front_filtert_dominierte_kombinationen()
    test_kompromiss_zulaessige_gewichtung()
    test_modus_f_funktionen_ohne_zulaessige_kombination()
    print("Alle Investitions-Tests erfolgreich.")
