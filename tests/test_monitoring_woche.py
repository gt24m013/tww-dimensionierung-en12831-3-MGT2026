import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from core.monitoring import (
    lade_wochenzapfprofil, WochenMonitoringDatenFehler, MINUTEN_PRO_TAG,
)


def _tagesblatt_df(tag_start: datetime, werte, aufloesung_minuten: int):
    n = len(werte)
    zeiten = [tag_start + timedelta(minutes=aufloesung_minuten * i) for i in range(n)]
    return pd.DataFrame({
        "Datum": [t.strftime("%d.%m.%Y") for t in zeiten],
        "Uhrzeit": [t.strftime("%H:%M:%S") for t in zeiten],
        "Zapfprofil in Liter": werte,
    })


def _schreibe_wochen_excel(tmp_path, anzahl_tage=7, aufloesung="1min", name="woche.xlsx"):
    pfad = tmp_path / name
    schritt_min = 1 if aufloesung == "1min" else 5
    n = MINUTEN_PRO_TAG if aufloesung == "1min" else MINUTEN_PRO_TAG // 5
    start = datetime(2026, 6, 15)  # ein Montag
    with pd.ExcelWriter(pfad) as writer:
        for tag in range(anzahl_tage):
            tag_start = start + timedelta(days=tag)
            werte = [1.0] * n
            df = _tagesblatt_df(tag_start, werte, schritt_min)
            df.to_excel(writer, sheet_name=f"Tag{tag + 1}", index=False)
    return pfad


def test_wochenzapfprofil_laenge_und_reihenfolge(tmp_path):
    pfad = _schreibe_wochen_excel(tmp_path, anzahl_tage=7, aufloesung="1min")
    erg = lade_wochenzapfprofil(pfad, "1min")
    assert erg.anzahl_tage == 7
    assert len(erg.zapfprofil_l_min) == 7 * MINUTEN_PRO_TAG
    assert erg.tagesblaetter == [f"Tag{i + 1}" for i in range(7)]
    assert erg.warnungen == []


def test_wochenzapfprofil_5min_aufloesung(tmp_path):
    pfad = _schreibe_wochen_excel(tmp_path, anzahl_tage=3, aufloesung="5min")
    erg = lade_wochenzapfprofil(pfad, "5min")
    assert erg.anzahl_tage == 3
    assert len(erg.zapfprofil_l_min) == 3 * MINUTEN_PRO_TAG


def test_nur_ein_blatt_wirft_fehler(tmp_path):
    pfad = tmp_path / "einzeln.xlsx"
    df = _tagesblatt_df(datetime(2026, 6, 15), [1.0] * MINUTEN_PRO_TAG, 1)
    df.to_excel(pfad, sheet_name="NurEinTag", index=False)
    with pytest.raises(WochenMonitoringDatenFehler):
        lade_wochenzapfprofil(pfad, "1min")


def test_fehler_in_einem_blatt_wird_durchgereicht(tmp_path):
    pfad = tmp_path / "fehlerhaft.xlsx"
    with pd.ExcelWriter(pfad) as writer:
        df_ok = _tagesblatt_df(datetime(2026, 6, 15), [1.0] * MINUTEN_PRO_TAG, 1)
        df_ok.to_excel(writer, sheet_name="Tag1", index=False)
        df_falsch = pd.DataFrame({"Falsch": [1, 2, 3]})
        df_falsch.to_excel(writer, sheet_name="Tag2", index=False)
    with pytest.raises(WochenMonitoringDatenFehler, match="Tag2"):
        lade_wochenzapfprofil(pfad, "1min")


def test_datei_mehrfach_lesbar_als_dateihandle(tmp_path):
    """Regressionstest: das Datei-Objekt darf nicht nach dem ersten Blatt
    'verbraucht' sein (Streamlit-UploadedFile-artiges Verhalten)."""
    pfad = _schreibe_wochen_excel(tmp_path, anzahl_tage=2, aufloesung="1min")
    with open(pfad, "rb") as f:
        erg = lade_wochenzapfprofil(f, "1min")
    assert erg.anzahl_tage == 2
    assert len(erg.zapfprofil_l_min) == 2 * MINUTEN_PRO_TAG


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_wochenzapfprofil_laenge_und_reihenfolge(tmp)
        test_wochenzapfprofil_5min_aufloesung(tmp)
        test_nur_ein_blatt_wirft_fehler(tmp)
        test_fehler_in_einem_blatt_wird_durchgereicht(tmp)
        test_datei_mehrfach_lesbar_als_dateihandle(tmp)
    print("Alle Wochenmonitoring-Tests erfolgreich.")
