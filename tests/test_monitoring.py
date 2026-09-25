import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from core.monitoring import lade_zapfprofil, MonitoringDatenFehler, MINUTEN_PRO_TAG


def _schreibe_excel(tmp_path, werte, spaltenname="Zapfprofil in Liter"):
    pfad = tmp_path / "test.xlsx"
    pd.DataFrame({spaltenname: werte}).to_excel(pfad, index=False)
    return pfad


def _schreibe_excel_mit_zeit(tmp_path, zeitstempel, werte, dateiname="test_zeit.xlsx"):
    pfad = tmp_path / dateiname
    df = pd.DataFrame({
        "Datum": [t.strftime("%d.%m.%Y") for t in zeitstempel],
        "Uhrzeit": [t.strftime("%H:%M:%S") for t in zeitstempel],
        "Zählerstand in Liter": np.cumsum(werte),
        "Zapfprofil in Liter": werte,
    })
    df.to_excel(pfad, index=False)
    return pfad


def test_1min_aufloesung(tmp_path):
    werte = [1.0] * MINUTEN_PRO_TAG
    pfad = _schreibe_excel(tmp_path, werte)
    erg = lade_zapfprofil(pfad, "1min")
    assert len(erg.zapfprofil_l_min) == MINUTEN_PRO_TAG
    assert erg.zapfprofil_l_min.sum() == pytest.approx(1440.0)


def test_5min_aufloesung_gleichverteilt(tmp_path):
    werte = [5.0] * (MINUTEN_PRO_TAG // 5)  # 5 l alle 5 min
    pfad = _schreibe_excel(tmp_path, werte)
    erg = lade_zapfprofil(pfad, "5min")
    assert len(erg.zapfprofil_l_min) == MINUTEN_PRO_TAG
    # 5 l je 5-Minuten-Block -> 1 l/min gleichverteilt
    assert np.allclose(erg.zapfprofil_l_min, 1.0)
    assert erg.zapfprofil_l_min.sum() == pytest.approx(sum(werte))


def test_falsche_spalte(tmp_path):
    pfad = _schreibe_excel(tmp_path, [1.0] * MINUTEN_PRO_TAG, spaltenname="Falsch")
    with pytest.raises(MonitoringDatenFehler):
        lade_zapfprofil(pfad, "1min")


def test_falsche_laenge(tmp_path):
    pfad = _schreibe_excel(tmp_path, [1.0] * 100)
    with pytest.raises(MonitoringDatenFehler):
        lade_zapfprofil(pfad, "1min")


def test_zeitstempel_regelmaessig_keine_warnung(tmp_path):
    start = datetime(2026, 6, 21, 0, 0, 0)
    zeiten = [start + timedelta(minutes=5 * i) for i in range(288)]
    pfad = _schreibe_excel_mit_zeit(tmp_path, zeiten, [5.0] * 288)
    erg = lade_zapfprofil(pfad, "5min")
    assert erg.warnungen == []


def test_zeitstempel_nicht_sortiert(tmp_path):
    start = datetime(2026, 6, 21, 0, 0, 0)
    zeiten = [start + timedelta(minutes=5 * i) for i in range(288)]
    zeiten[10], zeiten[11] = zeiten[11], zeiten[10]  # vertauscht -> nicht mehr sortiert
    pfad = _schreibe_excel_mit_zeit(tmp_path, zeiten, [5.0] * 288)
    with pytest.raises(MonitoringDatenFehler):
        lade_zapfprofil(pfad, "5min")


def test_zeitstempel_duplikat(tmp_path):
    start = datetime(2026, 6, 21, 0, 0, 0)
    zeiten = [start + timedelta(minutes=5 * i) for i in range(288)]
    zeiten[5] = zeiten[4]  # Duplikat
    pfad = _schreibe_excel_mit_zeit(tmp_path, zeiten, [5.0] * 288)
    with pytest.raises(MonitoringDatenFehler):
        lade_zapfprofil(pfad, "5min")


def test_zeitstempel_luecke_nur_warnung(tmp_path):
    start = datetime(2026, 6, 21, 0, 0, 0)
    zeiten = [start + timedelta(minutes=5 * i) for i in range(288)]
    zeiten = zeiten[:20] + [t + timedelta(minutes=15) for t in zeiten[20:]]  # 15-min-Lücke ab Index 20
    pfad = _schreibe_excel_mit_zeit(tmp_path, zeiten, [5.0] * 288)
    erg = lade_zapfprofil(pfad, "5min")  # darf nicht crashen, nur warnen
    assert len(erg.warnungen) >= 1
    assert "Lücke" in erg.warnungen[0] or "unregelmäßige" in erg.warnungen[0]


def test_ohne_zeitstempel_spalten_keine_pruefung(tmp_path):
    pfad = _schreibe_excel(tmp_path, [1.0] * MINUTEN_PRO_TAG)
    erg = lade_zapfprofil(pfad, "1min")
    assert erg.warnungen == []


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_1min_aufloesung(tmp)
        test_5min_aufloesung_gleichverteilt(tmp)
        test_falsche_spalte(tmp)
        test_falsche_laenge(tmp)
        test_zeitstempel_regelmaessig_keine_warnung(tmp)
        test_zeitstempel_nicht_sortiert(tmp)
        test_zeitstempel_duplikat(tmp)
        test_zeitstempel_luecke_nur_warnung(tmp)
        test_ohne_zeitstempel_spalten_keine_pruefung(tmp)
    print("Alle Monitoring-Tests erfolgreich.")
