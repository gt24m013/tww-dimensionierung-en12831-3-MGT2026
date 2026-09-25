"""Diagramme zur Normauslegung, analog Bild 12 (Bedarfs- und Versorgungskennlinie).

Jedes Panel wird von einer eigenen `_zeichne_*`-Funktion gezeichnet, die nur
eine gegebene Axes befüllt (Kurven, Achsenbeschriftung, Legende - aber ohne
Titel). Die `plot_*`-Funktionen setzen diese Panels zu einer Gesamtübersicht
zusammen (mit kurzen Titeln); die `einzelfiguren_*`-Funktionen liefern
dieselben Panels als eigenständige, titellose Einzel-Figures - z. B. um sie
ohne Überschrift als PDF zu exportieren und in einer Abbildung mit eigener
Bildunterschrift zu verwenden.
"""

from collections import OrderedDict

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from core.versorgung import Versorgungsergebnis
from core.investition import Kombination
from core.systemoptimierung import Rasterpunkt, Anlagenkosten
from core.kostenregression import Regressionsgruppe
from core.kostenfunktion import Kostenfunktion

# Etwas größere Achsen-/Tick-Beschriftung als der matplotlib-Default (10 pt), für bessere
# Lesbarkeit sowohl im Streamlit-Preview als auch im PDF-Export - deutlich zurückhaltender als in
# Berichtsabbildungen (dort oft 16-18 pt), da hier auch mehrere Panels pro Seite Platz finden müssen.
plt.rcParams.update({
    "axes.labelsize": 12,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
})

MINUTEN_PRO_TAG = 1440
LEGEND_FONTSIZE = 10

# Panel-Schlüssel -> (Dateiname-Stub, Kurztitel für die Gesamtübersicht)
PANEL_ERGEBNIS = OrderedDict([
    ("zapfprofil", "Zapfprofil"),
    ("energiebedarfskennlinie", "Energiebedarfskennlinie"),
    ("energieversorgungskennlinie", "Energieversorgungskennlinie"),
    ("nacherhitzungsleistung", "Momentane Nacherhitzungsleistung"),
    ("speicherbewirtschaftung", "Speicherbewirtschaftung"),
    ("summenkennlinien_vergleich", "Summenkennlinien-Vergleich"),
])

PANEL_VERGLEICH = OrderedDict([
    ("zapfprofil", "Zapfprofil (Soll vs. Ist)"),
    ("energiebedarfskennlinie", "Energiebedarfskennlinie (Soll vs. Ist)"),
    ("energieversorgungskennlinie", "Energieversorgungskennlinie (Soll vs. Ist)"),
    ("nacherhitzungsleistung", "Momentane Nacherhitzungsleistung (Soll vs. Ist)"),
    ("speicherbewirtschaftung", "Speicherbewirtschaftung (Soll vs. Ist)"),
    ("summenkennlinien_vergleich", "Summenkennlinien-Vergleich (Soll vs. Ist)"),
])


def _formatiere_achse(ax, dauer_min: int):
    ax.grid(True, alpha=0.15)
    ax.set_xlim(0, dauer_min)
    if dauer_min > MINUTEN_PRO_TAG:
        # Mehrtägige Auswertung (Wochenanalyse): Achse auf 24-h-Schritte takten
        # (Simulation bleibt minutenbasiert, nur Ticks/Beschriftung sind in h)
        anzahl_tage = dauer_min // MINUTEN_PRO_TAG
        ticks = [MINUTEN_PRO_TAG * i for i in range(anzahl_tage + 1)]
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"{i * 24} h" for i in range(anzahl_tage + 1)])
        ax.set_xlabel(r"Zeit $t$ [h]")
        for grenze in ticks[1:-1]:
            ax.axvline(grenze, color="#B0BEC5", lw=0.7, zorder=0)
    else:
        ax.set_xlabel(r"Zeit $t$ [min]")


# ---------------------------------------------------------------- Einzelpanels: Modus A/B (eine Kurve)
# Achsenbeschriftungen (Symbol + Einheit) gemäß ÖNORM EN 12831-3:2018, Tabelle 2 (Symbole und
# Einheiten) und Bild 12 (Bedarfs- und Versorgungskennlinie, Legende: Y = kumulierte Energiemenge
# [kWh]; 5 = effektive Leistung Φeff [W]) sowie Gl. (3) (Vt = abgezapftes Volumen in der Zeit t [l]).
FARBE_ZAPFPROFIL_NORM = "#008844"        # grün: normatives, stundenbasiertes Lastprofil (Soll)
FARBE_ZAPFPROFIL_MONITORING = "#4A90D9"  # helles Blau: reale, minutenbasierte Monitoring-Messdaten (Ist)


def _zeichne_mittellinie(ax, werte, farbe: str = "#CC0000", praefix: str = "Mittel") -> Line2D:
    """Gestrichelte Linie beim Mittelwert des Zapfprofils über den gesamten Auswertungszeitraum
    (Tag oder Woche). Gibt nur das Legenden-Handle zurück (Beschriftung inkl. Zahlenwert), statt
    den Wert als Text ins Diagramm zu schreiben - bei der Wochenauswertung mit vielen Spitzen würde
    ein Text an der Linie sonst leicht mit Datenpunkten kollidieren."""
    mittel = float(np.mean(werte))
    ax.axhline(mittel, color=farbe, ls="--", lw=1.3, alpha=0.85, zorder=4)
    return Line2D([], [], color=farbe, ls="--", lw=1.3, alpha=0.85, label=f"{praefix} {mittel:.2f} l/min")


def _zeichne_zapfprofil(ax, t, zapfprofil_l_min, farbe: str = FARBE_ZAPFPROFIL_NORM):
    ax.fill_between(t, 0, zapfprofil_l_min, color=farbe, alpha=0.3)
    ax.plot(t, zapfprofil_l_min, color=farbe, lw=1.5)
    mittel_handle = _zeichne_mittellinie(ax, zapfprofil_l_min)
    ax.legend(handles=[mittel_handle], loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)
    ax.set_ylabel(r"$V_t$ [l/min]")


def _zeichne_bedarfskennlinie(ax, t, ergebnis: Versorgungsergebnis):
    ax.plot(t, ergebnis.bedarfskennlinie, color="#004488", lw=2)
    ax.set_ylabel(r"Kumulierte Energiemenge $Q_{W,b}$ [kWh]")


def _zeichne_versorgungskennlinie(ax, t, ergebnis: Versorgungsergebnis):
    ax.plot(t, ergebnis.versorgungskennlinie[:-1], color="#CC0000", lw=1.5)
    ax.set_ylabel(r"Kumulierte Energiemenge $Q$ [kWh]")


def _zeichne_leistung(ax, t, ergebnis: Versorgungsergebnis):
    leistung_kw = np.gradient(ergebnis.versorgungskennlinie[:-1]) * 60
    ax.plot(t, leistung_kw, color="#CC6600")
    ax.set_ylabel(r"Nacherhitzungsleistung $\Phi_{eff}$ [kW]")


def _zeichne_speicherbewirtschaftung(ax, t, ergebnis: Versorgungsergebnis):
    ax.plot(t, ergebnis.ladezustand, color="#994C00", lw=1.5, label="Ladezustand (SOC)")
    ax.axhline(ergebnis.q_sto_on, color="red", ls=":", alpha=0.6, label=r"Einschaltpunkt $Q_{sto,ON}$")
    ax.axhline(ergebnis.q_sto_max, color="green", ls=":", alpha=0.4, label=r"$Q_{sto,max}$")
    if ergebnis.q_sto_min > 0:
        ax.axhline(ergebnis.q_sto_min, color="orange", ls="--", alpha=0.6, label=r"$Q_{sto,min}$")
    ax.set_ylabel(r"Speicherkapazität $Q_{sto}$ [kWh]")
    # Legende in die leere Fläche links unterhalb des ersten Entladevorgangs,
    # nicht in die äußerste Ecke (dort sonst zu nah am Rand).
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.16), fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_summenkennlinie(ax, t, ergebnis: Versorgungsergebnis):
    versorgung_summenlinie = ergebnis.bedarfskennlinie + ergebnis.ladezustand
    q_sto_on_linie = ergebnis.bedarfskennlinie + ergebnis.q_sto_on
    ax.plot(t, ergebnis.bedarfskennlinie, color="#004488", lw=2, label="1: Bedarfskennlinie")
    ax.plot(t, versorgung_summenlinie, color="#CC0000", lw=1.5, label="2: Versorgungskennlinie (Bedarf + Speicherreserve)")
    ax.plot(t, q_sto_on_linie, color="red", ls=":", lw=1, alpha=0.6, label=r"3: $Q_{sto,ON}$-Linie")
    ax.fill_between(t, ergebnis.bedarfskennlinie, versorgung_summenlinie, color="gray", alpha=0.1, label="Speicherreserve")
    ax.set_ylabel(r"Kumulierte Energiemenge $Q$ [kWh]")
    ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _panels_ergebnis(zapfprofil_l_min, ergebnis, farbe_zapfprofil: str = FARBE_ZAPFPROFIL_NORM):
    t = range(len(zapfprofil_l_min))
    return OrderedDict([
        ("zapfprofil", lambda ax: _zeichne_zapfprofil(ax, t, zapfprofil_l_min, farbe=farbe_zapfprofil)),
        ("energiebedarfskennlinie", lambda ax: _zeichne_bedarfskennlinie(ax, t, ergebnis)),
        ("energieversorgungskennlinie", lambda ax: _zeichne_versorgungskennlinie(ax, t, ergebnis)),
        ("nacherhitzungsleistung", lambda ax: _zeichne_leistung(ax, t, ergebnis)),
        ("speicherbewirtschaftung", lambda ax: _zeichne_speicherbewirtschaftung(ax, t, ergebnis)),
        ("summenkennlinien_vergleich", lambda ax: _zeichne_summenkennlinie(ax, t, ergebnis)),
    ])


def plot_ergebnis(
    zapfprofil_l_min: np.ndarray, ergebnis: Versorgungsergebnis, titel: bool = True,
    farbe_zapfprofil: str = FARBE_ZAPFPROFIL_NORM,
) -> Figure:
    fig, axes = plt.subplots(6, 1, figsize=(11, 24), sharex=False)
    panels = _panels_ergebnis(zapfprofil_l_min, ergebnis, farbe_zapfprofil=farbe_zapfprofil)
    for ax, (key, zeichnen) in zip(axes, panels.items()):
        zeichnen(ax)
        if titel:
            ax.set_title(PANEL_ERGEBNIS[key])
        _formatiere_achse(ax, len(zapfprofil_l_min))
    fig.tight_layout()
    return fig


def einzelfiguren_ergebnis(
    zapfprofil_l_min: np.ndarray, ergebnis: Versorgungsergebnis,
    farbe_zapfprofil: str = FARBE_ZAPFPROFIL_NORM,
) -> "OrderedDict[str, Figure]":
    """Jedes Panel aus plot_ergebnis() als eigenständige, titellose Figure -
    zum Einzelexport (z. B. für eine Abbildung mit eigener Bildunterschrift)."""
    panels = _panels_ergebnis(zapfprofil_l_min, ergebnis, farbe_zapfprofil=farbe_zapfprofil)
    figuren = OrderedDict()
    for key, zeichnen in panels.items():
        fig, ax = plt.subplots(figsize=(9, 5))
        zeichnen(ax)
        _formatiere_achse(ax, len(zapfprofil_l_min))
        fig.tight_layout()
        figuren[key] = fig
    return figuren


# ---------------------------------------------------------------- Einzelpanels: Modus C (Soll vs. Ist)
def _zeichne_zapfprofil_vergleich(ax, t, zapf_soll, zapf_ist):
    ax.fill_between(t, 0, zapf_soll, color=FARBE_ZAPFPROFIL_NORM, alpha=0.25, label="Soll (Norm)")
    ax.plot(t, zapf_soll, color=FARBE_ZAPFPROFIL_NORM, lw=1.5)
    ax.plot(t, zapf_ist, color=FARBE_ZAPFPROFIL_MONITORING, lw=1.2, alpha=0.8, label="Ist (Monitoring)")
    mittel_soll = _zeichne_mittellinie(ax, zapf_soll, farbe=FARBE_ZAPFPROFIL_NORM, praefix="Mittel Soll")
    mittel_ist = _zeichne_mittellinie(ax, zapf_ist, farbe=FARBE_ZAPFPROFIL_MONITORING, praefix="Mittel Ist")
    ax.set_ylabel(r"$V_t$ [l/min]")
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles=handles + [mittel_soll, mittel_ist], loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_bedarfskennlinie_vergleich(ax, t, erg_soll, erg_ist):
    ax.plot(t, erg_soll.bedarfskennlinie, color="#008844", ls="--", lw=2, label="Soll-Bedarf")
    ax.plot(t, erg_ist.bedarfskennlinie, color="#004488", lw=1.5, label="Ist-Bedarf")
    ax.set_ylabel(r"Kumulierte Energiemenge $Q_{W,b}$ [kWh]")
    ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_versorgungskennlinie_vergleich(ax, t, erg_soll, erg_ist):
    ax.plot(t, erg_soll.versorgungskennlinie[:-1], color="#008844", ls="--", lw=2, label="Soll-Versorgung")
    ax.plot(t, erg_ist.versorgungskennlinie[:-1], color="#CC0000", lw=1.5, label="Ist-Versorgung")
    ax.set_ylabel(r"Kumulierte Energiemenge $Q$ [kWh]")
    ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_leistung_vergleich(ax, t, erg_soll, erg_ist):
    leistung_soll = np.gradient(erg_soll.versorgungskennlinie[:-1]) * 60
    leistung_ist = np.gradient(erg_ist.versorgungskennlinie[:-1]) * 60
    ax.plot(t, leistung_soll, color="#008844", ls="--", alpha=0.7, label="Soll-Leistung")
    ax.plot(t, leistung_ist, color="#CC0000", alpha=0.8, label="Ist-Leistung")
    ax.set_ylabel(r"Nacherhitzungsleistung $\Phi_{eff}$ [kW]")
    ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_speicherbewirtschaftung_vergleich(ax, t, erg_soll, erg_ist):
    ax.plot(t, erg_soll.ladezustand, color="#008844", ls="--", lw=1.5, label="Soll-SOC")
    ax.plot(t, erg_ist.ladezustand, color="#CC6600", lw=1.5, label="Ist-SOC")
    ax.axhline(erg_soll.q_sto_on, color="red", ls=":", alpha=0.6, label=r"Einschaltpunkt $Q_{sto,ON}$")
    ax.axhline(erg_soll.q_sto_max, color="green", ls=":", alpha=0.4, label=r"$Q_{sto,max}$")
    if erg_soll.q_sto_min > 0:
        ax.axhline(erg_soll.q_sto_min, color="orange", ls="--", alpha=0.6, label=r"$Q_{sto,min}$")
    ax.set_ylabel(r"Speicherkapazität $Q_{sto}$ [kWh]")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.16), fontsize=LEGEND_FONTSIZE, frameon=False)


def _zeichne_summenkennlinie_vergleich(ax, t, erg_soll, erg_ist):
    summenlinie_soll = erg_soll.bedarfskennlinie + erg_soll.ladezustand
    summenlinie_ist = erg_ist.bedarfskennlinie + erg_ist.ladezustand
    ax.plot(t, erg_soll.bedarfskennlinie, color="#008844", lw=2, label="1: Bedarfskennlinie (Soll)")
    ax.plot(t, summenlinie_soll, color="#008844", ls="--", lw=1.5, alpha=0.9, label="2: Versorgungskennlinie (Soll)")
    ax.plot(t, erg_ist.bedarfskennlinie, color="#004488", lw=2, label="1: Bedarfskennlinie (Ist)")
    ax.plot(t, summenlinie_ist, color="#CC0000", ls="--", lw=1.5, alpha=0.9, label="2: Versorgungskennlinie (Ist)")
    ax.fill_between(t, erg_soll.bedarfskennlinie, summenlinie_soll, color="#008844", alpha=0.07)
    ax.set_ylabel(r"Kumulierte Energiemenge $Q$ [kWh]")
    ax.legend(loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=False)


def _panels_vergleich(zapf_soll, erg_soll, zapf_ist, erg_ist):
    t = range(len(zapf_soll))
    return OrderedDict([
        ("zapfprofil", lambda ax: _zeichne_zapfprofil_vergleich(ax, t, zapf_soll, zapf_ist)),
        ("energiebedarfskennlinie", lambda ax: _zeichne_bedarfskennlinie_vergleich(ax, t, erg_soll, erg_ist)),
        ("energieversorgungskennlinie", lambda ax: _zeichne_versorgungskennlinie_vergleich(ax, t, erg_soll, erg_ist)),
        ("nacherhitzungsleistung", lambda ax: _zeichne_leistung_vergleich(ax, t, erg_soll, erg_ist)),
        ("speicherbewirtschaftung", lambda ax: _zeichne_speicherbewirtschaftung_vergleich(ax, t, erg_soll, erg_ist)),
        ("summenkennlinien_vergleich", lambda ax: _zeichne_summenkennlinie_vergleich(ax, t, erg_soll, erg_ist)),
    ])


def plot_vergleich(
    zapf_soll: np.ndarray, erg_soll: Versorgungsergebnis,
    zapf_ist: np.ndarray, erg_ist: Versorgungsergebnis, titel: bool = True,
) -> Figure:
    """Überlagerte Darstellung Norm (Soll) vs. Monitoring (Ist), analog Bild 12."""
    fig, axes = plt.subplots(6, 1, figsize=(11, 24), sharex=False)
    panels = _panels_vergleich(zapf_soll, erg_soll, zapf_ist, erg_ist)
    for ax, (key, zeichnen) in zip(axes, panels.items()):
        zeichnen(ax)
        if titel:
            ax.set_title(PANEL_VERGLEICH[key])
        _formatiere_achse(ax, len(zapf_soll))
    fig.tight_layout()
    return fig


def einzelfiguren_vergleich(
    zapf_soll: np.ndarray, erg_soll: Versorgungsergebnis,
    zapf_ist: np.ndarray, erg_ist: Versorgungsergebnis,
) -> "OrderedDict[str, Figure]":
    """Jedes Panel aus plot_vergleich() als eigenständige, titellose Figure."""
    panels = _panels_vergleich(zapf_soll, erg_soll, zapf_ist, erg_ist)
    figuren = OrderedDict()
    for key, zeichnen in panels.items():
        fig, ax = plt.subplots(figsize=(9, 5))
        zeichnen(ax)
        _formatiere_achse(ax, len(zapf_soll))
        fig.tight_layout()
        figuren[key] = fig
    return figuren


# ---------------------------------------------------------------- Modus D/E: Streudiagramme (bereits Einzelpanel)
def plot_investitionsoptimierung(kombinationen: list[Kombination], titel: bool = True) -> Figure:
    """Streudiagramm Speichervolumen vs. WP-Leistung, eingefärbt nach Investkosten.

    Unzulässige Kombinationen (Norm-Kriterium nicht erfüllt) werden grau/x
    dargestellt, die günstigste zulässige Kombination wird hervorgehoben.
    """
    fig, ax = plt.subplots(figsize=(9, 6))

    zulaessig = [k for k in kombinationen if k.zulaessig]
    unzulaessig = [k for k in kombinationen if not k.zulaessig]

    if unzulaessig:
        ax.scatter(
            [k.speicher_volumen_l for k in unzulaessig],
            [k.wp_leistung_kw for k in unzulaessig],
            marker="x", color="lightgray", s=40, label="Unzulässig (Norm-Kriterium verletzt)",
        )

    if zulaessig:
        sc = ax.scatter(
            [k.speicher_volumen_l for k in zulaessig],
            [k.wp_leistung_kw for k in zulaessig],
            c=[k.gesamtkosten for k in zulaessig],
            cmap="viridis_r", s=70, edgecolors="black", linewidths=0.5, label="Zulässig",
        )
        plt.colorbar(sc, ax=ax, label="Investkosten [€]")

        beste = min(zulaessig, key=lambda k: k.gesamtkosten)
        ax.scatter(
            [beste.speicher_volumen_l], [beste.wp_leistung_kw],
            marker="s", facecolor="none", edgecolor="red", s=220, linewidths=2,
            label=f"Günstigste zulässige Kombination ({beste.gesamtkosten:,.0f} €)",
        )

    ax.set_xlabel(r"Speichervolumen $V_{sto}$ [l]")
    ax.set_ylabel(r"WP-Nennleistung $\Phi_N$ [kW]")
    if titel:
        ax.set_title("Investitionsoptimierung: Speicher- vs. WP-Wahl")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="best", fontsize=LEGEND_FONTSIZE, frameon=True)
    fig.tight_layout()
    return fig


def plot_pareto_front(
    kombinationen: list[Kombination], pareto: list[Kombination],
    technisch: Kombination | None = None, oekonomisch: Kombination | None = None,
    kompromiss: Kombination | None = None, titel: bool = True,
) -> Figure:
    """Zielkonflikt Gesamtkosten vs. Schalthäufigkeit (Modus F): alle
    zulässigen Kombinationen als Punktwolke, die Pareto-Front (nicht
    dominierte Kombinationen) als Stufenlinie hervorgehoben, plus die drei
    gewählten Varianten (technisch/ökonomisch/techno-ökonomisch) markiert."""
    fig, ax = plt.subplots(figsize=(9, 6))

    zulaessig = [k for k in kombinationen if k.zulaessig]
    unzulaessig = [k for k in kombinationen if not k.zulaessig]

    if unzulaessig:
        # In Modus F entscheidet nicht nur das Norm-Kriterium über die
        # Zulässigkeit, sondern zusätzlich die Laufzeitgrenze und die Erholung
        # des Speichers über die Bemessungswoche - die Legende darf das nicht
        # auf das Norm-Kriterium verkürzen.
        gegen_woche = any(k.gegen_woche_geprueft for k in kombinationen)
        label_unzulaessig = (
            "Unzulässig (Norm-Kriterium, Laufzeit oder Erholung)" if gegen_woche
            else "Unzulässig (Norm-Kriterium verletzt)"
        )
        ax.scatter(
            [k.gesamtkosten for k in unzulaessig], [k.zyklen for k in unzulaessig],
            marker="x", color="lightgray", s=25, alpha=0.6, label=label_unzulaessig,
        )
    if zulaessig:
        ax.scatter(
            [k.gesamtkosten for k in zulaessig], [k.zyklen for k in zulaessig],
            color="#9ecae1", s=30, alpha=0.75, edgecolors="none", label="Zulässig",
        )
    if pareto:
        ax.plot(
            [k.gesamtkosten for k in pareto], [k.zyklen for k in pareto],
            color="#08519c", marker="o", ms=6, lw=1.5, drawstyle="steps-post",
            label=f"Pareto-Front ({len(pareto)} Kombinationen)",
        )

    if technisch is not None:
        ax.scatter(
            [technisch.gesamtkosten], [technisch.zyklen], marker="^", facecolor="none",
            edgecolor="#2E7D32", s=220, linewidths=2.2,
            label=f"V1 Technisch ({technisch.zyklen} Zyklen, {technisch.gesamtkosten:,.0f} €)",
        )
    if oekonomisch is not None:
        ax.scatter(
            [oekonomisch.gesamtkosten], [oekonomisch.zyklen], marker="s", facecolor="none",
            edgecolor="#CC0000", s=220, linewidths=2.2,
            label=f"V2 Ökonomisch ({oekonomisch.gesamtkosten:,.0f} €, {oekonomisch.zyklen} Zyklen)",
        )
    if kompromiss is not None:
        ax.scatter(
            [kompromiss.gesamtkosten], [kompromiss.zyklen], marker="D", facecolor="none",
            edgecolor="#6A1B9A", s=220, linewidths=2.2,
            label=f"V3 Techno-ökonomisch ({kompromiss.gesamtkosten:,.0f} €, {kompromiss.zyklen} Zyklen)",
        )

    ax.set_xlabel("Gesamtkosten [€]")
    ax.set_ylabel("Schalthäufigkeit (Zyklen)")
    if titel:
        ax.set_title("Techno-ökonomischer Zielkonflikt (Modus F)")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="best", fontsize=LEGEND_FONTSIZE, frameon=True)
    fig.tight_layout()
    return fig


def plot_systemoptimierung(punkte: list[Rasterpunkt], titel: bool = True) -> Figure:
    """Streudiagramm der kontinuierlichen Rastersuche (Modus E), eingefärbt
    nach den aus den Kostenfunktionen abgeleiteten Investkosten."""
    fig, ax = plt.subplots(figsize=(9, 6))

    zulaessig = [p for p in punkte if p.zulaessig]
    unzulaessig = [p for p in punkte if not p.zulaessig]

    if unzulaessig:
        ax.scatter(
            [p.v_sto for p in unzulaessig], [p.phi_n for p in unzulaessig],
            marker="x", color="lightgray", s=15, alpha=0.6, label="Unzulässig",
        )

    if zulaessig:
        sc = ax.scatter(
            [p.v_sto for p in zulaessig], [p.phi_n for p in zulaessig],
            c=[p.kosten for p in zulaessig],
            cmap="viridis_r", s=35, edgecolors="none", label="Zulässig",
        )
        plt.colorbar(sc, ax=ax, label="Investkosten (Kostenfunktion) [€]")

        guenstigste = min(zulaessig, key=lambda p: p.kosten)
        kl_leistung = min(zulaessig, key=lambda p: p.phi_n)
        kl_volumen = min(zulaessig, key=lambda p: p.v_sto)

        ax.scatter([guenstigste.v_sto], [guenstigste.phi_n], marker="s", facecolor="none",
                   edgecolor="red", s=220, linewidths=2,
                   label=f"Günstigste Kombination ({guenstigste.kosten:,.0f} €)")
        ax.scatter([kl_leistung.v_sto], [kl_leistung.phi_n], marker="^", facecolor="none",
                   edgecolor="blue", s=180, linewidths=2,
                   label=f"Minimale WP-Leistung ({kl_leistung.phi_n:.1f} kW)")
        ax.scatter([kl_volumen.v_sto], [kl_volumen.phi_n], marker="o", facecolor="none",
                   edgecolor="orange", s=180, linewidths=2,
                   label=f"Minimales Speichervolumen ({kl_volumen.v_sto:.0f} l)")

    ax.set_xlabel(r"Speichervolumen $V_{sto}$ [l]")
    ax.set_ylabel(r"WP-Nennleistung $\Phi_N$ [kW]")
    if titel:
        ax.set_title("Systemoptimierung über Kostenfunktionen (Modus E)")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="best", fontsize=LEGEND_FONTSIZE, frameon=True)
    fig.tight_layout()
    return fig


# Farben des Anlagenkosten-Vergleichs (Modus E): zwei abgestufte Blautöne für die
# beiden Kostenbestandteile, Grün/Rot für Minder-/Mehrkosten gegenüber dem Ausgangszustand.
FARBE_KOSTEN_WP = "#1f4e79"
FARBE_KOSTEN_SPEICHER = "#9ec5e0"
FARBE_MINDERKOSTEN = "#1b7837"
FARBE_MEHRKOSTEN = "#b2182b"
FARBE_AUSGANGSZUSTAND = "#4d4d4d"


def plot_anlagenkosten_vergleich(
    anlagen: list[Anlagenkosten], titel: bool = True, fusszeile: str | None = None,
    titel_text: str | None = None, modus_hinweis: bool = True,
    vollrahmen: bool = False,
) -> Figure:
    """Gestapeltes Balkendiagramm der Investitionskosten je Anlage (Modus E/F).

    Verglichen werden die mit den Kostenfunktionen bewerteten Anlagen - erster
    Eintrag ist der Ausgangszustand (Normauslegung, Modus A), auf den sich die
    Mehr-/Minderkosten der übrigen Balken beziehen. Jeder Balken ist in seine
    beiden Bestandteile (WP / Speicher) zerlegt, weil die Kostenfunktionen
    genau so aufgebaut sind; die Bezugslinie und die Pfeile zwischen Linie und
    Balkenoberkante machen die relative Einsparung direkt ablesbar.

    `titel_text` überschreibt die Überschrift: Modus F stellt damit dieselbe
    Darstellung unter „Kosten je Optimierungsvariante“, weil dort nicht nur
    ausgelegte, sondern auch optimierte Anlagen nebeneinander stehen.

    `modus_hinweis=False` lässt die Modusangabe in Klammern („(Modus A)“,
    „(Modus F)“ …) aus den Balkenbeschriftungen und aus der Legende weg. In
    der App ist sie nützlich, weil dort zwischen den Modi gewechselt wird; in
    der exportierten Abbildung hat die Bedienoberfläche des Tools dagegen
    nichts verloren - dort erklärt die Bildunterschrift den Zusammenhang.

    `vollrahmen=True` schließt den Achsenrahmen rundum (statt nur links und
    unten). Für den Export in die Arbeit gedacht, wo die Abbildung als
    abgegrenzter Block im Satzspiegel steht; in der App bleibt der offene
    Rahmen, der die Balken weniger einengt.
    """
    fig, ax = plt.subplots(figsize=(9.5, 6.4))
    x = np.arange(len(anlagen))
    wp_werte = [a.wp_kosten for a in anlagen]
    sp_werte = [a.speicher_kosten for a in anlagen]
    basis = anlagen[0].gesamtkosten
    kopf = max(a.gesamtkosten for a in anlagen)

    ax.bar(x, wp_werte, width=0.58, color=FARBE_KOSTEN_WP, zorder=3,
           label="Wärmepumpe (Listenpreis + IBN + Montage)")
    ax.bar(x, sp_werte, width=0.58, bottom=wp_werte, color=FARBE_KOSTEN_SPEICHER,
           edgecolor="white", linewidth=0.8, zorder=3, label="Speicher (Listenpreis + Montage)")
    ax.axhline(basis, color=FARBE_AUSGANGSZUSTAND, lw=1.3, linestyle="--", zorder=2)

    for i, a in enumerate(anlagen):
        # Wert je Bestandteil in den Balken, sofern das Segment groß genug ist
        for wert, unten, textfarbe in ((a.wp_kosten, 0.0, "white"),
                                        (a.speicher_kosten, a.wp_kosten, "#12384f")):
            if wert > 0.09 * kopf:
                ax.text(i, unten + wert / 2, f"{wert:,.0f} €", ha="center", va="center",
                        fontsize=10, color=textfarbe, zorder=4)

        ax.text(i, a.gesamtkosten + 0.02 * kopf, f"{a.gesamtkosten:,.0f} €",
                ha="center", va="bottom", fontsize=13, fontweight="bold", zorder=4)

        if a.ist_ausgangszustand:
            beschriftung, farbe = "Ausgangszustand", FARBE_AUSGANGSZUSTAND
        else:
            farbe = FARBE_MINDERKOSTEN if a.diff_abs < 0 else FARBE_MEHRKOSTEN
            wort = "Einsparung" if a.diff_abs < 0 else "Mehrkosten"
            beschriftung = f"{wort}\n{a.diff_pct:+.1f} %\n{a.diff_abs:+,.0f} €"
        ax.text(i, a.gesamtkosten + 0.105 * kopf, beschriftung, ha="center", va="bottom",
                fontsize=11, fontweight="bold", color="white", linespacing=1.35,
                bbox=dict(boxstyle="round,pad=0.4", facecolor=farbe, edgecolor="none", alpha=0.95),
                zorder=5)

        # Pfeil zwischen Bezugslinie und Balkenoberkante: macht die Differenz zum
        # Ausgangszustand als Strecke sichtbar; beziffert ist sie schon im Kästchen darüber.
        if not a.ist_ausgangszustand and abs(a.diff_abs) > 0.005 * basis:
            ax.annotate("", xy=(i + 0.36, a.gesamtkosten), xytext=(i + 0.36, basis),
                        arrowprops=dict(arrowstyle="<->", color=farbe, lw=1.5, shrinkA=0, shrinkB=0),
                        zorder=4)

    def _beschriftung(a: Anlagenkosten) -> str:
        # Mit Modushinweis steht der Modus in einer eigenen Zeile unter dem
        # Namen; ohne ihn bleibt nur der Name und darunter die Auslegungsgrößen.
        name = a.bezeichnung if modus_hinweis else a.bezeichnung.split(" (")[0]
        return (f"{name.replace(' (', chr(10) + '(')}\n"
                f"{a.v_sto:,.0f} l · {a.phi_n:.1f} kW")

    ax.set_xticks(x)
    ax.set_xticklabels([_beschriftung(a) for a in anlagen], fontsize=10.5)
    ax.set_ylabel("Investitionskosten [€]")
    ax.set_ylim(0, kopf * 1.42)
    ax.yaxis.set_major_formatter(lambda wert, _: f"{wert:,.0f}")
    ax.grid(True, axis="y", linestyle=":", alpha=0.45)
    ax.set_axisbelow(True)
    for rand in ("top", "right"):
        ax.spines[rand].set_visible(vollrahmen)

    handles, labels = ax.get_legend_handles_labels()
    ausgangszustand_label = (
        f"Ausgangszustand Modus A ({basis:,.0f} €)" if modus_hinweis
        else f"Ausgangszustand ({basis:,.0f} €)"
    )
    handles.append(Line2D([], [], color=FARBE_AUSGANGSZUSTAND, lw=1.3, linestyle="--",
                          label=ausgangszustand_label))
    ax.legend(handles=handles, loc="upper left", fontsize=LEGEND_FONTSIZE, frameon=True, framealpha=0.95)

    if titel:
        ax.set_title(
            titel_text or "Investitionskosten der ausgelegten Anlagen (Kostenfunktionen Modus E)",
            fontsize=12, fontweight="bold")
    fig.tight_layout()
    if fusszeile:
        fig.subplots_adjust(bottom=0.26)
        fig.text(0.012, 0.012, fusszeile, fontsize=8.5, color="#3c3c3c", va="bottom", linespacing=1.5)
    return fig


def farbzuordnung(schluessel: list[str]) -> dict[str, tuple]:
    """Weist jedem eindeutigen Schlüssel (z. B. Herstellernamen) eine feste
    Farbe aus einer qualitativen Palette zu - für konsistente Farben über
    mehrere Diagramme hinweg (Einzelplots + Gesamtübersicht: derselbe
    Hersteller hat überall dieselbe Punktfarbe)."""
    eindeutig = list(dict.fromkeys(schluessel))
    n = max(len(eindeutig), 1)
    cmap = plt.cm.tab10 if n <= 10 else plt.cm.tab20
    werte = cmap(np.linspace(0, 1, n)) if n > 1 else cmap(np.array([0.0]))
    return {s: werte[i] for i, s in enumerate(eindeutig)}


def funktions_label(funktions_praefix: str, x_mathtext: str, a: float, b: float) -> str:
    """Formatiert die Legendenbeschriftung einer Potenzfunktion als
    \\hat{C}_...(x) = a * x^b, in Mathtext-Notation passend zur Symbolik der
    Masterthesis (z. B. funktions_praefix=r"\\hat{C}_\\mathrm{I}",
    x_mathtext=r"\\Phi_N" -> "$\\hat{C}_\\mathrm{I}(\\Phi_N)$ = a · $\\Phi_N^b$")."""
    return f"${funktions_praefix}({x_mathtext})$ = {a:.2f} $\\cdot$ ${x_mathtext}^{{{b:.4f}}}$"


def _zeichne_regressionsgruppe(
    ax, g: Regressionsgruppe, x_mathtext: str, farbe, funktions_praefix: str = r"\hat{C}_\mathrm{I}",
    linienfarbe: str = "#8B0000", legend_loc: str = "upper left",
) -> None:
    """Punktwolke + degressive Kostenfunktion (Potenzkurve) einer einzelnen
    Gruppe, mit Legendenbox (Stützstellenanzahl, Funktionsgleichung, R²) -
    analog zur klassischen Darstellung von Kostenschätzfunktionen. Bei
    fallenden (degressiven) Kurven liegen die Datenpunkte oben links dicht,
    bei steigenden Kurven oben rechts - `legend_loc` entsprechend auf die
    jeweils freie Ecke setzen, damit die Legende keine Punkte verdeckt."""
    ax.scatter(g.x, g.y, s=32, color=farbe, zorder=3, edgecolors="white", linewidths=0.4)
    handles = [Line2D([], [], marker="o", linestyle="None", color=farbe, label=f"Datenpunkte (n={g.anzahl})")]
    if g.funktion is not None:
        x_lin = np.linspace(float(g.x.min()), float(g.x.max()), 80)
        ax.plot(x_lin, g.funktion(x_lin), color=linienfarbe, lw=1.8, zorder=2)
        handles.append(Line2D(
            [], [], color=linienfarbe, lw=1.8,
            label=(f"{funktions_label(funktions_praefix, x_mathtext, g.funktion.koeffizient_a, g.funktion.exponent_b)}\n"
                   f"R² = {g.funktion.r_quadrat:.4f}"),
        ))
    ax.legend(handles=handles, loc=legend_loc, fontsize=LEGEND_FONTSIZE, frameon=True)
    ax.grid(True, linestyle=":", alpha=0.4)


def einzelfigur_regression(
    g: Regressionsgruppe, x_label: str, y_label: str, x_mathtext: str, farbe,
    funktions_praefix: str = r"\hat{C}_\mathrm{I}", titel: str | None = None, legend_loc: str = "upper left",
) -> Figure:
    """Eigenständige Figure für genau eine Gruppe (ein Hersteller bzw. ein
    Hersteller+Material) - ohne `titel` titellos für den Download/Export,
    mit `titel` für die Einbettung in den Gesamt-PDF-Export."""
    fig, ax = plt.subplots(figsize=(6.5, 4.8))
    _zeichne_regressionsgruppe(ax, g, x_mathtext, farbe, funktions_praefix=funktions_praefix, legend_loc=legend_loc)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if titel:
        ax.set_title(titel, fontsize=11, fontweight="bold")
    fig.tight_layout()
    return fig


def _zeichne_kombiniert(
    ax, punkte: dict[str, Regressionsgruppe], farben: dict[str, object],
    gesamt_funktion: Kostenfunktion | None, x_mathtext: str, linienfarbe: str, legend_loc: str = "upper left",
    gesamt_label: str | None = None, funktions_praefix: str = r"\hat{C}_\mathrm{I}",
) -> None:
    """Mehrere farblich unterschiedene Punktgruppen (z. B. je Hersteller)
    plus eine einzelne gepoolte Kostenfunktion über alle Gruppen zusammen -
    für die 'alle Hersteller'- bzw. 'alle Hersteller je Material'-Übersicht.

    `gesamt_funktion` muss nur `__call__(x)` unterstützen; für die
    automatische Legendenbeschriftung "\\hat{C}(x)=a*x^b, R²=..." braucht es
    zusätzlich `koeffizient_a`/`exponent_b`/`r_quadrat`/`stuetzstellen` (wie
    bei `Kostenfunktion`). Ist `gesamt_funktion` selbst keine einzelne
    Potenzfunktion (z. B. eine Summe zweier getrennt gefitteter
    Kostenfunktionen), muss `gesamt_label` die Beschriftung vorgeben."""
    handles = []
    for name, g in punkte.items():
        farbe = farben[name]
        ax.scatter(g.x, g.y, s=26, color=farbe, alpha=0.85, zorder=3, edgecolors="white", linewidths=0.3)
        handles.append(Line2D([], [], marker="o", linestyle="None", color=farbe,
                               label=f"{g.bezeichnung} (n={g.anzahl})"))
    if gesamt_funktion is not None and punkte:
        alle_x = np.concatenate([g.x for g in punkte.values()])
        x_lin = np.linspace(float(alle_x.min()), float(alle_x.max()), 100)
        ax.plot(x_lin, gesamt_funktion(x_lin), color=linienfarbe, lw=2.2, linestyle="--", zorder=2)
        label = gesamt_label if gesamt_label is not None else (
            f"Regressionsfunktion (n={gesamt_funktion.stuetzstellen})\n"
            f"{funktions_label(funktions_praefix, x_mathtext, gesamt_funktion.koeffizient_a, gesamt_funktion.exponent_b)}\n"
            f"R² = {gesamt_funktion.r_quadrat:.4f}"
        )
        handles.append(Line2D([], [], color=linienfarbe, lw=2.2, linestyle="--", label=label))
    ax.legend(handles=handles, loc=legend_loc, fontsize=LEGEND_FONTSIZE, frameon=True)
    ax.grid(True, linestyle=":", alpha=0.4)


def einzelfigur_kombiniert(
    punkte: dict[str, Regressionsgruppe], farben: dict[str, object], gesamt_funktion,
    x_label: str, y_label: str, x_mathtext: str, linienfarbe: str = "#00008B",
    titel: str | None = None, legend_loc: str = "upper left", gesamt_label: str | None = None,
    funktions_praefix: str = r"\hat{C}_\mathrm{I}",
) -> Figure:
    """Eigenständige Figure für eine Gesamtübersicht (alle Hersteller, ggf.
    auf ein Material eingeschränkt) - ohne `titel` titellos für den
    Download/Export, mit `titel` für den Gesamt-PDF-Export."""
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    _zeichne_kombiniert(
        ax, punkte, farben, gesamt_funktion, x_mathtext, linienfarbe, legend_loc=legend_loc,
        gesamt_label=gesamt_label, funktions_praefix=funktions_praefix)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if titel:
        ax.set_title(titel, fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig


def einzelfigur_verlust_kombiniert(
    punkte: dict[str, Regressionsgruppe], farben: dict[str, object], funktionen: dict[str, Kostenfunktion],
    x_label: str, y_label: str, x_symbol: str, linienfarben: dict[str, str],
    titel: str | None = None, legend_loc: str = "upper left",
) -> Figure:
    """Ein Speicher-Gesamtplot, der beliebig viele Regressionskurven auf
    derselben Achse zeichnet (je Material eine) - anders als
    einzelfigur_kombiniert(), das nur eine einzelne gepoolte Kurve zeichnet.
    Für den Wärmeverlust-vs-Speichergröße-Plot, der je Material als eigenes
    Diagramm ausgegeben wird (`punkte`/`funktionen` dann auf dieses Material
    gefiltert); mehrere Kurven in einer Achse bleiben weiterhin möglich."""
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    handles = []
    # Das Material steht nur dann an jedem Hersteller, wenn die Achse mehrere
    # Materialien zeigt - im Diagramm je Material wäre es in jeder Zeile dasselbe.
    materialien_im_plot = {g.material for g in punkte.values()}
    for name, g in punkte.items():
        farbe = farben[name]
        ax.scatter(g.x, g.y, s=26, color=farbe, alpha=0.85, zorder=3, edgecolors="white", linewidths=0.3)
        beschriftung = (
            f"{g.bezeichnung} ({g.material}, n={g.anzahl})" if len(materialien_im_plot) > 1
            else f"{g.bezeichnung} (n={g.anzahl})"
        )
        handles.append(Line2D([], [], marker="o", linestyle="None", color=farbe, label=beschriftung))
    alle_x = np.concatenate([g.x for g in punkte.values()]) if punkte else np.array([])
    if alle_x.size:
        x_lin = np.linspace(float(alle_x.min()), float(alle_x.max()), 100)
        for material, fn in funktionen.items():
            farbe = linienfarben.get(material, "black")
            ax.plot(x_lin, fn(x_lin), color=farbe, lw=2.2, linestyle="--", zorder=2)
            handles.append(Line2D(
                [], [], color=farbe, lw=2.2, linestyle="--",
                label=(f"{material} (n={fn.stuetzstellen})\n"
                       f"K({x_symbol}) = {fn.koeffizient_a:.2f} · {x_symbol}^{fn.exponent_b:.4f}\n"
                       f"R² = {fn.r_quadrat:.4f}"),
            ))
    ax.legend(handles=handles, loc=legend_loc, fontsize=LEGEND_FONTSIZE, frameon=True)
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if titel:
        ax.set_title(titel, fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig
