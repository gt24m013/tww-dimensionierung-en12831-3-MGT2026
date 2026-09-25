"""Kostenregressionen je Hersteller (und bei Speichern zusätzlich je Material)
zur visuellen Prüfung, wie gut sich die in core/kostenfunktion.py für Modus E
gebildeten degressiven Kostenfunktionen (Potenzansatz K(x) = a * x^b)
tatsächlich an die Katalogdaten anpassen - sowohl für die absoluten
Investkosten als auch für die spezifischen Kosten (€/kW bzw. €/l), die
stärker für den Herstellervergleich geeignet sind (der Skaleneffekt selbst
ist an der Steigung der spezifischen Kosten unmittelbar ablesbar).

Speicher werden IMMER je (Hersteller, Material)-Kombination als eigene
Gruppe geführt (nie über Materialgrenzen hinweg zusammengefasst) - auch die
"Gesamtübersicht je Material" bildet nur eine gepoolte Regressionsfunktion
über alle Hersteller EINES Materials, die einzelnen Hersteller bleiben als
separat eingefärbte Punktwolken erkennbar.

Jede Gruppe liefert ihre eigene Kostenfunktion (core.kostenfunktion.
passe_potenzfunktion_an) - unabhängig von der einen gepoolten bzw.
materialgefilterten Kostenfunktion, die tatsächlich in Modus D/E für die
Optimierung verwendet wird (core/kostenfunktion.py). Gruppen mit weniger als
zwei Katalogeinträgen liefern keine Regression (funktion=None), bleiben aber
als Punktwolke in den Plots sichtbar.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.kostenfunktion import Kostenfunktion, passe_potenzfunktion_an


@dataclass
class Regressionsgruppe:
    bezeichnung: str           # Hersteller (bzw. "Alle Hersteller" / Materialname für gepoolte Gruppen)
    x: np.ndarray
    y: np.ndarray
    funktion: Kostenfunktion | None
    anzahl: int
    material: str | None = None  # nur bei Speichern gesetzt


def _y_werte(investkosten: np.ndarray, groesse: np.ndarray, spezifisch: bool) -> np.ndarray:
    return investkosten / groesse if spezifisch else investkosten


def _regressionsgruppe(bezeichnung: str, x: np.ndarray, y: np.ndarray, material: str | None = None) -> Regressionsgruppe:
    funktion = passe_potenzfunktion_an(x, y) if len(x) >= 2 else None
    return Regressionsgruppe(bezeichnung=bezeichnung, x=x, y=y, funktion=funktion, anzahl=len(x), material=material)


def _wp_y_summe(df: pd.DataFrame, spalten: tuple[str, ...], x: np.ndarray, spezifisch: bool) -> np.ndarray:
    y_summe = sum(df[spalte].to_numpy(dtype=float) for spalte in spalten)
    return _y_werte(y_summe, x, spezifisch)


def wp_regression_je_hersteller(
    wp_katalog: pd.DataFrame, spezifisch: bool, spalten: tuple[str, ...] = ("investkosten",),
) -> dict[str, Regressionsgruppe]:
    """Eine degressive Kostenfunktion (Summe der `spalten`, bzw. €/kW) vs.
    Leistung je Hersteller. `spalten` erlaubt es, statt der vollen
    Investkosten (Default) nur eine Teilsumme zu betrachten - z. B. nur den
    Listenpreis, oder Listenpreis+IBN ohne Montage (siehe
    core.kostenfunktion.wp_kostenfunktion_listenpreis/_inkl_ibn/wp_kostenfunktion
    für die einzelnen Fit-Stufen)."""
    ergebnis = {}
    for name, gruppe in wp_katalog.groupby("hersteller"):
        x = gruppe["leistung_kw"].to_numpy(dtype=float)
        y = _wp_y_summe(gruppe, spalten, x, spezifisch)
        ergebnis[str(name)] = _regressionsgruppe(str(name), x, y)
    return ergebnis


def wp_regression_gesamt(
    wp_katalog: pd.DataFrame, spezifisch: bool, spalten: tuple[str, ...] = ("investkosten",),
) -> Regressionsgruppe:
    """Eine gepoolte Kostenfunktion (Summe der `spalten`) über alle
    Hersteller - mit dem Default `spalten=("investkosten",)` identisch zu
    der, die core.kostenfunktion.wp_kostenfunktion() für Modus E liefert."""
    x = wp_katalog["leistung_kw"].to_numpy(dtype=float)
    y = _wp_y_summe(wp_katalog, spalten, x, spezifisch)
    return _regressionsgruppe("Alle Hersteller", x, y)


def speicher_regression_je_hersteller(speicher_katalog: pd.DataFrame, spezifisch: bool) -> dict[str, Regressionsgruppe]:
    """Eine Gruppe je (Hersteller, Material)-Kombination - flach, nicht nach
    Hersteller verschachtelt, da ein Hersteller mit mehreren Materialien in
    der Darstellung als mehrere eigenständige Diagramme auftreten soll."""
    ergebnis = {}
    for (hersteller, material), gruppe in speicher_katalog.groupby(["hersteller", "material"]):
        x = gruppe["volumen_l"].to_numpy(dtype=float)
        y = _y_werte(gruppe["investkosten"].to_numpy(dtype=float), x, spezifisch)
        schluessel = f"{hersteller}__{material}"
        ergebnis[schluessel] = _regressionsgruppe(str(hersteller), x, y, material=str(material))
    return ergebnis


def speicher_regression_je_material(speicher_katalog: pd.DataFrame, spezifisch: bool) -> dict[str, Regressionsgruppe]:
    """Eine gepoolte Kostenfunktion je Material, über alle Hersteller -
    identisch zu der, die core.kostenfunktion.speicher_kostenfunktion(
    ..., material=...) für Modus E liefert. Die Punktwolke dazu bleibt in
    der Darstellung nach Hersteller eingefärbt (siehe
    speicher_regression_je_hersteller), nur die Linie ist gepoolt."""
    ergebnis = {}
    for material, gruppe in speicher_katalog.groupby("material"):
        x = gruppe["volumen_l"].to_numpy(dtype=float)
        y = _y_werte(gruppe["investkosten"].to_numpy(dtype=float), x, spezifisch)
        ergebnis[str(material)] = _regressionsgruppe(str(material), x, y, material=str(material))
    return ergebnis


def speicher_verlust_je_hersteller(speicher_katalog: pd.DataFrame) -> dict[str, Regressionsgruppe]:
    """Bereitschaftsverlust q_sb,sto [kWh/24h] (aus dem katalogeigenen
    Warmhalteverlust je Modell, Gl. 7) vs. Speichervolumen - eine Gruppe je
    (Hersteller, Material)-Kombination, analog zu
    speicher_regression_je_hersteller(), aber mit dem Wärmeverlust statt der
    Investkosten als Zielgröße. Modelle ohne Warmhalteverlust (q_sb_sto =
    NaN, optionales Feld - siehe core.katalog.lade_speicher_katalog) fließen
    hier nicht ein, bleiben aber in den Investkosten-/Volumenplots enthalten."""
    ergebnis = {}
    df = speicher_katalog[speicher_katalog["q_sb_sto"].notna()]
    for (hersteller, material), gruppe in df.groupby(["hersteller", "material"]):
        x = gruppe["volumen_l"].to_numpy(dtype=float)
        y = gruppe["q_sb_sto"].to_numpy(dtype=float)
        schluessel = f"{hersteller}__{material}"
        ergebnis[schluessel] = _regressionsgruppe(str(hersteller), x, y, material=str(material))
    return ergebnis


def speicher_verlust_je_material(speicher_katalog: pd.DataFrame) -> dict[str, Regressionsgruppe]:
    """Eine gepoolte Verlustfunktion q_sb,sto(V) je Material, über alle
    Hersteller - zeigt, ob (und wie stark) der Bereitschaftsverlust
    materialabhängig degressiv mit der Speichergröße skaliert (vgl. Tabelle
    B.8 der Norm, die denselben Zusammenhang tabellarisch vorgibt). Modelle
    ohne Warmhalteverlust (siehe speicher_verlust_je_hersteller) fließen
    hier nicht ein."""
    ergebnis = {}
    df = speicher_katalog[speicher_katalog["q_sb_sto"].notna()]
    for material, gruppe in df.groupby("material"):
        x = gruppe["volumen_l"].to_numpy(dtype=float)
        y = gruppe["q_sb_sto"].to_numpy(dtype=float)
        ergebnis[str(material)] = _regressionsgruppe(str(material), x, y, material=str(material))
    return ergebnis
