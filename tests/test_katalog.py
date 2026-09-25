import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math

import pandas as pd
import pytest

from core.katalog import lade_speicher_katalog, KatalogFehler


def _schreibe(tmp_path, zeilen: dict, name="speicher.xlsx"):
    pfad = tmp_path / name
    pd.DataFrame(zeilen).to_excel(pfad, index=False)
    return pfad


def _basis_spalten(**overrides):
    spalten = {
        "Hersteller": ["C"], "Produktname": ["S-1000"], "Nennvolumen [l]": [1000],
        "Material Speicher": ["Edelstahl"], "Gesamthöhe [mm]": [1200],
        "Durchmesser [mm]": [600], "Nettokosten [Euro]": [2500],
        "Warmhalteverlust [W]": [50],
    }
    spalten.update(overrides)
    return spalten


def test_runder_speicher_ueber_durchmesser(tmp_path):
    pfad = _schreibe(tmp_path, _basis_spalten())
    erg = lade_speicher_katalog(pfad)
    sp = erg.katalog
    assert not erg.warnungen
    assert sp.loc[0, "durchmesser_mm"] == pytest.approx(600)
    assert pd.isna(sp.loc[0, "breite_mm"]) and pd.isna(sp.loc[0, "laenge_mm"])
    assert sp.loc[0, "grundflaeche_m2"] == pytest.approx(math.pi * 0.3 ** 2)


def test_eckiger_speicher_ueber_breite_laenge(tmp_path):
    spalten = _basis_spalten()
    del spalten["Durchmesser [mm]"]
    spalten["Breite [mm]"] = [800]
    spalten["Länge [mm]"] = [900]
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    sp = erg.katalog
    assert pd.isna(sp.loc[0, "durchmesser_mm"])
    assert sp.loc[0, "grundflaeche_m2"] == pytest.approx(0.8 * 0.9)


def test_gemischter_katalog_rund_und_eckig(tmp_path):
    pfad = _schreibe(tmp_path, {
        "Hersteller": ["C", "C"], "Produktname": ["S-Rund", "S-Eckig"],
        "Nennvolumen [l]": [1000, 1200], "Material Speicher": ["Edelstahl", "Edelstahl"],
        "Gesamthöhe [mm]": [1200, 1300],
        "Durchmesser [mm]": [600, None],
        "Breite [mm]": [None, 800], "Länge [mm]": [None, 900],
        "Nettokosten [Euro]": [2500, 2700],
        "Warmhalteverlust [W]": [50, 55],
    })
    erg = lade_speicher_katalog(pfad)
    sp = erg.katalog
    assert sp.loc[sp["produkt"] == "S-Rund", "grundflaeche_m2"].iloc[0] == pytest.approx(math.pi * 0.3 ** 2)
    assert sp.loc[sp["produkt"] == "S-Eckig", "grundflaeche_m2"].iloc[0] == pytest.approx(0.72)


def test_warmhalteverlust_wird_nach_gl7_umgerechnet(tmp_path):
    pfad = _schreibe(tmp_path, _basis_spalten())
    erg = lade_speicher_katalog(pfad)
    sp = erg.katalog
    assert sp.loc[0, "warmhalteverlust_w"] == pytest.approx(50.0)
    assert sp.loc[0, "q_sb_sto"] == pytest.approx(50.0 * 0.024)


def test_material_ist_optional(tmp_path):
    spalten = _basis_spalten()
    del spalten["Material Speicher"]
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    assert erg.katalog.loc[0, "material"] == "unbekannt"


def test_warmhalteverlust_ist_optional(tmp_path):
    """Anders als die übrigen Pflichtfelder: fehlt die ganze Spalte, wird
    trotzdem geladen (Warmhalteverlust wird nur für q_sb_sto gebraucht,
    nicht für Investkosten-/Volumenauswertungen) - q_sb_sto ist dann NaN,
    und es gibt eine Warnung statt eines harten Fehlers."""
    spalten = _basis_spalten()
    del spalten["Warmhalteverlust [W]"]
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    assert list(erg.katalog["produkt"]) == ["S-1000"]
    assert pd.isna(erg.katalog.loc[0, "q_sb_sto"])
    assert len(erg.warnungen) == 1
    assert "S-1000" in erg.warnungen[0]


def test_leere_zelle_bei_warmhalteverlust_wird_nicht_uebersprungen(tmp_path):
    """Anders als bei den übrigen Pflichtfeldern (siehe
    test_leere_zelle_in_pflichtfeld_wird_uebersprungen_mit_warnung) bleibt
    die Zeile trotz fehlendem Warmhalteverlust im Katalog - nur q_sb_sto
    wird NaN, alle anderen Werte (u. a. für Investkosten-/Volumenplots)
    bleiben nutzbar."""
    spalten = {
        "Hersteller": ["C", "C"], "Produktname": ["S-Mit-Verlust", "S-Ohne-Verlust"],
        "Nennvolumen [l]": [1000, 1500], "Material Speicher": ["Edelstahl", "Edelstahl"],
        "Gesamthöhe [mm]": [1200, 1400],
        "Durchmesser [mm]": [600, 700],
        "Nettokosten [Euro]": [2500, 2800],
        "Warmhalteverlust [W]": [50, None],
    }
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    assert list(erg.katalog["produkt"]) == ["S-Mit-Verlust", "S-Ohne-Verlust"]
    ohne_verlust = erg.katalog.loc[erg.katalog["produkt"] == "S-Ohne-Verlust"].iloc[0]
    assert ohne_verlust["nettokosten"] == 2800
    assert pd.isna(ohne_verlust["q_sb_sto"])
    assert len(erg.warnungen) == 1
    assert "S-Ohne-Verlust" in erg.warnungen[0]


def test_fehlende_masse_wirft_fehler(tmp_path):
    spalten = _basis_spalten()
    del spalten["Gesamthöhe [mm]"]
    pfad = _schreibe(tmp_path, spalten)
    with pytest.raises(KatalogFehler):
        lade_speicher_katalog(pfad)


def test_leere_zelle_in_pflichtfeld_wird_uebersprungen_mit_warnung(tmp_path):
    """Nur einzelne Zeilen mit fehlenden Pflichtwerten fliegen raus (Warnung),
    nicht der gesamte Katalog-Import."""
    spalten = {
        "Hersteller": ["C", "C"], "Produktname": ["S-OK", "S-Ohne-Kosten"],
        "Nennvolumen [l]": [1000, 1500], "Material Speicher": ["Edelstahl", "Edelstahl"],
        "Gesamthöhe [mm]": [1200, 1400],
        "Durchmesser [mm]": [600, 700],
        "Nettokosten [Euro]": [2500, None],
        "Warmhalteverlust [W]": [50, 60],
    }
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    assert list(erg.katalog["produkt"]) == ["S-OK"]
    assert len(erg.warnungen) == 1
    assert "S-Ohne-Kosten" in erg.warnungen[0]


def test_einzige_zeile_ohne_grundriss_wirft_fehler(tmp_path):
    """Bleibt nach dem Herausfiltern unvollständiger Zeilen gar keine Zeile
    mehr übrig, ist das ein harter Fehler (nichts zu berechnen)."""
    spalten = _basis_spalten()
    del spalten["Durchmesser [mm]"]
    pfad = _schreibe(tmp_path, spalten)
    with pytest.raises(KatalogFehler):
        lade_speicher_katalog(pfad)


def test_eine_von_zwei_zeilen_ohne_grundriss_wird_uebersprungen_mit_warnung(tmp_path):
    spalten = {
        "Hersteller": ["C", "C"], "Produktname": ["S-OK", "S-Ohne-Grundriss"],
        "Nennvolumen [l]": [1000, 1500], "Material Speicher": ["Edelstahl", "Edelstahl"],
        "Gesamthöhe [mm]": [1200, 1400],
        "Durchmesser [mm]": [600, None],
        "Nettokosten [Euro]": [2500, 2800],
        "Warmhalteverlust [W]": [50, 60],
    }
    pfad = _schreibe(tmp_path, spalten)
    erg = lade_speicher_katalog(pfad)
    assert list(erg.katalog["produkt"]) == ["S-OK"]
    assert len(erg.warnungen) == 1
    assert "S-Ohne-Grundriss" in erg.warnungen[0]


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_runder_speicher_ueber_durchmesser(tmp)
        test_eckiger_speicher_ueber_breite_laenge(tmp)
        test_gemischter_katalog_rund_und_eckig(tmp)
        test_warmhalteverlust_wird_nach_gl7_umgerechnet(tmp)
        test_material_ist_optional(tmp)
        test_fehlende_masse_wirft_fehler(tmp)
    print("Alle Katalog-Tests erfolgreich.")
