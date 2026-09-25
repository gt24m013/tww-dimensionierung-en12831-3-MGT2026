import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.lastprofil import LastprofilFehler, lies_csv

BEISPIEL = Path(__file__).resolve().parents[1] / "beispiele" / "demo_zapfprofil.csv"


def datei(text: str, name: str = "profil.csv"):
    puffer = io.BytesIO(text.encode("utf-8"))
    puffer.name = name
    return puffer


def test_mitgeliefertes_beispiel_laesst_sich_lesen():
    name, werte = lies_csv(BEISPIEL)
    assert len(werte) == 24
    assert abs(sum(werte) - 100.0) < 0.5
    assert "demo_zapfprofil" in name


def test_stundenspalte_wird_verworfen():
    text = "stunde;anteil\n" + "\n".join(f"{h};{h + 1}" for h in range(24))
    _, werte = lies_csv(datei(text))
    assert werte == [float(h + 1) for h in range(24)]


def test_werte_ohne_kopfzeile_und_ohne_stundenspalte():
    text = "\n".join(str(h + 1) for h in range(24))
    _, werte = lies_csv(datei(text))
    assert werte == [float(h + 1) for h in range(24)]


def test_alle_werte_in_einer_zeile():
    _, werte = lies_csv(datei(";".join(str(h + 1) for h in range(24))))
    assert werte == [float(h + 1) for h in range(24)]


def test_dezimalkomma_wird_erkannt():
    text = "\n".join(f"{h};1,5" for h in range(24))
    _, werte = lies_csv(datei(text))
    assert werte == [1.5] * 24


def test_name_wird_aus_dem_dateinamen_abgeleitet():
    text = "\n".join("1" for _ in range(24))
    name, _ = lies_csv(datei(text, name="Mein Profil.csv"))
    assert name == "Mein Profil (geladen) [%]"


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("\n".join("1" for _ in range(23)), "23"),          # zu wenige Werte
        ("\n".join("1" for _ in range(25)), "25"),          # zu viele Werte
        ("\n".join("0" for _ in range(24)), "größer als 0"),  # Summe null
        ("\n".join("-1" for _ in range(24)), "Negative"),   # negative Anteile
        ("", "leer"),
    ],
)
def test_fehlerhafte_dateien_werden_abgewiesen(text, fragment):
    with pytest.raises(LastprofilFehler, match=fragment):
        lies_csv(datei(text))
