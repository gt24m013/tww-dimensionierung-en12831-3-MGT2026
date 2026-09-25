import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.modell import Eingabedaten
from core.bedarf import zapfprofil_minutenwerte
from core.versorgung import berechne_versorgungskennlinie
from core.vergleich import vergleiche


def test_identische_profile_ergeben_keine_warnung_und_null_abweichung():
    daten = Eingabedaten()
    zapf = zapfprofil_minutenwerte(daten)
    erg = berechne_versorgungskennlinie(daten, zapf)

    v = vergleiche(zapf, erg, zapf, erg)
    assert v.diff_vol_pct == 0.0
    assert v.diff_energie_pct == 0.0
    assert v.zyklen_soll == v.zyklen_ist
    assert v.warnungen == []


def test_unterdimensionierung_wird_erkannt():
    daten = Eingabedaten(speicher_typ="Gemischtes Speichersystem", v_sto=200, phi_n=5)
    zapf = zapfprofil_minutenwerte(daten)
    erg = berechne_versorgungskennlinie(daten, zapf)

    v = vergleiche(zapf, erg, zapf, erg)
    if erg.ladezustand.min() < erg.q_sto_min:
        assert any("UNTERDIMENSIONIERUNG" in w for w in v.warnungen)


if __name__ == "__main__":
    test_identische_profile_ergeben_keine_warnung_und_null_abweichung()
    test_unterdimensionierung_wird_erkannt()
    print("Alle Vergleichs-Tests erfolgreich.")
