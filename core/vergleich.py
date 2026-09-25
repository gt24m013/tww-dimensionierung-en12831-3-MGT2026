"""Vergleich Norm-Auslegung (Soll) vs. reales Monitoring (Ist) für dieselbe Anlage."""

from dataclasses import dataclass, field

import numpy as np

from core.modell import Eingabedaten
from core.versorgung import (
    MINUTEN_PRO_TAG,
    Versorgungsergebnis,
    verlust_gesamt_je_minute,
    verlust_speicher_je_minute,
    verlust_verteilung_je_minute,
)


@dataclass
class Verlustbilanz:
    """Wärmeverluste eines Falls, so wie sie minutenweise in die Simulation eingehen.

    Der Norm-Fall schätzt sie nach Gl. 6 (Speicher) und Gl. 9 (Verteilung), der
    Monitoring-Fall setzt stattdessen einen gemessenen Summenwert ein. Bei diesem
    Messwert-Override ist die Aufteilung auf Speicher und Verteilung nicht bekannt -
    die beiden Einzelposten bleiben dann None.
    """

    ist_messwert: bool
    je_minute: float                    # q_V,ges [kWh/min], genau der Wert aus der Simulation
    gesamt_kwh_tag: float               # q_V,ges * 1440 [kWh/d]
    gesamt_kwh_zeitraum: float          # q_V,ges * Anzahl simulierter Minuten [kWh]
    minuten: int
    speicher_kwh_tag: float | None = None      # Gl. 6, nur bei Norm-Schätzung
    verteilung_kwh_tag: float | None = None    # Gl. 9, nur bei Norm-Schätzung

    @property
    def ansatz(self) -> str:
        return "Messwert (ersetzt Gl. 6/9)" if self.ist_messwert else "Norm-Schätzung (Gl. 6/9)"


def verlustbilanz(daten: Eingabedaten, minuten: int) -> Verlustbilanz:
    """Verlustbilanz eines Falls über `minuten` simulierte Minuten."""
    je_minute = verlust_gesamt_je_minute(daten)
    ist_messwert = daten.verlust_gesamt_je_minute is not None
    return Verlustbilanz(
        ist_messwert=ist_messwert,
        je_minute=je_minute,
        gesamt_kwh_tag=je_minute * MINUTEN_PRO_TAG,
        gesamt_kwh_zeitraum=je_minute * minuten,
        minuten=minuten,
        speicher_kwh_tag=None if ist_messwert else verlust_speicher_je_minute(daten) * MINUTEN_PRO_TAG,
        verteilung_kwh_tag=None if ist_messwert else verlust_verteilung_je_minute(daten) * MINUTEN_PRO_TAG,
    )


@dataclass
class VergleichsErgebnis:
    vol_soll: float
    vol_ist: float
    diff_vol_pct: float
    energie_soll: float
    energie_ist: float
    diff_energie_pct: float
    laufzeit_soll_min: int
    laufzeit_ist_min: int
    zyklen_soll: int
    zyklen_ist: int
    soc_min_soll: float
    soc_min_ist: float
    q_sto_min: float
    warnungen: list[str] = field(default_factory=list)
    # Verlustgegenüberstellung; None, solange die Parametersätze nicht mitgegeben werden
    verlust_soll: Verlustbilanz | None = None
    verlust_ist: Verlustbilanz | None = None
    diff_verlust_pct: float | None = None


def vergleiche(
    zapf_soll: np.ndarray, erg_soll: Versorgungsergebnis,
    zapf_ist: np.ndarray, erg_ist: Versorgungsergebnis,
    daten_soll: Eingabedaten | None = None, daten_ist: Eingabedaten | None = None,
) -> VergleichsErgebnis:
    """Kennzahlen beider Fälle nebeneinander.

    `daten_soll`/`daten_ist` sind die Parametersätze, mit denen die beiden Fälle
    tatsächlich gerechnet wurden. Werden sie mitgegeben, kommt die
    Verlustgegenüberstellung dazu - sonst bleiben die Verlustfelder None.
    """
    vol_soll, vol_ist = float(zapf_soll.sum()), float(zapf_ist.sum())
    diff_vol = ((vol_ist - vol_soll) / vol_soll * 100) if vol_soll > 0 else 0.0

    e_soll, e_ist = erg_soll.bedarfskennlinie[-1], erg_ist.bedarfskennlinie[-1]
    diff_e = ((e_ist - e_soll) / e_soll * 100) if e_soll > 0 else 0.0

    laufzeit_soll = sum(z.dauer_min for z in erg_soll.zyklen)
    laufzeit_ist = sum(z.dauer_min for z in erg_ist.zyklen)

    soc_min_soll, soc_min_ist = erg_soll.ladezustand.min(), erg_ist.ladezustand.min()
    q_sto_min = erg_soll.q_sto_min

    warnungen = []
    if soc_min_ist < q_sto_min:
        warnungen.append(
            f"KRITISCHE UNTERDIMENSIONIERUNG: Realer Ladezustand fällt auf {soc_min_ist:.2f} kWh "
            f"(Reserve Q_sto,min = {q_sto_min:.2f} kWh)."
        )
    if soc_min_soll >= q_sto_min and soc_min_ist < q_sto_min:
        warnungen.append(
            "PERFORMANCE GAP: Die normative Auslegung ist sicher, aber das reale Zapfverhalten "
            "führt zur Unterversorgung."
        )
    elif soc_min_soll < q_sto_min and soc_min_ist >= q_sto_min:
        warnungen.append(
            "ÜBERDIMENSIONIERUNG: Anlage scheitert bei der Normauslegung, reale Daten zeigen "
            "jedoch einen unkritischen Betrieb."
        )

    v_soll = verlustbilanz(daten_soll, len(zapf_soll)) if daten_soll is not None else None
    v_ist = verlustbilanz(daten_ist, len(zapf_ist)) if daten_ist is not None else None
    diff_verlust = None
    if v_soll is not None and v_ist is not None and v_soll.gesamt_kwh_tag > 0:
        diff_verlust = (
            (v_ist.gesamt_kwh_tag - v_soll.gesamt_kwh_tag) / v_soll.gesamt_kwh_tag * 100
        )

    return VergleichsErgebnis(
        vol_soll=vol_soll, vol_ist=vol_ist, diff_vol_pct=diff_vol,
        energie_soll=e_soll, energie_ist=e_ist, diff_energie_pct=diff_e,
        laufzeit_soll_min=laufzeit_soll, laufzeit_ist_min=laufzeit_ist,
        zyklen_soll=len(erg_soll.zyklen), zyklen_ist=len(erg_ist.zyklen),
        soc_min_soll=soc_min_soll, soc_min_ist=soc_min_ist, q_sto_min=q_sto_min,
        warnungen=warnungen,
        verlust_soll=v_soll, verlust_ist=v_ist, diff_verlust_pct=diff_verlust,
    )
