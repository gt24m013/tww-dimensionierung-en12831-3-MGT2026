# -*- coding: utf-8 -*-
"""Erzeugt die Programmstruktur als zweiseitiges A4-PDF für den Druck.

Das große Übersichtsdiagramm (erzeuge_ablaufdiagramm.py) ist 76 x 90 cm groß
und auf eine A4-Seite gebracht nicht mehr lesbar. Diese Fassung verteilt
denselben Inhalt auf zwei A4-Seiten im Querformat:

    Teil 1  Eingabe, Aufbereitung und Simulation
    Teil 2  Auswertung je Modus und Ausgabe

Die Seiten sind in Zoll bemaßt (1 Einheit = 1 Zoll), die Schriftgrößen in
Punkt - dadurch entspricht die Darstellung hier der späteren Druckgröße, und
6,5 pt bleiben in der gedruckten Arbeit lesbar.

Aufruf aus dem Projektverzeichnis:

    python abbildungen/erzeuge_ablaufdiagramm_a4.py

Geschrieben wird abbildungen/Berechnungsablaufdiagramm_A4.pdf.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

AUSGABE = Path(__file__).resolve().parent / "Berechnungsablaufdiagramm_A4.pdf"

plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})

# A4 quer, Ränder wie in einer Arbeit mit 2 cm Seitenrand
SEITE_B, SEITE_H = 11.69, 8.27
RAND_X, RAND_O, RAND_U = 0.55, 0.78, 0.30
NUTZ_B = SEITE_B - 2 * RAND_X
NUTZ_L, NUTZ_R = RAND_X, SEITE_B - RAND_X

TEXT = "#1B2733"
TEXT_SEK = "#55636F"
TEXT_MODUL = "#7C8794"
LINIE = "#8A96A3"
RAHMEN = "#BAC4CE"
FLAECHE = "#FBFCFD"
FLAECHE_STUFE = "#F1F4F7"
AKZENT = "#1F4E79"
AKZENT_FLAECHE = "#EAF1F8"

FS_TITEL = 7.4        # Überschrift im Kasten
FS_ZEILE = 6.5        # Erläuterungszeile
FS_MODUL = 5.9        # Modulangabe
ZEILE_H = 0.155       # Zeilenabstand in Zoll
POLSTER = 0.20


def neue_seite(untertitel):
    fig = plt.figure(figsize=(SEITE_B, SEITE_H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, SEITE_B)
    ax.set_ylim(0, SEITE_H)
    ax.axis("off")
    fig.text(RAND_X / SEITE_B, 1 - 0.30 / SEITE_H,
             "Programmstruktur des Berechnungswerkzeugs",
             ha="left", va="center", fontsize=10.5, fontweight="bold", color=TEXT)
    fig.text(RAND_X / SEITE_B, 1 - 0.52 / SEITE_H, untertitel,
             ha="left", va="center", fontsize=7.6, color=TEXT_SEK)
    return fig, ax, {}


def box(ax, boxes, key, cx, cy, w, titel, zeilen=(), modul=None,
        flaeche=FLAECHE, rahmen=RAHMEN, lw=0.8, titel_farbe=TEXT,
        fs_titel=FS_TITEL):
    zeilen = list(zeilen)
    n = 1 + len(zeilen) + (1 if modul else 0)
    h = POLSTER + n * ZEILE_H

    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.008,rounding_size=0.045",
        linewidth=lw, edgecolor=rahmen, facecolor=flaeche, zorder=2))

    y = cy + (n - 1) * ZEILE_H / 2
    ax.text(cx, y, titel, ha="center", va="center", fontsize=fs_titel,
            fontweight="bold", color=titel_farbe, zorder=3)
    for zeile in zeilen:
        y -= ZEILE_H
        ax.text(cx, y, zeile, ha="center", va="center", fontsize=FS_ZEILE,
                color=TEXT_SEK, zorder=3)
    if modul:
        y -= ZEILE_H
        ax.text(cx, y, modul, ha="center", va="center", fontsize=FS_MODUL,
                color=TEXT_MODUL, family="DejaVu Sans Mono", zorder=3)

    boxes[key] = dict(cx=cx, cy=cy, w=w, h=h)


def raute(ax, boxes, key, cx, cy, text, w=1.5, h=0.52):
    ax.add_patch(Polygon(
        [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
        closed=True, linewidth=0.8, edgecolor=LINIE, facecolor=FLAECHE_STUFE,
        zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=FS_TITEL,
            fontweight="bold", color=TEXT, zorder=3)
    boxes[key] = dict(cx=cx, cy=cy, w=w, h=h)


def _k(boxes, key):
    b = boxes[key]
    return dict(x=b["cx"], oben=b["cy"] + b["h"] / 2, unten=b["cy"] - b["h"] / 2)


def _pfeil(ax, x, y_von, y_bis):
    ax.add_patch(FancyArrowPatch(
        (x, y_von), (x, y_bis), arrowstyle="-|>", mutation_scale=6,
        linewidth=0.8, color=LINIE, zorder=1, shrinkA=0, shrinkB=1))


def senkrecht(ax, boxes, von, nach):
    a, b = _k(boxes, von), _k(boxes, nach)
    ax.add_patch(FancyArrowPatch(
        (a["x"], a["unten"]), (b["x"], b["oben"]), arrowstyle="-|>",
        mutation_scale=6, linewidth=0.8, color=LINIE, zorder=1,
        shrinkA=0, shrinkB=1))


def kette(ax, boxes, *keys):
    for oben, unten in zip(keys, keys[1:]):
        senkrecht(ax, boxes, oben, unten)


def verteiler(ax, boxes, von, ziele, y_bus):
    a = _k(boxes, von)
    ax.plot([a["x"], a["x"]], [a["unten"], y_bus], color=LINIE, lw=0.8, zorder=1)
    xs = [boxes[k]["cx"] for k in ziele]
    ax.plot([min(xs), max(xs)], [y_bus, y_bus], color=LINIE, lw=0.8, zorder=1)
    for k in ziele:
        b = _k(boxes, k)
        _pfeil(ax, b["x"], y_bus, b["oben"])


def sammler(ax, boxes, quellen, ziel, y_bus):
    xs = []
    for k in quellen:
        b = _k(boxes, k)
        xs.append(b["x"])
        ax.plot([b["x"], b["x"]], [b["unten"], y_bus], color=LINIE, lw=0.8, zorder=1)
    ax.plot([min(xs), max(xs)], [y_bus, y_bus], color=LINIE, lw=0.8, zorder=1)
    z = _k(boxes, ziel)
    _pfeil(ax, z["x"], y_bus, z["oben"])


def phase(ax, text, y):
    ax.text(NUTZ_L + 0.02, y, text.upper(), ha="left", va="center",
            fontsize=5.8, fontweight="bold", color=TEXT_MODUL, zorder=3)


# ============================================================ Seite 1
def seite_eingabe_und_simulation(pdf):
    fig, ax, b = neue_seite("Teil 1 von 2 — Eingabe, Aufbereitung und Simulation")

    mitte = SEITE_B / 2
    spur = 3.45
    breit_in = 3.25

    box(ax, b, "start", mitte, 7.18, 5.2, "Modusauswahl in der Bedienoberfläche",
        modul="app.py", flaeche=FLAECHE_STUFE, fs_titel=8.2)

    box(ax, b, "in_anlage", mitte - spur, 6.15, breit_in, "Anlagenparameter",
        ["Speicher, Erzeuger, Verluste, Temperaturen",
         "mehrere Speicher als ein Rechenspeicher"],
        "core/modell.py · core/speicherverbund.py")
    box(ax, b, "in_norm", mitte, 6.15, breit_in, "Bedarfsparameter",
        ["Personen, Nutzungseinheiten oder Wohnfläche",
         "Lastprofil aus Normwerten oder CSV-Datei"],
        "core/norm_daten.py · core/lastprofil.py")
    box(ax, b, "in_mon", mitte + spur, 6.15, breit_in, "Messdaten aus dem Monitoring",
        ["Zapfprofil aus Excel, optional mit Zeitstempel",
         "Bemessungstag und Bemessungswoche"],
        "core/monitoring.py")

    box(ax, b, "p_norm", mitte, 4.95, breit_in, "Zapfprofil aus dem Tagesbedarf",
        ["Tagesvolumen gleichmäßig auf Minutenwerte verteilt"],
        "core/bedarf.py")
    box(ax, b, "p_mon", mitte + spur, 4.95, breit_in, "Zapfprofil aus der Messreihe",
        ["Spalten- und Zeitstempelprüfung, Auflösung auf 1 min"],
        "core/monitoring.py")

    box(ax, b, "zapfprofil", mitte + spur / 2, 4.05, 5.4,
        "Zapfprofil in Minutenwerten — ein Tag oder eine Woche",
        flaeche=FLAECHE_STUFE)

    box(ax, b, "simulation", mitte, 2.95, 8.6, "Simulation der Energieversorgung",
        ["Der Speicherladezustand wird Minute für Minute fortgeschrieben:",
         "Entnahme, Speicher- und Verteilverluste, Nacherhitzung durch den Erzeuger",
         "Ergebnis: Bedarfs- und Versorgungskennlinie, Ladezustand, Einschaltzyklen"],
        "core/versorgung.py", flaeche=AKZENT_FLAECHE, rahmen=AKZENT, lw=1.2,
        titel_farbe=AKZENT, fs_titel=8.2)

    box(ax, b, "kriterium", mitte, 1.85, 8.6, "Prüfung gegen das Normkriterium",
        ["Der Ladezustand darf zu keinem Zeitpunkt die zulässige Restkapazität unterschreiten.",
         "In den Optimierungsmodi zusätzlich: höchste Tageslaufzeit und Erholung des Speichers."],
        flaeche=FLAECHE_STUFE, rahmen=AKZENT, titel_farbe=AKZENT)

    box(ax, b, "weiter", mitte, 0.85, 5.2, "Verzweigung nach Modus",
        ["Fortsetzung in Teil 2"], flaeche=FLAECHE_STUFE)

    verteiler(ax, b, "start", ["in_anlage", "in_norm", "in_mon"], y_bus=6.72)
    senkrecht(ax, b, "in_norm", "p_norm")
    senkrecht(ax, b, "in_mon", "p_mon")
    sammler(ax, b, ["p_norm", "p_mon"], "zapfprofil", y_bus=4.45)
    sammler(ax, b, ["in_anlage", "zapfprofil"], "simulation", y_bus=3.52)
    kette(ax, b, "simulation", "kriterium", "weiter")

    phase(ax, "Eingabe", 6.15)
    phase(ax, "Aufbereitung", 4.95)
    phase(ax, "Simulation", 2.95)

    pdf.savefig(fig)
    plt.close(fig)


# ============================================================ Seite 2
def seite_auswertung(pdf):
    fig, ax, b = neue_seite("Teil 2 von 2 — Auswertung je Modus und Ausgabe")

    modi = ["A", "B", "C", "D", "E", "F"]
    spalte_w = 1.73
    gap = 0.11
    gesamt = len(modi) * spalte_w + (len(modi) - 1) * gap
    x0 = (SEITE_B - gesamt) / 2
    mx = {m: x0 + i * (spalte_w + gap) + spalte_w / 2 for i, m in enumerate(modi)}
    mitte = SEITE_B / 2

    box(ax, b, "von_teil1", mitte, 7.32, 5.0, "Aus Teil 1: geprüfte Simulation",
        flaeche=FLAECHE_STUFE)
    raute(ax, b, "verzweigung", mitte, 6.75, "Modus")

    kopf = {
        "A": ("Modus A / A2", "Auslegung nach Norm"),
        "B": ("Modus B", "Auslegung nach Messdaten"),
        "C": ("Modus C", "Soll-Ist-Vergleich"),
        "D": ("Modus D", "Investitionsoptimierung"),
        "E": ("Modus E", "über Kostenfunktionen"),
        "F": ("Modus F", "techno-ökonomisch"),
    }
    for m in modi:
        titel, unter = kopf[m]
        box(ax, b, f"head_{m}", mx[m], 5.95, spalte_w, titel, [unter],
            flaeche=FLAECHE_STUFE, rahmen=LINIE, lw=1.0, fs_titel=8.0)

    # Zeilenabstand so gewählt, dass die längste Kette (Modus F mit fünf
    # Stufen) samt Ausgabeblock auf der Seite bleibt.
    y1, y2, y3, y4, y5 = 5.08, 4.13, 3.18, 2.23, 1.28

    box(ax, b, "A1", mx["A"], y1, spalte_w, "Ergebnisdarstellung",
        ["Kennlinien, Ladezustand,", "Wochenprüfung"], "core/visualisierung.py")
    box(ax, b, "B1", mx["B"], y1, spalte_w, "Ergebnisdarstellung",
        ["wie Modus A, mit gemessenem", "Zapfprofil und Verlust"], "core/visualisierung.py")

    box(ax, b, "C1", mx["C"], y1, spalte_w, "Gegenüberstellung",
        ["Kennzahlen Soll gegen Ist,", "Hinweis auf Fehldimensionierung"], "core/vergleich.py")
    box(ax, b, "C2", mx["C"], y2, spalte_w, "Ergebnis",
        ["überlagerte Kennlinien", "und Protokoll"])

    katalog = ("Produktkataloge einlesen",
               ["Listenpreise, Rabatte,", "Montagekosten"],
               "core/katalog.py · rabatt.py")

    box(ax, b, "D1", mx["D"], y1, spalte_w, *katalog)
    box(ax, b, "D2", mx["D"], y2, spalte_w, "Kombinationen prüfen",
        ["jede Paarung aus Erzeuger", "und Speicher einzeln simuliert"], "core/investition.py")
    box(ax, b, "D3", mx["D"], y3, spalte_w, "Ergebnis",
        ["günstigste zulässige", "Kombination mit Rangliste"])

    box(ax, b, "E1", mx["E"], y1, spalte_w, *katalog)
    box(ax, b, "E2", mx["E"], y2, spalte_w, "Kostenfunktionen anpassen",
        ["degressiver Verlauf je", "Erzeuger und Speicher"], "core/kostenfunktion.py")
    box(ax, b, "E3", mx["E"], y3, spalte_w, "Rastersuche",
        ["stufenloser Auslegungsraum,", "30 bis 200 % des Referenzwerts"],
        "core/systemoptimierung.py")
    box(ax, b, "E4", mx["E"], y4, spalte_w, "Ergebnis",
        ["Kostenoptimum und Randpunkte,", "bewertete Zustände A, A2, B"])

    box(ax, b, "F1", mx["F"], y1, spalte_w, *katalog)
    box(ax, b, "F2", mx["F"], y2, spalte_w, "Kombinationen prüfen",
        ["jede Paarung gegen Bemessungs-", "tag und Bemessungswoche"], "core/investition.py")
    box(ax, b, "F3", mx["F"], y3, spalte_w, "Pareto-Front",
        ["nicht dominierte Kombinationen", "aus Kosten und Schalthäufigkeit"],
        "core/investition.py")
    box(ax, b, "F4", mx["F"], y4, spalte_w, "Drei Vorzugsvarianten",
        ["technisch: wenigste Schaltungen", "wirtschaftlich: geringste Kosten",
         "Kompromiss: gewichtete Summe"])
    box(ax, b, "F5", mx["F"], y5, spalte_w, "Ergebnis",
        ["Pareto-Diagramm und", "Variantenvergleich"])

    box(ax, b, "ausgabe", mitte, 0.42, NUTZ_B, "Ausgabe",
        ["Diagramme, Parameterprotokoll, PDF-Export, Projektstand sichern und laden"],
        "core/visualisierung.py · core/protokoll.py · core/projekt.py",
        flaeche=FLAECHE_STUFE, lw=1.0, fs_titel=8.2)

    senkrecht(ax, b, "von_teil1", "verzweigung")
    verteiler(ax, b, "verzweigung", [f"head_{m}" for m in modi], y_bus=6.35)
    kette(ax, b, "head_A", "A1")
    kette(ax, b, "head_B", "B1")
    kette(ax, b, "head_C", "C1", "C2")
    kette(ax, b, "head_D", "D1", "D2", "D3")
    kette(ax, b, "head_E", "E1", "E2", "E3", "E4")
    kette(ax, b, "head_F", "F1", "F2", "F3", "F4", "F5")
    sammler(ax, b, ["A1", "B1", "C2", "D3", "E4", "F5"], "ausgabe", y_bus=0.82)

    # Auf dieser Seite reichen die Spalten bis an den Rand - eine Beschriftung
    # am linken Rand wie auf Seite 1 würde in den ersten Kasten laufen.

    pdf.savefig(fig)
    plt.close(fig)


with PdfPages(AUSGABE) as pdf:
    seite_eingabe_und_simulation(pdf)
    seite_auswertung(pdf)

print("geschrieben:", AUSGABE)
