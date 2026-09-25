"""Herstellerspezifische Rabattgruppen auf die Katalog-Listenpreise.

Rabatte werden je Hersteller in Prozent angegeben und nur auf den
rabattfähigen Preisanteil angewendet - bei Wärmepumpen der Listenpreis
(nicht Inbetriebnahme-/Transportkosten, die i. d. R. nicht Teil der
Rabattstaffel des Herstellers sind), bei Speichern die Nettokosten.
Hersteller ohne hinterlegten Rabatt bleiben unrabattiert (0 %).
"""

import pandas as pd


def wende_wp_rabatt_an(wp_katalog: pd.DataFrame, rabatte: dict[str, float]) -> pd.DataFrame:
    """Gibt eine Kopie des WP-Katalogs mit rabattiertem Listenpreis zurück.

    rabatte: {Hersteller: Rabatt in %}.
    """
    df = wp_katalog.copy()
    rabatt_pct = df["hersteller"].map(lambda h: rabatte.get(h, 0.0)).astype(float)
    df["rabatt_pct"] = rabatt_pct
    df["listenpreis_rabattiert"] = df["listenpreis"] * (1 - rabatt_pct / 100.0)
    df["investkosten"] = df["listenpreis_rabattiert"] + df["ibn_kosten"] + df["transport_kosten"]
    return df


def wende_speicher_rabatt_an(speicher_katalog: pd.DataFrame, rabatte: dict[str, float]) -> pd.DataFrame:
    """Gibt eine Kopie des Speicher-Katalogs mit rabattierten Nettokosten zurück."""
    df = speicher_katalog.copy()
    rabatt_pct = df["hersteller"].map(lambda h: rabatte.get(h, 0.0)).astype(float)
    df["rabatt_pct"] = rabatt_pct
    df["nettokosten_rabattiert"] = df["nettokosten"] * (1 - rabatt_pct / 100.0)
    df["investkosten"] = df["nettokosten_rabattiert"]
    return df
