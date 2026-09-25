"""Montagekosten als zusätzlicher, von den Katalog-Listenpreisen unabhängiger
Investitionskostenbestandteil.

Bei Wärmepumpen eine über alle Leistungsbereiche konstante, vom Nutzer im
Tool eingegebene Pauschale (Montageaufwand variiert bei WP kaum mit der
Leistung). Bei Speichern ein vom Nutzer im Tool eingegebener Prozentsatz auf
die bereits rabattierten Investkosten (core.rabatt.wende_speicher_rabatt_an
muss also VOR dieser Funktion aufgerufen werden) - Speichermontage wird in
der Praxis meist als Anteil der (rabattierten) Anschaffungskosten
kalkuliert, nicht als von diesen unabhängige Pauschale.

Analog zu core/rabatt.py: beide Funktionen geben eine Kopie des jeweiligen
Katalogs mit neu berechneten Investkosten zurück, statt die Montagekosten
in core/katalog.py fest einzurechnen - so bleibt die Montagepauschale ein
unabhängig einstellbarer Bestandteil (WP: € pauschal; Speicher: % auf den
rabattierten Listenpreis), ohne die Rohdaten aus dem Katalog zu verändern.
"""

import pandas as pd


def wende_wp_montage_an(wp_katalog: pd.DataFrame, montagekosten: float) -> pd.DataFrame:
    """Gibt eine Kopie des WP-Katalogs zurück, bei der `montagekosten` (eine
    über alle Leistungsbereiche konstante Pauschale [€]) zusätzlich in die
    Investkosten einfließt."""
    df = wp_katalog.copy()
    df["montage_kosten"] = float(montagekosten)
    df["investkosten"] = df["investkosten"] + df["montage_kosten"]
    return df


def wende_speicher_montage_an(speicher_katalog: pd.DataFrame, montage_pct: float) -> pd.DataFrame:
    """Gibt eine Kopie des Speicher-Katalogs zurück, bei der `montage_pct` [%]
    der bereits rabattierten Investkosten (Spalte 'investkosten', siehe
    core.rabatt.wende_speicher_rabatt_an) zusätzlich als Montagekosten
    einfließen."""
    df = speicher_katalog.copy()
    df["montage_kosten"] = df["investkosten"] * (float(montage_pct) / 100.0)
    df["investkosten"] = df["investkosten"] + df["montage_kosten"]
    return df
