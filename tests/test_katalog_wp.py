import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from core.katalog import lade_wp_katalog, KatalogFehler


def _schreibe(tmp_path, spalten: dict, name="wp.xlsx"):
    pfad = tmp_path / name
    pd.DataFrame(spalten).to_excel(pfad, index=False)
    return pfad


def _basis_spalten():
    return {
        "Hersteller": ["A", "A"],
        "Produkt": ["WP-1", "WP-2"],
        "Leistung B0/W35 [kW]": [34.0, 57.0],
        "COP B0/W35": [4.8, 4.7],
        "Leistung B0/W55 [kW]": [30.0, 50.0],
        "COP B0/W55": [3.2, 3.1],
        "Höhe [mm]": [1500.0, 1500.0],
        "Breite [mm]": [600.0, 600.0],
        "Länge [mm]": [650.0, 650.0],
        "Listenpreis 2026 [Euro]": [10000.0, 14000.0],
        "Inbetriebnahme 2026 [Euro]": [500.0, 500.0],
    }


def test_betriebspunkt_w55_ist_default(tmp_path):
    erg = lade_wp_katalog(_schreibe(tmp_path, _basis_spalten()))
    wp = erg.katalog
    assert not erg.warnungen
    assert list(wp["leistung_kw"]) == [30.0, 50.0]
    assert list(wp["cop"]) == [3.2, 3.1]
    # beide Betriebspunkte bleiben erhalten
    assert list(wp["leistung_kw_w35"]) == [34.0, 57.0]
    assert list(wp["leistung_kw_w55"]) == [30.0, 50.0]


def test_betriebspunkt_w35_waehlbar(tmp_path):
    pfad = _schreibe(tmp_path, _basis_spalten())
    wp = lade_wp_katalog(pfad, betriebspunkt="W35").katalog
    assert list(wp["leistung_kw"]) == [34.0, 57.0]
    assert list(wp["cop"]) == [4.8, 4.7]


def test_platzbedarf_aus_hbl_berechnet(tmp_path):
    wp = lade_wp_katalog(_schreibe(tmp_path, _basis_spalten())).katalog
    erwartet = 1.5 * 0.6 * 0.65
    assert wp.loc[wp["produkt"] == "WP-1", "platzbedarf_m3"].iloc[0] == pytest.approx(erwartet)


def test_listenpreis_2026_wird_bevorzugt_vor_quelle_spalte(tmp_path):
    """Eine zusätzliche 'lt. Quelle'-Basisspalte (nur zur Indexierung) darf
    nicht statt des aktuellen Listenpreises gematcht werden, selbst wenn sie
    ebenfalls 'netto'/'listenpreis' im Namen trägt."""
    spalten = _basis_spalten()
    spalten["Listenpreis netto lt. Quelle [Euro]"] = [9822.0, 10559.0]
    spalten["Inbetriebnahmekosten lt. Quelle [Euro]"] = [500.0, 500.0]
    wp = lade_wp_katalog(_schreibe(tmp_path, spalten)).katalog
    assert wp.loc[wp["produkt"] == "WP-1", "listenpreis"].iloc[0] == pytest.approx(10000.0)
    assert wp.loc[wp["produkt"] == "WP-1", "ibn_kosten"].iloc[0] == pytest.approx(500.0)


def test_transportkosten_optional_default_null(tmp_path):
    erg = lade_wp_katalog(_schreibe(tmp_path, _basis_spalten()))
    wp = erg.katalog
    assert (wp["transport_kosten"] == 0.0).all()
    assert wp.loc[wp["produkt"] == "WP-1", "investkosten"].iloc[0] == pytest.approx(10000.0 + 500.0)


def test_transportkosten_werden_verwendet_wenn_vorhanden(tmp_path):
    spalten = _basis_spalten()
    spalten["Transportkosten [Euro]"] = [200.0, 300.0]
    wp = lade_wp_katalog(_schreibe(tmp_path, spalten)).katalog
    assert wp.loc[wp["produkt"] == "WP-1", "investkosten"].iloc[0] == pytest.approx(10000.0 + 500.0 + 200.0)


def test_vl_max_optional(tmp_path):
    spalten = _basis_spalten()
    wp_ohne = lade_wp_katalog(_schreibe(tmp_path, spalten, name="ohne.xlsx")).katalog
    assert wp_ohne["vl_max_c"].isna().all()

    spalten["max. Vorlauftemperatur [°C]"] = [65.0, 65.0]
    wp_mit = lade_wp_katalog(_schreibe(tmp_path, spalten, name="mit.xlsx")).katalog
    assert list(wp_mit["vl_max_c"]) == [65.0, 65.0]


def test_fehlende_w35_spalte_wirft_fehler(tmp_path):
    spalten = _basis_spalten()
    del spalten["Leistung B0/W35 [kW]"]
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(_schreibe(tmp_path, spalten))


def test_fehlende_ibn_spalte_wirft_fehler(tmp_path):
    spalten = _basis_spalten()
    del spalten["Inbetriebnahme 2026 [Euro]"]
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(_schreibe(tmp_path, spalten))


def test_fehlende_abmessung_wirft_fehler(tmp_path):
    spalten = _basis_spalten()
    del spalten["Breite [mm]"]
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(_schreibe(tmp_path, spalten))


def test_unbekannter_betriebspunkt_wirft_fehler(tmp_path):
    pfad = _schreibe(tmp_path, _basis_spalten())
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(pfad, betriebspunkt="W99")


def test_leere_zelle_in_pflichtfeld_wird_uebersprungen_mit_warnung(tmp_path):
    spalten = _basis_spalten()
    spalten["Listenpreis 2026 [Euro]"] = [10000.0, None]
    erg = lade_wp_katalog(_schreibe(tmp_path, spalten))
    assert list(erg.katalog["produkt"]) == ["WP-1"]
    assert len(erg.warnungen) == 1
    assert "WP-2" in erg.warnungen[0]


def test_leistung_kleiner_gleich_null_wird_uebersprungen_mit_warnung(tmp_path):
    spalten = _basis_spalten()
    spalten["Leistung B0/W55 [kW]"] = [30.0, 0.0]
    erg = lade_wp_katalog(_schreibe(tmp_path, spalten))
    assert list(erg.katalog["produkt"]) == ["WP-1"]
    assert len(erg.warnungen) == 1


def test_alle_zeilen_unvollstaendig_wirft_fehler(tmp_path):
    spalten = _basis_spalten()
    spalten["Listenpreis 2026 [Euro]"] = [None, None]
    with pytest.raises(KatalogFehler):
        lade_wp_katalog(_schreibe(tmp_path, spalten))


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_betriebspunkt_w55_ist_default(tmp)
        test_betriebspunkt_w35_waehlbar(tmp)
        test_platzbedarf_aus_hbl_berechnet(tmp)
        test_listenpreis_2026_wird_bevorzugt_vor_quelle_spalte(tmp)
        test_transportkosten_optional_default_null(tmp)
        test_transportkosten_werden_verwendet_wenn_vorhanden(tmp)
        test_vl_max_optional(tmp)
        test_fehlende_w35_spalte_wirft_fehler(tmp)
        test_fehlende_ibn_spalte_wirft_fehler(tmp)
        test_fehlende_abmessung_wirft_fehler(tmp)
        test_unbekannter_betriebspunkt_wirft_fehler(tmp)
        test_leere_zelle_in_pflichtfeld_wird_uebersprungen_mit_warnung(tmp)
        test_leistung_kleiner_gleich_null_wird_uebersprungen_mit_warnung(tmp)
        test_alle_zeilen_unvollstaendig_wirft_fehler(tmp)
    print("Alle WP-Katalog-Tests erfolgreich.")
