"""Kontinuierliche Systemoptimierung über abgeleitete Kostenfunktionen (Modus E).

Rastersuche im kontinuierlichen Auslegungsraum: V_sto und Φ_N werden je im
Bereich 30-200 % eines Referenzwerts gerastert, der Bereitschaftsverlust wird
mit der Speichergröße skaliert (~V^(2/3)), und zulässig ist eine Kombination,
wenn sie das Norm-Kriterium (SOC_min >= Q_sto,min) erfüllt, die maximale
WP-Laufzeit einhält und sich der Speicher über 24 h nicht entleert
(Endladezustand >= 95 % von Q_sto,max).

Die Rasterpunkte sind rechnerische Größen, keine Produkte. Minimiert wird die
tatsächliche Investitionssumme aus den degressiven Kostenfunktionen
(core/kostenfunktion.py), nicht ein abstrakter gewichteter Score aus
Leistung, Volumen und Taktzahl.
"""

from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from core.modell import Eingabedaten
from core.versorgung import berechne_versorgungskennlinie


@dataclass
class Rasterpunkt:
    v_sto: float
    phi_n: float
    kosten: float
    zulaessig: bool
    soc_min_kwh: float
    q_sto_min_kwh: float
    zyklen: int
    laufzeit_min: int
    ist_24h_ausgeglichen: bool


def optimiere_raster(
    daten_basis: Eingabedaten,
    zapfprofil_l_min: np.ndarray,
    wp_kosten: Callable[[float], float],
    speicher_kosten: Callable[[float], float],
    v_sto_referenz: float,
    phi_n_referenz: float,
    max_laufzeit_h: float = 24.0,
    raster_schritte: int = 25,
) -> list[Rasterpunkt]:
    v_min, v_max = max(100.0, v_sto_referenz * 0.3), v_sto_referenz * 2.0
    phi_min, phi_max = max(2.0, phi_n_referenz * 0.3), phi_n_referenz * 2.0

    v_sto_range = np.linspace(v_min, v_max, raster_schritte)
    phi_n_range = np.linspace(phi_min, phi_max, raster_schritte)
    q_sb_referenz = daten_basis.q_sb_sto

    punkte: list[Rasterpunkt] = []
    for v_test in v_sto_range:
        # Bereitschaftsverlust skaliert mit der Speicheroberfläche (~V^(2/3))
        q_sb_test = q_sb_referenz * ((v_test / v_sto_referenz) ** (2 / 3))
        for phi_test in phi_n_range:
            daten = replace(daten_basis, v_sto=float(v_test), phi_n=float(phi_test), q_sb_sto=float(q_sb_test))
            ergebnis = berechne_versorgungskennlinie(daten, zapfprofil_l_min)

            soc_min = float(ergebnis.ladezustand.min())
            laufzeit = sum(z.dauer_min for z in ergebnis.zyklen)
            ausgeglichen = ergebnis.ladezustand_ende >= ergebnis.q_sto_max * 0.95
            zulaessig = (
                soc_min >= ergebnis.q_sto_min
                and laufzeit <= max_laufzeit_h * 60
                and ausgeglichen
            )
            kosten = wp_kosten(phi_test) + speicher_kosten(v_test)

            punkte.append(Rasterpunkt(
                v_sto=float(v_test), phi_n=float(phi_test), kosten=float(kosten),
                zulaessig=zulaessig, soc_min_kwh=soc_min, q_sto_min_kwh=ergebnis.q_sto_min,
                zyklen=len(ergebnis.zyklen), laufzeit_min=laufzeit, ist_24h_ausgeglichen=ausgeglichen,
            ))
    return punkte


@dataclass
class Anlagenkosten:
    """Eine konkret dimensionierte Anlage (V_sto, Φ_N), bewertet mit den
    Kostenfunktionen aus Modus E, samt Abweichung zum Ausgangszustand."""

    bezeichnung: str
    v_sto: float
    phi_n: float
    wp_kosten: float
    speicher_kosten: float
    gesamtkosten: float
    diff_abs: float          # Mehr-/Minderkosten gegenüber dem Ausgangszustand [€]
    diff_pct: float          # dieselbe Differenz bezogen auf den Ausgangszustand [%]
    ist_ausgangszustand: bool


def bewerte_anlagen(
    eintraege: list[tuple[str, float, float]],
    wp_kosten: Callable[[float], float],
    speicher_kosten: Callable[[float], float],
) -> list[Anlagenkosten]:
    """Bewertet fertig dimensionierte Anlagen mit denselben Kostenfunktionen,
    die auch das Raster in Modus E minimiert.

    `eintraege` ist eine Liste aus (Bezeichnung, V_sto [l], Φ_N [kW]); der
    ERSTE Eintrag ist der Ausgangszustand, auf den sich die Mehr-/Minderkosten
    aller weiteren Einträge absolut und prozentual beziehen. Damit lässt sich
    die in Modus A normbasiert ausgelegte Anlage direkt gegen die aus dem
    realen Monitoring (Modus B) dimensionierte und gegen das Kostenoptimum des
    Rasters stellen - alle drei auf derselben Kostenbasis.
    """
    bewertet: list[Anlagenkosten] = []
    basis = None
    for bezeichnung, v_sto, phi_n in eintraege:
        wp = float(wp_kosten(phi_n))
        sp = float(speicher_kosten(v_sto))
        gesamt = wp + sp
        if basis is None:
            basis = gesamt
        diff = gesamt - basis
        bewertet.append(Anlagenkosten(
            bezeichnung=bezeichnung, v_sto=float(v_sto), phi_n=float(phi_n),
            wp_kosten=wp, speicher_kosten=sp, gesamtkosten=gesamt,
            diff_abs=diff, diff_pct=(diff / basis * 100.0) if basis > 0 else 0.0,
            ist_ausgangszustand=not bewertet,
        ))
    return bewertet


def guenstigster_punkt(punkte: list[Rasterpunkt]) -> Rasterpunkt | None:
    zulaessige = [p for p in punkte if p.zulaessig]
    return min(zulaessige, key=lambda p: p.kosten) if zulaessige else None


def kleinste_leistung(punkte: list[Rasterpunkt]) -> Rasterpunkt | None:
    zulaessige = [p for p in punkte if p.zulaessig]
    return min(zulaessige, key=lambda p: p.phi_n) if zulaessige else None


def kleinstes_volumen(punkte: list[Rasterpunkt]) -> Rasterpunkt | None:
    zulaessige = [p for p in punkte if p.zulaessig]
    return min(zulaessige, key=lambda p: p.v_sto) if zulaessige else None
