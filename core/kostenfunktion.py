"""Leitet stetige, degressive Kostenfunktionen aus den Investitionskosten-
Katalogen ab.

Verwendet den in der Kostenschätzung für Anlagenkomponenten üblichen
Potenzansatz (Kostendegression, vgl. die "6/10-Regel"):

    K(x) = a * x^b

mit Baugröße x (Leistung [kW] bzw. Volumen [l]), Vorfaktor a und
Degressionsexponent b. Für b < 1 sinken die spezifischen Kosten K(x)/x mit
steigender Baugröße (Skaleneffekt) - anders als bei einem linearen
Fixkosten-Ansatz (K = a + b*x), der eine konstante Grenzkostenrate und einen
mit x/x_0 -> 0 gehenden Fixkostenanteil unterstellt. Der Potenzansatz bildet
den in den Katalogdaten durchgängig beobachteten Verlauf (siehe die
Kostenregressionen in Modus D/E) besser ab und kommt ohne separate
Fixkosten-Annahme aus.

Grundlage für Modus E (Optimierung über Kostenfunktionen) - im Unterschied
zu Modus D, der reale Katalogprodukte direkt durchprobiert.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.katalog import normalisiere_material as _normalisiert


class KostenfunktionFehler(Exception):
    pass


@dataclass
class Kostenfunktion:
    koeffizient_a: float    # Vorfaktor [€ je (kW bzw. l)^exponent_b]
    exponent_b: float       # Degressionsexponent [-]; < 1 => sinkende spezifische Kosten mit Baugröße
    r_quadrat: float         # Bestimmtheitsmaß auf Originalskala, zur Beurteilung der Anpassungsgüte
    stuetzstellen: int        # Anzahl Katalogeinträge, auf denen die Funktion beruht

    def __call__(self, x):
        return self.koeffizient_a * np.asarray(x, dtype=float) ** self.exponent_b


def bestimmtheitsmass(y_beobachtet: np.ndarray, y_vorhersage: np.ndarray) -> float:
    """Bestimmtheitsmaß R² zwischen beobachteten und vorhergesagten Werten,
    auf der Skala der übergebenen Werte (kein Log-Log-R²). Für eine
    Kostenfunktion, die auf absoluten Kosten gefittet wurde, liefert dieselbe
    Kurve je nach übergebener Skala (Gesamtkosten vs. spezifische Kosten) ein
    anderes R² - beide sind zulässig, solange y_beobachtet und y_vorhersage
    konsistent auf derselben Skala liegen (siehe core.kostenfunktion.
    speicher_kostenfunktion zur Äquivalenz der Kurve selbst über Skalen
    hinweg)."""
    y = np.asarray(y_beobachtet, dtype=float)
    y_pred = np.asarray(y_vorhersage, dtype=float)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0


def _potenzfit(x: np.ndarray, y: np.ndarray) -> Kostenfunktion:
    """Fit von K(x) = a * x^b über log-log-Linearisierung (ln K = ln a + b *
    ln x, per kleinste-Quadrate-Gerade). Das Bestimmtheitsmaß wird auf der
    Originalskala (nicht log-log) berechnet, damit R² unmittelbar die
    Anpassungsgüte an die tatsächlichen Kosten widerspiegelt."""
    if len(x) < 2:
        raise KostenfunktionFehler("Mindestens 2 Katalogeinträge nötig, um eine Kostenfunktion zu bilden.")
    if np.any(x <= 0) or np.any(y <= 0):
        raise KostenfunktionFehler(
            "Degressive Kostenfunktion (Potenzansatz) erfordert Baugröße > 0 und Kosten > 0 für alle Stützstellen."
        )
    b, ln_a = np.polyfit(np.log(x), np.log(y), 1)
    a = float(np.exp(ln_a))
    r2 = bestimmtheitsmass(y, a * x ** b)
    return Kostenfunktion(koeffizient_a=a, exponent_b=float(b), r_quadrat=r2, stuetzstellen=len(x))


def passe_potenzfunktion_an(x: np.ndarray, y: np.ndarray) -> Kostenfunktion:
    """Öffentlicher Zugang zum Potenzfit für andere Module (z. B.
    core/kostenregression.py), die Kostenfunktionen für beliebige Gruppen
    (Hersteller, Material) statt für den Gesamtkatalog bilden wollen."""
    return _potenzfit(x, y)


def _wp_listenpreis_spalte(wp_katalog: pd.DataFrame) -> str:
    return "listenpreis_rabattiert" if "listenpreis_rabattiert" in wp_katalog.columns else "listenpreis"


def wp_kostenfunktion_listenpreis(wp_katalog: pd.DataFrame) -> Kostenfunktion:
    """Fit 1: Investkosten(Φ_N) [€] = Potenzfit auf den reinen Netto-Listenpreis
    (ohne IBN, ohne Montage) - rein diagnostisch für die Gesamtübersicht."""
    x = wp_katalog["leistung_kw"].to_numpy(dtype=float)
    y = wp_katalog[_wp_listenpreis_spalte(wp_katalog)].to_numpy(dtype=float)
    return _potenzfit(x, y)


def wp_kostenfunktion_inkl_ibn(wp_katalog: pd.DataFrame) -> Kostenfunktion:
    """Fit 2: Investkosten(Φ_N) [€] = EIN gemeinsamer Potenzfit auf Listenpreis+IBN
    zusammen (ohne Montage) - rein diagnostisch für die Gesamtübersicht.

    Ein gemeinsamer Fit statt getrennter Potenzfits für Listenpreis und
    Inbetriebnahme: Listenpreis und IBN skalieren zwar unterschiedlich stark
    mit der Leistung (unterschiedlicher Degressionsexponent bei getrennter
    Betrachtung), an einem realen Katalog (n=64) zeigt sich aber, dass ein
    einzelner Potenzfit auf der Summe die tatsächlichen Gesamtkosten
    mindestens ebenso gut trifft wie die Summe zweier getrennter Fits
    (R²=0,7952 vs. 0,7947, RMSE-Unterschied < 0,2 %) - der gemeinsame Fit
    ist damit die einfachere Näherung ohne nennenswerten Genauigkeitsverlust."""
    x = wp_katalog["leistung_kw"].to_numpy(dtype=float)
    summe = (
        wp_katalog[_wp_listenpreis_spalte(wp_katalog)].to_numpy(dtype=float)
        + wp_katalog["ibn_kosten"].to_numpy(dtype=float)
    )
    return _potenzfit(x, summe)


def wp_kostenfunktion(wp_katalog: pd.DataFrame, montagekosten: float = 0.0) -> Kostenfunktion:
    """Fit 3: Investkosten(Φ_N) [€] = EIN gemeinsamer Potenzfit auf Listenpreis+IBN
    +Montage zusammen - das ist die für Modus E/F tatsächlich verwendete
    Kostenfunktion.

    Die Montagepauschale (über alle Leistungsbereiche konstant, siehe
    core/montage.py) geht hier VOR dem Fit mit in die Summe ein, statt erst
    danach als Konstante addiert zu werden: Da jede WP dieselbe Pauschale
    erhält, verschiebt das nur die absolute Kostenkurve, ändert aber nicht
    die relative Kostendifferenz zwischen den WP-Leistungsstufen und damit
    nicht das Optimierungsergebnis (welche Kombination am günstigsten ist) -
    ein gemeinsamer Fit über alle drei Bestandteile ist dadurch die
    einfachere Rechnung ohne Einfluss auf die Optimierung."""
    x = wp_katalog["leistung_kw"].to_numpy(dtype=float)
    summe = (
        wp_katalog[_wp_listenpreis_spalte(wp_katalog)].to_numpy(dtype=float)
        + wp_katalog["ibn_kosten"].to_numpy(dtype=float)
        + float(montagekosten)
    )
    return _potenzfit(x, summe)


def speicher_kostenfunktion(speicher_katalog: pd.DataFrame, material: str | None = None) -> Kostenfunktion:
    """Investkosten(V_sto) [€] = EIN Potenzfit auf die Investkosten (bereits
    inkl. Rabatt, core.rabatt.wende_speicher_rabatt_an, und ggf. Montage-
    Prozentsatz, core.montage.wende_speicher_montage_an).

    Anders als bei der WP (additive Montagepauschale, siehe
    wp_kostenfunktion) ist die Speicher-Montage ein reiner Prozentsatz auf
    die bereits rabattierten Investkosten, geht also rein multiplikativ ein:
    ein gemeinsamer Potenzfit auf den Investkosten inkl. Montage liefert
    daher exakt denselben Exponenten und einen um den Faktor (1 +
    Montage-%/100) skalierten Vorfaktor wie ein Fit ohne Montage - eine
    getrennte Montage-Kostenfunktion (wie bei der additiven WP-Pauschale)
    ist hier nicht nötig."""
    df = speicher_katalog
    if material:
        df = df[_normalisiert(df["material"]) == _normalisiert(material)]
        if df.empty:
            raise KostenfunktionFehler(f"Keine Speichermodelle mit Material '{material}' im Katalog gefunden.")
    return _potenzfit(df["volumen_l"].to_numpy(dtype=float), df["investkosten"].to_numpy(dtype=float))
