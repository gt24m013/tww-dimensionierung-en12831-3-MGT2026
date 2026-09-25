"""Investitionsoptimierung: kostenoptimale Kombination aus Wärmepumpe und Speicher.

Statt eines abstrakten Rasters werden die realen Katalogprodukte
durchprobiert: für jede Kombination aus WP-Modell
und Speicher-Modell wird per Norm-Simulation geprüft, ob die
Sicherheitsbedingung nach 6.4.3.3 (SOC_min >= Q_sto,min) erfüllt ist. Unter
den zulässigen Kombinationen wird nach Investkosten sortiert.

Platzbedarf/Abmessungen sind (Stand jetzt) bewusst keine Nebenbedingung,
sondern nur zur Information im Ergebnis enthalten.

Der Bereitschaftsverlust q_sb,sto wird je Kombination aus dem produktspezifischen
Warmhalteverlust des jeweiligen Speichermodells übernommen (core/katalog.py,
Gl. 7), statt wie zuvor für alle Speichergrößen denselben global eingegebenen
Wert anzunehmen.
"""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from core.modell import Eingabedaten
from core.versorgung import (
    berechne_versorgungskennlinie, erholungsanalyse, tagesauswertung,
)
from core.katalog import normalisiere_material as _normalisiert


@dataclass
class Laufergebnis:
    """Kennzahlen einer Kombination unter EINEM Zapfprofil (Tag oder Woche).

    Die drei Teilbedingungen bleiben einzeln erhalten, damit im Ergebnis
    ablesbar ist, woran eine Kombination scheitert: am Norm-Kriterium, an der
    zulässigen Laufzeit (Sperrzeiten) oder an der Erholung des Speichers.
    """

    tage: int
    soc_min_kwh: float
    q_sto_min_kwh: float
    zyklen: int
    laufzeit_min: int              # Gesamtlaufzeit über den ganzen Zeitraum
    laufzeit_max_tag_min: int      # längste Laufzeit innerhalb eines einzelnen Tages
    ladezustand_ende_kwh: float
    erholung_max_abstand_min: int  # größter Abstand zwischen zwei Vollladungen
    erfuellt_norm: bool            # SOC_min >= Q_sto,min (6.4.3.3)
    erfuellt_laufzeit: bool        # längste Tageslaufzeit <= Grenze
    erfuellt_erholung: bool        # Speicher kommt mind. 1x je Tag wieder auf Vollladung
    zulaessig: bool                # alle geprüften Teilbedingungen erfüllt


def bewerte_lauf(
    daten: Eingabedaten,
    zapfprofil_l_min: np.ndarray,
    *,
    max_laufzeit_h: float = 24.0,
    erholung_pruefen: bool = False,
) -> Laufergebnis:
    """Rechnet ein Zapfprofil durch und bewertet es gegen alle Bedingungen.

    Norm-Kriterium (SOC_min >= Q_sto,min, 6.4.3.3) gilt immer. Die Laufzeit wird
    je KALENDERTAG geprüft, nicht über die Summe des Zeitraums - Sperrzeiten
    begrenzen die Laufzeit pro Tag. Die Erholungsbedingung ist nur über einen
    mehrtägigen Zeitraum aussagekräftig (über einen einzelnen Tag kann der
    Abstand zwischen zwei Vollladungen 24 h gar nicht überschreiten) und wird
    deshalb nur auf Anforderung in die Zulässigkeit einbezogen.
    """
    ergebnis = berechne_versorgungskennlinie(daten, zapfprofil_l_min)
    tage = tagesauswertung(zapfprofil_l_min, ergebnis)
    erholung = erholungsanalyse(ergebnis)

    soc_min = float(ergebnis.ladezustand.min())
    laufzeit_max_tag = max((t.laufzeit_min for t in tage), default=0)

    erfuellt_norm = soc_min >= ergebnis.q_sto_min
    erfuellt_laufzeit = laufzeit_max_tag <= max_laufzeit_h * 60
    erfuellt_erholung = erholung.ist_erholt

    return Laufergebnis(
        tage=len(tage),
        soc_min_kwh=soc_min,
        q_sto_min_kwh=ergebnis.q_sto_min,
        zyklen=len(ergebnis.zyklen),
        laufzeit_min=sum(z.dauer_min for z in ergebnis.zyklen),
        laufzeit_max_tag_min=laufzeit_max_tag,
        ladezustand_ende_kwh=float(ergebnis.ladezustand_ende),
        erholung_max_abstand_min=erholung.max_abstand_min,
        erfuellt_norm=erfuellt_norm,
        erfuellt_laufzeit=erfuellt_laufzeit,
        erfuellt_erholung=erfuellt_erholung,
        zulaessig=erfuellt_norm and erfuellt_laufzeit and (erfuellt_erholung or not erholung_pruefen),
    )


@dataclass
class Kombination:
    wp_hersteller: str
    wp_produkt: str
    wp_leistung_kw: float
    wp_kosten: float
    wp_platzbedarf_m3: float
    speicher_hersteller: str
    speicher_produkt: str
    speicher_volumen_l: float
    speicher_material: str
    speicher_kosten: float
    gesamtkosten: float
    zulaessig: bool
    soc_min_kwh: float
    q_sto_min_kwh: float
    zyklen: int
    laufzeit_min: int
    # Detailergebnisse je Zapfprofil; `woche` bleibt None, wenn keine
    # Bemessungswoche mitgegeben wurde (Modus D, und Modus F ohne Wochendatei).
    tag: Laufergebnis | None = None
    woche: Laufergebnis | None = None

    @property
    def gegen_woche_geprueft(self) -> bool:
        return self.woche is not None

    def scheitert_an(self) -> list[str]:
        """Klartext, woran die Kombination scheitert - leer, wenn zulässig."""
        gruende = []
        for lauf, bezeichnung in ((self.tag, "Bemessungstag"), (self.woche, "Bemessungswoche")):
            if lauf is None:
                continue
            if not lauf.erfuellt_norm:
                gruende.append(f"{bezeichnung}: SOC_min < Q_sto,min")
            if not lauf.erfuellt_laufzeit:
                gruende.append(f"{bezeichnung}: Laufzeit {lauf.laufzeit_max_tag_min / 60:.1f} h/d über Grenze")
            if bezeichnung == "Bemessungswoche" and not lauf.erfuellt_erholung:
                gruende.append(
                    f"{bezeichnung}: keine Vollladung über {lauf.erholung_max_abstand_min / 60:.1f} h"
                )
        return gruende


def optimiere(
    daten_basis: Eingabedaten,
    zapfprofil_l_min: np.ndarray,
    wp_katalog: pd.DataFrame,
    speicher_katalog: pd.DataFrame,
    material: str | None = None,
    *,
    zapfprofil_woche: np.ndarray | None = None,
    max_laufzeit_h: float = 24.0,
) -> list[Kombination]:
    """Prüft alle Kombinationen aus WP- und Speicher-Katalog gegen die Norm.

    `material`: falls gesetzt, wird der Speicher-Katalog vorher auf dieses
    Material gefiltert (z. B. "Edelstahl"); None = alle Materialien.

    `zapfprofil_woche`: optionale Bemessungswoche. Ist sie gesetzt, muss jede
    Kombination in BEIDEN Profilen bestehen - im Bemessungstag (Spitzendeckung)
    und in der Bemessungswoche (Dauerbetrieb inkl. Erholung des Speichers).
    `max_laufzeit_h` begrenzt die Erzeugerlaufzeit je Kalendertag (Sperrzeiten).

    Die zurückgegebenen Kennzahlen auf oberster Ebene (`soc_min_kwh`, `zyklen`,
    `laufzeit_min`) beziehen sich weiterhin auf den Bemessungstag; die
    vollständigen Kennzahlen beider Läufe stehen in `tag` und `woche`.
    """
    speicher_df = speicher_katalog
    if material:
        speicher_df = speicher_df[_normalisiert(speicher_df["material"]) == _normalisiert(material)]
        if speicher_df.empty:
            raise ValueError(f"Keine Speichermodelle mit Material '{material}' im Katalog gefunden.")

    ergebnisse: list[Kombination] = []
    for _, wp in wp_katalog.iterrows():
        for _, sp in speicher_df.iterrows():
            daten = replace(
                daten_basis, phi_n=float(wp["leistung_kw"]), v_sto=float(sp["volumen_l"]),
                q_sb_sto=float(sp["q_sb_sto"]),
            )
            tag = bewerte_lauf(daten, zapfprofil_l_min, max_laufzeit_h=max_laufzeit_h)
            woche = None
            if zapfprofil_woche is not None:
                woche = bewerte_lauf(
                    daten, zapfprofil_woche,
                    max_laufzeit_h=max_laufzeit_h, erholung_pruefen=True,
                )

            ergebnisse.append(Kombination(
                wp_hersteller=wp["hersteller"], wp_produkt=wp["produkt"],
                wp_leistung_kw=float(wp["leistung_kw"]), wp_kosten=float(wp["investkosten"]),
                wp_platzbedarf_m3=float(wp["platzbedarf_m3"]),
                speicher_hersteller=sp["hersteller"], speicher_produkt=sp["produkt"],
                speicher_volumen_l=float(sp["volumen_l"]), speicher_material=sp["material"],
                speicher_kosten=float(sp["investkosten"]),
                gesamtkosten=float(wp["investkosten"] + sp["investkosten"]),
                zulaessig=tag.zulaessig and (woche is None or woche.zulaessig),
                soc_min_kwh=tag.soc_min_kwh, q_sto_min_kwh=tag.q_sto_min_kwh,
                zyklen=tag.zyklen, laufzeit_min=tag.laufzeit_min,
                tag=tag, woche=woche,
            ))

    ergebnisse.sort(key=lambda k: (not k.zulaessig, k.gesamtkosten))
    return ergebnisse


def guenstigste_zulaessige(kombinationen: list[Kombination]) -> Kombination | None:
    for k in kombinationen:
        if k.zulaessig:
            return k
    return None


def materialschonendste_zulaessige(kombinationen: list[Kombination]) -> Kombination | None:
    """Unter den zulässigen Kombinationen jene mit der geringsten
    Schalthäufigkeit (Zyklen) - technische Optimierung (Modus F, Variante 1):
    möglichst materialschonender Betrieb bei weiterhin normkonformer
    Auslegung. Bei gleicher Zyklenzahl entscheidet die Investitionssumme."""
    zulaessige = [k for k in kombinationen if k.zulaessig]
    if not zulaessige:
        return None
    return min(zulaessige, key=lambda k: (k.zyklen, k.gesamtkosten))


def pareto_front(kombinationen: list[Kombination]) -> list[Kombination]:
    """Nicht-dominierte zulässige Kombinationen bezüglich der beiden
    Zielgrößen Gesamtkosten und Schalthäufigkeit (Zyklen), beide zu
    minimieren - Grundlage der techno-ökonomischen Optimierung (Modus F,
    Variante 3). Eine Kombination ist nicht dominiert, wenn keine andere
    zulässige Kombination in beiden Zielgrößen mindestens gleich gut und in
    mindestens einer davon strikt besser ist. Nach Gesamtkosten sortiert
    zurückgegeben (damit sie als zusammenhängende Front gezeichnet werden
    kann)."""
    zulaessige = [k for k in kombinationen if k.zulaessig]
    front = [
        k for k in zulaessige
        if not any(
            a is not k and a.gesamtkosten <= k.gesamtkosten and a.zyklen <= k.zyklen
            and (a.gesamtkosten < k.gesamtkosten or a.zyklen < k.zyklen)
            for a in zulaessige
        )
    ]
    return sorted(front, key=lambda k: k.gesamtkosten)


def kompromiss_zulaessige(kombinationen: list[Kombination], gewicht_kosten: float = 0.5) -> Kombination | None:
    """Techno-ökonomischer Kompromiss (Modus F, Variante 3): unter den
    zulässigen Kombinationen jene mit dem kleinsten gewichteten Score aus
    normierten Gesamtkosten und normierter Schalthäufigkeit (gewichtete
    Summe - Standardverfahren der Mehrzieloptimierung zur Skalarisierung
    einer Pareto-Front bei fest vorgegebener Gewichtung). Beide Zielgrößen
    werden vorher auf [0, 1] normiert (min-max über die zulässigen
    Kombinationen), damit die unterschiedlichen Größenordnungen (€ vs.
    Anzahl Zyklen) die Gewichtung nicht verzerren.

    `gewicht_kosten` in [0, 1]: 1.0 entspricht der rein ökonomischen,
    0.0 der rein technischen Optimierung.
    """
    zulaessige = [k for k in kombinationen if k.zulaessig]
    if not zulaessige:
        return None
    kosten = [k.gesamtkosten for k in zulaessige]
    zyklen = [k.zyklen for k in zulaessige]
    k_min, k_max = min(kosten), max(kosten)
    z_min, z_max = min(zyklen), max(zyklen)

    def _score(k: Kombination) -> float:
        kn = (k.gesamtkosten - k_min) / (k_max - k_min) if k_max > k_min else 0.0
        zn = (k.zyklen - z_min) / (z_max - z_min) if z_max > z_min else 0.0
        return gewicht_kosten * kn + (1 - gewicht_kosten) * zn

    return min(zulaessige, key=_score)
