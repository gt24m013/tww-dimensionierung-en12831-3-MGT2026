"""Energieversorgungskennlinie nach ÖNORM EN 12831-3, Abschnitt 6.4.2 / 6.4.3.

Enthält die Speicher- und Verlustgrößen (Gl. 4-10) sowie den minutenweisen
Simulationsalgorithmus zur Bestimmung der Versorgungskennlinie (Bild 14,
6.4.3.3), inklusive der effektiven Nacherhitzungsleistung (Gl. 13/14).
"""

from dataclasses import dataclass, field

import numpy as np

from core.modell import Eingabedaten

MINUTEN_PRO_TAG = 1440


def dichte_wasser(theta: float) -> float:
    """Dichte des Wassers ρ_W [kg/l], Gl. B.1 (Anhang B.4.1)."""
    return (1000.0 - 0.005 * (theta - 4.0) ** 2) / 1000.0


def q_sto_max(daten: Eingabedaten) -> float:
    """Maximale Speicherkapazität Q_sto,max [kWh], Gl. 4."""
    rho_w = dichte_wasser(daten.theta_draw)
    return (
        daten.v_sto * rho_w * daten.cw
        * (daten.theta_sto_max - daten.theta_c) * daten.f_l
    ) / 3600.0


def q_sto_min(daten: Eingabedaten) -> float:
    """Minimale Speicherkapazität Q_sto,min [kWh], Gl. 5.

    Nur für gemischte Speichersysteme relevant; bei Speicherladesystemen ist
    Q_sto,min = 0 (6.4.2.4.2).
    """
    if not daten.ist_gemischtes_system():
        return 0.0
    rho_w = dichte_wasser(daten.theta_draw)
    return (
        daten.v_sto * rho_w * daten.cw
        * (1 - daten.h_sensor / (2 * daten.h_sto))
        * (daten.theta_draw - daten.theta_c) * daten.f_l
    ) / 3600.0


def q_sto_on(daten: Eingabedaten) -> float:
    """Einschaltpunkt Q_sto,ON [kWh], Gl. 10."""
    return q_sto_max(daten) * (1 - daten.h_sensor / daten.h_sto)


def verlust_speicher_je_minute(daten: Eingabedaten) -> float:
    """Speicher-Bereitschaftsverlust Q_W,sto,t je Minute [kWh/min], Gl. 6."""
    return (
        daten.q_sb_sto * (daten.theta_sto_max - daten.theta_a) / 45.0
    ) / MINUTEN_PRO_TAG


def verlust_verteilung_je_minute(daten: Eingabedaten) -> float:
    """Verteilungs-Wärmeverlust Q_W,dis,t je Minute [kWh/min], Gl. 9 (vereinfachtes Verfahren)."""
    return (daten.q_dis_spec * daten.l_dis) / 60000.0


def verlust_gesamt_je_minute(daten: Eingabedaten) -> float:
    """Summenverlust Speicher+Verteilung je Minute [kWh/min].

    Ist daten.verlust_gesamt_je_minute gesetzt (z. B. aus Monitoring-Messwerten
    bestimmt), wird dieser Messwert direkt verwendet und die Norm-Schätzung aus
    Gl. 6/9 entfällt; sonst Summe der beiden Norm-Terme wie bisher.
    """
    if daten.verlust_gesamt_je_minute is not None:
        return daten.verlust_gesamt_je_minute
    return verlust_speicher_je_minute(daten) + verlust_verteilung_je_minute(daten)


@dataclass
class Einschaltzyklus:
    start_min: int
    ende_min: int

    @property
    def dauer_min(self) -> int:
        return self.ende_min - self.start_min


@dataclass
class Versorgungsergebnis:
    bedarfskennlinie: np.ndarray       # kumulierter Energiebedarf [kWh], Länge = len(Zapfprofil)
    versorgungskennlinie: np.ndarray   # kumulierte Nacherhitzung netto [kWh], Länge = len(Zapfprofil) + 1
    ladezustand: np.ndarray            # Speicher-Ladezustand (SOC) je Minute [kWh], Länge = len(Zapfprofil)
    zyklen: list[Einschaltzyklus]
    q_sto_max: float
    q_sto_on: float
    q_sto_min: float
    ladezustand_ende: float


@dataclass
class Tagesauswertung:
    """Kennzahlen eines einzelnen Tages innerhalb eines mehrtägigen Laufs."""

    tag: int                  # 1-basierter Tag im Auslegungszeitraum
    zapfvolumen_l: float      # gezapftes Volumen dieses Tages [l]
    soc_min: float            # tiefster Ladezustand des Tages [kWh]
    soc_ende: float           # Ladezustand am Tagesende [kWh]
    zyklen: int               # in diesem Tag begonnene Einschaltzyklen
    laufzeit_min: int         # Erzeuger-Laufzeit innerhalb dieses Tages [min]


def tagesauswertung(
    zapfprofil_l_min: np.ndarray, ergebnis: "Versorgungsergebnis",
) -> list[Tagesauswertung]:
    """Zerlegt einen mehrtägigen Lauf in Tageskennzahlen.

    Nötig, um zu beurteilen, ob sich der Speicher über mehrere Tage einpendelt:
    Das Norm-Lastprofil endet um Mitternacht, die entnahmearme Zeit beginnt aber
    erst danach - ein am Ende des Auslegungstages nicht voll geladener Speicher
    muss deshalb nicht unterdimensioniert sein, sondern kann den Ladezustand über
    die Folgetage wieder aufholen.

    Ein über Mitternacht laufender Zyklus zählt beim Tag seines Beginns; seine
    Laufzeit wird dagegen minutengenau auf die betroffenen Tage aufgeteilt.
    """
    tage = max(1, len(zapfprofil_l_min) // MINUTEN_PRO_TAG)
    auswertungen = []
    for index in range(tage):
        beginn, ende = index * MINUTEN_PRO_TAG, (index + 1) * MINUTEN_PRO_TAG
        soc = ergebnis.ladezustand[beginn:ende]
        laufzeit = sum(
            max(0, min(z.ende_min, ende) - max(z.start_min, beginn)) for z in ergebnis.zyklen
        )
        auswertungen.append(Tagesauswertung(
            tag=index + 1,
            zapfvolumen_l=float(np.asarray(zapfprofil_l_min[beginn:ende]).sum()),
            soc_min=float(soc.min()),
            soc_ende=float(soc[-1]),
            zyklen=sum(1 for z in ergebnis.zyklen if beginn <= z.start_min < ende),
            laufzeit_min=int(laufzeit),
        ))
    return auswertungen


SCHWELLE_VOLLLADUNG = 0.95


@dataclass
class Erholung:
    """Erholt sich der Speicher regelmäßig wieder auf (annähernd) Vollladung?

    Maßgeblich ist nicht der Ladezustand zu einem festen Zeitpunkt (etwa um
    Mitternacht), sondern ob der Speicher in den entnahmearmen Stunden überhaupt
    wieder hochkommt, bevor die nächste größere Entnahme beginnt. Geprüft wird
    deshalb der größte zeitliche Abstand zwischen zwei Vollladungen: liegt er
    unter der Grenze (Vorgabe 24 h), kommt der Speicher mindestens einmal je Tag
    wieder auf Q_sto,max zurück - unabhängig davon, wann im Tagesverlauf das
    passiert. Ein Speicher, der durchgehend nachgeladen wird und den Sollwert nie
    erreicht, fällt dadurch auf.

    Dies ist eine Zusatzbedingung für die Optimierung, kein Norm-Kriterium: die
    Norm prüft in 6.4.3.3 ausschließlich SOC_min >= Q_sto,min.
    """

    schwelle_kwh: float           # ab hier gilt der Speicher als wieder voll
    max_abstand_min: int          # größter Abstand zwischen zwei Vollladungen [min]
    grenze_min: int               # zulässiger Höchstabstand [min]
    anzahl_vollladungen: int      # Anzahl getrennter Erholungsvorgänge
    ist_erholt: bool


def erholungsanalyse(
    ergebnis: "Versorgungsergebnis", *,
    schwelle: float = SCHWELLE_VOLLLADUNG,
    grenze_min: int = MINUTEN_PRO_TAG,
) -> Erholung:
    """Erholungsverhalten eines gerechneten Laufs (siehe `Erholung`)."""
    soc = np.asarray(ergebnis.ladezustand, dtype=float)
    schwelle_kwh = ergebnis.q_sto_max * schwelle
    voll = soc >= schwelle_kwh

    # Bezugspunkte: der Start (Q_sto(0) = Q_sto,max, per Definition voll), jede
    # Minute mit erreichter Vollladung und das Ende des Betrachtungszeitraums.
    # Der Abstand zwischen zwei Bezugspunkten ist die Zeit ohne Erholung.
    punkte = [0, *(int(t) + 1 for t in np.flatnonzero(voll)), len(soc)]
    max_abstand = int(max(np.diff(punkte))) if len(punkte) > 1 else len(soc)

    # Getrennte Erholungsvorgänge = Übergänge von "nicht voll" auf "voll"
    anzahl = int(np.count_nonzero(voll[1:] & ~voll[:-1])) + int(bool(voll[:1].any()))

    return Erholung(
        schwelle_kwh=float(schwelle_kwh),
        max_abstand_min=max_abstand,
        grenze_min=grenze_min,
        anzahl_vollladungen=anzahl,
        ist_erholt=max_abstand <= grenze_min,
    )


def berechne_versorgungskennlinie(
    daten: Eingabedaten, zapfprofil_l_min: np.ndarray
) -> Versorgungsergebnis:
    """Minutenweiser Algorithmus zur Bestimmung der Versorgungskennlinie (Bild 14, 6.4.3.3).

    Ablauf je Minute:
      1. Bedarf abziehen (Zapfung -> Gl. 1 sinngemäß, minutenweise)
      2. Speicher- und Verteilverluste abziehen (Gl. 6, Gl. 9)
      3. sinkt der Ladezustand auf Q_sto,ON, wird die Nacherhitzung ausgelöst;
         nach Ablauf der Zeitverzögerung t_lag,HG (Gl. 11/12) liefert der
         Erzeuger seine effektive Leistung Φeff (Gl. 13 bzw. 14), bis der
         Speicher wieder Q_sto,max erreicht.
    """
    rho_w = dichte_wasser(daten.theta_draw)
    delta_t = daten.theta_draw - daten.theta_c
    is_mixed = daten.ist_gemischtes_system()

    bedarf_je_minute = (zapfprofil_l_min * rho_w * daten.cw * delta_t) / 3600.0
    bedarfskennlinie = np.cumsum(bedarf_je_minute)

    q_max = q_sto_max(daten)
    q_on = q_sto_on(daten)
    q_min = q_sto_min(daten)
    q_verlust = verlust_gesamt_je_minute(daten)

    theta_ch_hg = daten.theta_ch_hg if daten.theta_ch_hg is not None else daten.theta_sto_max + 5.0

    q_aktuell = q_max
    versorgung_netto = [0.0]
    ladezustand = []
    zyklen: list[Einschaltzyklus] = []

    erzeuger_laeuft = False
    laufzeit_min = 0
    start_t = 0

    n = len(zapfprofil_l_min)
    for t in range(n):
        if not erzeuger_laeuft and q_aktuell <= q_on:
            erzeuger_laeuft = True
            laufzeit_min = 0
            start_t = t

        q_eff = 0.0
        if erzeuger_laeuft:
            laufzeit_min += 1
            if laufzeit_min > daten.t_lag_hg:
                if is_mixed:
                    # Gl. 14: effektive Leistung sinkt mit steigender mittlerer Speichertemperatur
                    theta_m = daten.theta_c + (q_aktuell / q_max) * (daten.theta_sto_max - daten.theta_c)
                    anteil = 1 - (theta_m - daten.theta_c) / (theta_ch_hg - daten.theta_c)
                    phi_eff = daten.phi_n * max(0.0, anteil)
                else:
                    # Gl. 13: konstante effektive Leistung bei Speicherladesystemen
                    phi_eff = daten.phi_n
                q_eff = phi_eff / 60.0  # kW -> kWh je Minute (Gl. 17)

        q_aktuell = q_aktuell + q_eff - bedarf_je_minute[t] - q_verlust

        if erzeuger_laeuft and q_aktuell >= q_max:
            q_aktuell = q_max
            erzeuger_laeuft = False
            laufzeit_min = 0
            zyklen.append(Einschaltzyklus(start_t, t))

        ladezustand.append(q_aktuell)
        versorgung_netto.append(
            versorgung_netto[-1] + q_eff - q_verlust
        )

    if erzeuger_laeuft:
        zyklen.append(Einschaltzyklus(start_t, n))

    return Versorgungsergebnis(
        bedarfskennlinie=bedarfskennlinie,
        versorgungskennlinie=np.array(versorgung_netto),
        ladezustand=np.array(ladezustand),
        zyklen=zyklen,
        q_sto_max=q_max,
        q_sto_on=q_on,
        q_sto_min=q_min,
        ladezustand_ende=q_aktuell,
    )
