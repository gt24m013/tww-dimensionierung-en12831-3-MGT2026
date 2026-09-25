"""Energiebedarf für erwärmtes Trinkwasser, Abschnitt 6.5.2 der ÖNORM EN 12831-3."""

from dataclasses import dataclass

import numpy as np

from core.modell import Eingabedaten
from core.norm_daten import (
    GEBAEUDETYP_KOEFFIZIENTEN,
    GEBAEUDETYP_WOHNUNG,
    LASTPROFILE_STUNDENANTEILE,
    N_P_EQ_BEZUGSWERT,
    N_P_EQ_DAEMPFUNG,
    N_P_EQ_STEIGUNG,
)

MINUTEN_PRO_TAG = 1440


@dataclass(frozen=True)
class AequivalentePersonen:
    """Zwischenergebnisse des Verfahrens C (Anhang B.2.2, Gl. B.1 bis B.5)."""

    n_p_eq_max: float      # n_P,eq,max je Wohneinheit [-]   (Gl. B.1 / B.3)
    n_p_eq: float          # n_P,eq je Wohneinheit [-]       (Gl. B.2 / B.4)
    n_p_eq_gesamt: float   # n_P,eq aller Wohneinheiten [-]
    v_w_p_day: float       # V_W,P,day [l/(Person*d)]        (Gl. B.5)
    v_w_day: float         # V_W,day über alle Einheiten [l/d] (Gl. 20)
    x_greift: bool         # True, wenn in Gl. B.5 die Obergrenze x maßgebend ist


def n_p_eq_max(wohnflaeche: float, gebaeudetyp: str = GEBAEUDETYP_WOHNUNG) -> float:
    """Maximale äquivalente Personenanzahl n_P,eq,max je Wohneinheit [-].

    Abschnittsweise Funktion über der bewohnbaren Fläche A_h, Gl. (B.3) für
    Wohnungen bzw. Gl. (B.1) für Einfamilien-/Reihenhäuser:

        A_h <  flaeche_min    ->  1
        A_h <  flaeche_bezug  ->  bezugswert - steigung * (flaeche_bezug - A_h)
        A_h >= flaeche_bezug  ->  flaechenfaktor * A_h

    Die Koeffizienten stammen aus core/norm_daten.py und sind vom Anwender aus
    seinem Normexemplar einzutragen (siehe core/norm_werte_vorlage.py).

    Sind die Koeffizienten stetig gewählt - liefern also beide angrenzenden
    Zweige an den Stützstellen denselben Wert, wie es bei den Normwerten der
    Fall ist -, sind die in der Norm offen gelassenen Intervallgrenzen ohne
    Einfluss auf das Ergebnis.
    """
    if wohnflaeche <= 0:
        raise ValueError("Die bewohnbare Fläche A_h muss größer als 0 m² sein.")

    try:
        flaeche_min, flaeche_bezug, flaechenfaktor = GEBAEUDETYP_KOEFFIZIENTEN[gebaeudetyp]
    except KeyError:
        raise ValueError(f"Unbekannter Gebäudetyp für Verfahren C: '{gebaeudetyp}'.") from None

    if wohnflaeche < flaeche_min:
        return 1.0
    if wohnflaeche < flaeche_bezug:
        return N_P_EQ_BEZUGSWERT - N_P_EQ_STEIGUNG * (flaeche_bezug - wohnflaeche)
    return flaechenfaktor * wohnflaeche


def n_p_eq(wohnflaeche: float, gebaeudetyp: str = GEBAEUDETYP_WOHNUNG) -> float:
    """Äquivalente Personenanzahl n_P,eq je Wohneinheit [-], Gl. (B.4) bzw. (B.2).

    Oberhalb des Bezugswerts wird n_P,eq,max abgemindert:

        n_P,eq,max <  bezugswert  ->  n_P,eq,max
        n_P,eq,max >= bezugswert  ->  bezugswert + daempfung * (n_P,eq,max - bezugswert)

    Bezugswert und Dämpfung stammen aus core/norm_daten.py.
    """
    maximum = n_p_eq_max(wohnflaeche, gebaeudetyp)
    if maximum < N_P_EQ_BEZUGSWERT:
        return maximum
    return N_P_EQ_BEZUGSWERT + N_P_EQ_DAEMPFUNG * (maximum - N_P_EQ_BEZUGSWERT)


def aequivalente_personen(daten: Eingabedaten) -> AequivalentePersonen:
    """Verfahren C: Tagesbedarf über die äquivalente Personenanzahl (Anhang B.2.2).

    Gl. (B.5): V_W,P,day = min( x ; y * A_h / n_P,eq )
    Gl. (20):  V_W,day   = V_W,P,day * n_P    mit n_P = n_P,eq aller Wohneinheiten

    Bezugsgröße von n_P,eq,max ist nach B.2.2 die Personengruppe an einer
    gemeinsamen Leitung für erwärmtes Trinkwasser, also eine Wohneinheit. Für
    ein Gebäude mit mehreren gleichartigen Einheiten wird n_P,eq je Einheit
    bestimmt und mit deren Anzahl multipliziert.
    """
    einheiten = daten.anzahl_wohneinheiten
    je_einheit = n_p_eq(daten.wohnflaeche, daten.wohnungstyp)
    gesamt = je_einheit * einheiten

    flaechenbezogen = daten.y_spez_volumen * daten.wohnflaeche / je_einheit
    v_w_p_day = min(daten.x_max_spez_volumen, flaechenbezogen)

    return AequivalentePersonen(
        n_p_eq_max=n_p_eq_max(daten.wohnflaeche, daten.wohnungstyp),
        n_p_eq=je_einheit,
        n_p_eq_gesamt=gesamt,
        v_w_p_day=v_w_p_day,
        v_w_day=v_w_p_day * gesamt,
        x_greift=daten.x_max_spez_volumen <= flaechenbezogen,
    )


def tagesvolumen_liter(daten: Eingabedaten) -> float:
    """Tägliches Trinkwarmwasser-Volumen V_W,day [l/d].

    Gl. 20 (Verfahren A, nach Personenzahl): V_W,day = V_W,P,day * n_P
    Gl. 21 (Verfahren B, nach Einheiten):     V_W,day = V_W,f,day * f
    Verfahren C (Anhang B.2.2, Gl. B.1-B.5):  V_W,day über n_P,eq, siehe
    aequivalente_personen(); mündet ebenfalls in Gl. 20.
    """
    if daten.tagesbedarf_methode == "A":
        return daten.n_personen * daten.v_pro_person
    if daten.tagesbedarf_methode == "C":
        return aequivalente_personen(daten).v_w_day
    return daten.n_einheiten * daten.v_pro_einheit


def zapfprofil_minutenwerte(daten: Eingabedaten) -> np.ndarray:
    """Verteilt das Tagesvolumen auf 1440 Minutenwerte [l/min].

    Die 24 Stundenanteile des gewählten Lastprofils werden gleichmäßig auf die
    60 Minuten der jeweiligen Stunde verteilt. Abschnitt 6.4.3.2 verlangt die
    Umrechnung auf einen Minuten-Zeitschritt, wenn das Bedarfsprofil auf einem
    anderen Zeitschritt beruht; die Profile nach Anhang B.1 sind stündlich
    angegeben.
    """
    stundenanteile = np.array(LASTPROFILE_STUNDENANTEILE[daten.gewaehltes_profil])
    anteil_je_minute = np.repeat(stundenanteile / stundenanteile.sum() / 60.0, 60)
    v_day = tagesvolumen_liter(daten)
    return anteil_je_minute * v_day
