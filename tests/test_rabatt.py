import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from core.rabatt import wende_wp_rabatt_an, wende_speicher_rabatt_an


def test_wp_rabatt_nur_auf_listenpreis():
    df = pd.DataFrame({
        "hersteller": ["A", "B"],
        "listenpreis": [10000.0, 20000.0],
        "ibn_kosten": [500.0, 600.0],
        "transport_kosten": [200.0, 300.0],
        "investkosten": [10700.0, 20900.0],
    })
    rabattiert = wende_wp_rabatt_an(df, {"A": 10.0})

    # A: 10 % auf Listenpreis, IBN/Transport unverändert
    assert rabattiert.loc[0, "listenpreis_rabattiert"] == pytest.approx(9000.0)
    assert rabattiert.loc[0, "investkosten"] == pytest.approx(9000.0 + 500.0 + 200.0)
    # B: kein Rabatt hinterlegt -> unverändert
    assert rabattiert.loc[1, "investkosten"] == pytest.approx(20900.0)
    # Original bleibt unangetastet (Funktion arbeitet auf einer Kopie)
    assert df.loc[0, "investkosten"] == 10700.0


def test_speicher_rabatt_auf_nettokosten():
    df = pd.DataFrame({
        "hersteller": ["C", "D"],
        "nettokosten": [4000.0, 5200.0],
        "investkosten": [4000.0, 5200.0],
    })
    rabattiert = wende_speicher_rabatt_an(df, {"C": 15.0, "D": 0.0})

    assert rabattiert.loc[0, "investkosten"] == pytest.approx(4000.0 * 0.85)
    assert rabattiert.loc[1, "investkosten"] == pytest.approx(5200.0)


def test_rabatt_ohne_eintrag_ist_null():
    df = pd.DataFrame({
        "hersteller": ["X"],
        "listenpreis": [1000.0], "ibn_kosten": [0.0], "transport_kosten": [0.0],
        "investkosten": [1000.0],
    })
    rabattiert = wende_wp_rabatt_an(df, {})
    assert rabattiert.loc[0, "investkosten"] == pytest.approx(1000.0)


if __name__ == "__main__":
    test_wp_rabatt_nur_auf_listenpreis()
    test_speicher_rabatt_auf_nettokosten()
    test_rabatt_ohne_eintrag_ist_null()
    print("Alle Rabatt-Tests erfolgreich.")
