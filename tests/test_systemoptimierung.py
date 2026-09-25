import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from core.modell import Eingabedaten
from core.bedarf import zapfprofil_minutenwerte
from core.kostenfunktion import (
    wp_kostenfunktion, wp_kostenfunktion_listenpreis, wp_kostenfunktion_inkl_ibn,
    passe_potenzfunktion_an, speicher_kostenfunktion, KostenfunktionFehler,
)
from core.montage import wende_speicher_montage_an
from core.systemoptimierung import (
    optimiere_raster, guenstigster_punkt, kleinste_leistung, kleinstes_volumen, bewerte_anlagen,
)


def test_wp_kostenfunktion_listenpreis_ist_fit_nur_auf_listenpreis():
    df = pd.DataFrame({
        "leistung_kw": [100, 400, 900, 1600],
        "listenpreis": [1000, 2000, 3000, 4000],
        "ibn_kosten": [40, 80, 120, 160],
    })
    f = wp_kostenfunktion_listenpreis(df)
    assert f.koeffizient_a == pytest.approx(100, rel=1e-6)
    assert f.exponent_b == pytest.approx(0.5, rel=1e-6)


def test_wp_kostenfunktion_inkl_ibn_summiert_listenpreis_und_ibn():
    # Listenpreis: K(x) = 100 * x^0.5, IBN: K(x) = 4 * x^0.5 - beide mit demselben Exponenten,
    # damit die Summe exakt wieder eine Potenzfunktion K(x) = 104 * x^0.5 ist (gemeinsamer Fit).
    df = pd.DataFrame({
        "leistung_kw": [100, 400, 900, 1600],
        "listenpreis": [1000, 2000, 3000, 4000],
        "ibn_kosten": [40, 80, 120, 160],
    })
    f = wp_kostenfunktion_inkl_ibn(df)
    assert f.koeffizient_a == pytest.approx(104, rel=1e-6)
    assert f.exponent_b == pytest.approx(0.5, rel=1e-6)


def test_wp_kostenfunktion_ist_gemeinsamer_fit_inkl_montage():
    df = pd.DataFrame({
        "leistung_kw": [100, 400, 900, 1600],
        "listenpreis": [1000, 2000, 3000, 4000],
        "ibn_kosten": [40, 80, 120, 160],
    })
    # Ohne Montage reduziert sich Fit 3 auf denselben Fit wie Fit 2.
    f_ohne_montage = wp_kostenfunktion(df, montagekosten=0.0)
    assert f_ohne_montage.koeffizient_a == pytest.approx(104, rel=1e-6)
    assert f_ohne_montage.exponent_b == pytest.approx(0.5, rel=1e-6)

    # Mit Montage: EIN gemeinsamer Fit auf (Listenpreis+IBN+Montage) - die Montage-Konstante
    # fließt VOR dem Fit mit ein, statt hinterher separat addiert zu werden.
    f_mit_montage = wp_kostenfunktion(df, montagekosten=500.0)
    x = df["leistung_kw"].to_numpy(dtype=float)
    erwartete_summe = df["listenpreis"].to_numpy(dtype=float) + df["ibn_kosten"].to_numpy(dtype=float) + 500.0
    erwartet = passe_potenzfunktion_an(x, erwartete_summe)
    assert f_mit_montage.koeffizient_a == pytest.approx(erwartet.koeffizient_a)
    assert f_mit_montage.exponent_b == pytest.approx(erwartet.exponent_b)
    # Kein exakter Aufschlag von 500 € mehr, weil die Konstante schon vor dem Fit einfließt.
    assert f_mit_montage.koeffizient_a != pytest.approx(104, rel=1e-3)


def test_speicher_kostenfunktion_mit_materialfilter():
    df = pd.DataFrame({
        "volumen_l": [1000, 2000, 3000, 2000],
        "material": ["Stahl emailliert", "Stahl emailliert", "Stahl emailliert", "Edelstahl"],
        "investkosten": [2500, 4000, 5500, 5200],
    })
    f_emailliert = speicher_kostenfunktion(df, "Stahl emailliert")
    assert f_emailliert.stuetzstellen == 3
    with pytest.raises(KostenfunktionFehler):
        speicher_kostenfunktion(df, "Edelstahl")  # nur 1 Datenpunkt -> zu wenig für Regression


def test_speicher_montage_wird_auf_bereits_rabattierte_kosten_angewendet():
    # wende_speicher_montage_an() setzt eine bereits rabattierte 'investkosten'-Spalte voraus
    # (core/rabatt.py muss vorher aufgerufen worden sein) und schlägt den Prozentsatz darauf auf.
    df = pd.DataFrame({"volumen_l": [1000, 2000], "investkosten": [1000.0, 2000.0]})
    df_montage = wende_speicher_montage_an(df, montage_pct=20.0)
    assert df_montage["montage_kosten"].tolist() == pytest.approx([200.0, 400.0])
    assert df_montage["investkosten"].tolist() == pytest.approx([1200.0, 2400.0])


def test_speicher_montage_prozentsatz_wirkt_rein_multiplikativ_auf_den_fit():
    df = pd.DataFrame({"volumen_l": [1000, 2000, 3000], "investkosten": [2500, 4000, 5500]})
    df_mit_montage = wende_speicher_montage_an(df, montage_pct=10.0)

    f_ohne = speicher_kostenfunktion(df)
    f_mit = speicher_kostenfunktion(df_mit_montage)
    # Ein Prozentsatz auf bereits rabattierte Kosten skaliert alle Stützstellen um denselben
    # Faktor -> im log-log-Fit bleibt der Exponent unverändert, nur der Vorfaktor wächst um 1.1.
    assert f_mit.exponent_b == pytest.approx(f_ohne.exponent_b)
    assert f_mit.koeffizient_a == pytest.approx(f_ohne.koeffizient_a * 1.1)


def test_kostenfunktion_zu_wenig_daten():
    df = pd.DataFrame({"leistung_kw": [10], "listenpreis": [3000], "ibn_kosten": [100]})
    with pytest.raises(KostenfunktionFehler):
        wp_kostenfunktion(df)


def test_optimiere_raster_liefert_plausible_ergebnisse():
    daten = Eingabedaten()
    zapf = zapfprofil_minutenwerte(daten)

    wp_df = pd.DataFrame({
        "leistung_kw": [30, 50, 80, 100],
        "listenpreis": [10000, 13800, 19700, 24400],
        "ibn_kosten": [700, 900, 1200, 1500],
    })
    sp_df = pd.DataFrame({"volumen_l": [1000, 2000, 3000, 4000], "investkosten": [2500, 4000, 5500, 7000]})
    wp_f = wp_kostenfunktion(wp_df)
    sp_f = speicher_kostenfunktion(sp_df)

    punkte = optimiere_raster(
        daten, zapf, wp_f, sp_f,
        v_sto_referenz=daten.v_sto, phi_n_referenz=daten.phi_n,
        max_laufzeit_h=24, raster_schritte=8,
    )
    assert len(punkte) == 64

    beste = guenstigster_punkt(punkte)
    if beste is not None:
        zulaessige = [p for p in punkte if p.zulaessig]
        assert beste.kosten == min(p.kosten for p in zulaessige)

        kl_leistung = kleinste_leistung(punkte)
        kl_volumen = kleinstes_volumen(punkte)
        assert kl_leistung.phi_n == min(p.phi_n for p in zulaessige)
        assert kl_volumen.v_sto == min(p.v_sto for p in zulaessige)


def test_bewerte_anlagen_bezieht_alle_zeilen_auf_den_ausgangszustand():
    # Einfache Kostenfunktionen, damit die erwarteten Kosten von Hand nachrechenbar sind:
    # WP 100 €/kW, Speicher 1 €/l.
    wp_f, sp_f = (lambda phi: 100.0 * phi), (lambda v: 1.0 * v)
    anlagen = bewerte_anlagen(
        [
            ("Normauslegung (Modus A)", 3000.0, 70.0),   # 3000 + 7000 = 10000 €
            ("Reales Monitoring (Modus B)", 2000.0, 60.0),  # 2000 + 6000 =  8000 €
            ("Kostenoptimum (Modus E)", 4000.0, 80.0),   # 4000 + 8000 = 12000 €
        ],
        wp_f, sp_f,
    )
    norm, monitoring, optimum = anlagen

    assert norm.ist_ausgangszustand and not monitoring.ist_ausgangszustand
    assert norm.wp_kosten == pytest.approx(7000.0)
    assert norm.speicher_kosten == pytest.approx(3000.0)
    assert norm.gesamtkosten == pytest.approx(10000.0)
    # Der Ausgangszustand hat definitionsgemäß keine Abweichung zu sich selbst.
    assert norm.diff_abs == pytest.approx(0.0)
    assert norm.diff_pct == pytest.approx(0.0)

    # Minderkosten gegenüber dem Ausgangszustand: -2000 € = -20 %
    assert monitoring.diff_abs == pytest.approx(-2000.0)
    assert monitoring.diff_pct == pytest.approx(-20.0)
    # Mehrkosten gegenüber dem Ausgangszustand: +2000 € = +20 %
    assert optimum.diff_abs == pytest.approx(2000.0)
    assert optimum.diff_pct == pytest.approx(20.0)


def test_bewerte_anlagen_nutzt_dieselben_kosten_wie_das_raster():
    daten = Eingabedaten()
    zapf = zapfprofil_minutenwerte(daten)
    wp_df = pd.DataFrame({
        "leistung_kw": [30, 50, 80, 100],
        "listenpreis": [10000, 13800, 19700, 24400],
        "ibn_kosten": [700, 900, 1200, 1500],
    })
    sp_df = pd.DataFrame({"volumen_l": [1000, 2000, 3000, 4000], "investkosten": [2500, 4000, 5500, 7000]})
    wp_f, sp_f = wp_kostenfunktion(wp_df), speicher_kostenfunktion(sp_df)

    punkte = optimiere_raster(
        daten, zapf, wp_f, sp_f,
        v_sto_referenz=daten.v_sto, phi_n_referenz=daten.phi_n,
        max_laufzeit_h=24, raster_schritte=6,
    )
    punkt = punkte[0]
    bewertet = bewerte_anlagen([("Rasterpunkt", punkt.v_sto, punkt.phi_n)], wp_f, sp_f)[0]
    assert bewertet.gesamtkosten == pytest.approx(punkt.kosten)


if __name__ == "__main__":
    test_wp_kostenfunktion_summiert_listenpreis_ibn_und_montage()
    test_speicher_kostenfunktion_mit_materialfilter()
    test_kostenfunktion_zu_wenig_daten()
    test_optimiere_raster_liefert_plausible_ergebnisse()
    print("Alle Systemoptimierungs-Tests erfolgreich.")
