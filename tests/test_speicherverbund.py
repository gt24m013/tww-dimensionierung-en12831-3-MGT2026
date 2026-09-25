import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.modell import Eingabedaten
from core.bedarf import zapfprofil_minutenwerte
from core.versorgung import berechne_versorgungskennlinie, q_sto_max, q_sto_on
from core.speicherverbund import (
    Speicherverbund, SpeicherverbundFehler, SERIE, PARALLEL,
    FUEHLER_ZAPFSEITIG, FUEHLER_ERSTER,
)


def test_einzelspeicher_bleibt_unveraendert():
    """anzahl = 1 muss exakt die bisherige Eingabe reproduzieren."""
    v = Speicherverbund(anzahl=1, v_je_speicher=3000.0, h_je_speicher=2.0,
                        h_sensor_je_speicher=0.6, q_sb_je_speicher=3.48)
    assert not v.ist_verbund
    assert (v.v_sto, v.h_sto, v.h_sensor, v.q_sb_sto) == (3000.0, 2.0, 0.6, 3.48)
    assert v.einbauhoehe_fuehler == pytest.approx(1.4)


def test_serie_stapelt_die_hoehen():
    # 2 x 1500 l, je 2 m hoch, Fühler 0,6 m unter dem Deckel des zapfseitigen Speichers
    v = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                        h_sensor_je_speicher=0.6, q_sb_je_speicher=2.19, schaltung=SERIE)
    assert v.v_sto == pytest.approx(3000.0)
    assert v.h_sto == pytest.approx(4.0)           # Schichtung läuft durch beide Gefäße
    assert v.h_sensor == pytest.approx(0.6)        # zapfseitige Oberkante = Oberkante des Verbunds
    assert v.q_sb_sto == pytest.approx(4.38)       # Summe der Einzelverluste
    # Real messbare Einbauhöhe bleibt die im jeweiligen Speicher, nicht h_sto - h_sensor
    assert v.einbauhoehe_fuehler == pytest.approx(1.4)


def test_serie_mit_fuehler_im_ersten_speicher_liegt_tiefer_im_stapel():
    v = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                        h_sensor_je_speicher=0.6, q_sb_je_speicher=2.19,
                        schaltung=SERIE, fuehler_position=FUEHLER_ERSTER)
    # (n-1) * h + Fühlertiefe im Gefäß = 2,0 + 0,6
    assert v.h_sensor == pytest.approx(2.6)
    assert v.einbauhoehe_fuehler == pytest.approx(1.4)  # unverändert real 1,4 m über dem Boden


def test_parallel_behaelt_die_einzelhoehe():
    """Parallel entschichten alle Speicher synchron -> Verhältnis wie im Einzelspeicher."""
    v = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                        h_sensor_je_speicher=0.6, q_sb_je_speicher=2.19, schaltung=PARALLEL)
    assert v.v_sto == pytest.approx(3000.0)
    assert v.h_sto == pytest.approx(2.0)
    assert v.h_sensor == pytest.approx(0.6)
    assert v.h_sensor / v.h_sto == pytest.approx(0.3)


def test_parallel_entspricht_einem_einzelspeicher_gleichen_volumens():
    """Nur der Bereitschaftsverlust unterscheidet die Parallelschaltung vom
    Einzelspeicher - das Einschaltverhalten ist identisch."""
    einzeln = Eingabedaten(v_sto=3000.0, h_sto=2.0, h_sensor=0.6)
    parallel = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                               h_sensor_je_speicher=0.6, q_sb_je_speicher=1.74,
                               schaltung=PARALLEL)
    verbund_daten = Eingabedaten(v_sto=parallel.v_sto, h_sto=parallel.h_sto,
                                 h_sensor=parallel.h_sensor, q_sb_sto=parallel.q_sb_sto)
    assert q_sto_max(verbund_daten) == pytest.approx(q_sto_max(einzeln))
    assert q_sto_on(verbund_daten) == pytest.approx(q_sto_on(einzeln))


def test_serie_schaltet_frueher_ein_als_ein_einzelspeicher():
    """Kernaussage des Verbundmodells: bei Serienschaltung verschiebt sich der
    Einschaltpunkt (Gl. 10), weil h_sensor/h_sto kleiner wird - die WP taktet
    häufiger, obwohl Volumen und Leistung gleich bleiben."""
    basis = Eingabedaten()
    zapf = zapfprofil_minutenwerte(basis)

    einzeln = Eingabedaten(v_sto=3000.0, h_sto=2.0, h_sensor=0.6, q_sb_sto=3.48)
    serie = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                            h_sensor_je_speicher=0.6, q_sb_je_speicher=2.19,
                            schaltung=SERIE, fuehler_position=FUEHLER_ZAPFSEITIG)
    verbund_daten = Eingabedaten(v_sto=serie.v_sto, h_sto=serie.h_sto,
                                 h_sensor=serie.h_sensor, q_sb_sto=serie.q_sb_sto)

    assert q_sto_max(verbund_daten) == pytest.approx(q_sto_max(einzeln))  # gleiches Volumen
    assert q_sto_on(verbund_daten) > q_sto_on(einzeln)                    # aber früherer Start
    zyklen_einzeln = len(berechne_versorgungskennlinie(einzeln, zapf).zyklen)
    zyklen_serie = len(berechne_versorgungskennlinie(verbund_daten, zapf).zyklen)
    assert zyklen_serie > zyklen_einzeln


def test_unzulaessige_eingaben():
    with pytest.raises(SpeicherverbundFehler):
        Speicherverbund(anzahl=0)
    with pytest.raises(SpeicherverbundFehler):
        Speicherverbund(schaltung="Reihe")
    with pytest.raises(SpeicherverbundFehler):
        Speicherverbund(fuehler_position="oben")
