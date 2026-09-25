# -*- coding: utf-8 -*-
"""Erzeugt das Berechnungsablaufdiagramm des TWW-Dimensionierungstools.

Abgebildet wird die Programmstruktur: welche Eingaben in welches Modul laufen,
wo die gemeinsame Simulation sitzt und wie sich die Auswertung danach je Modus
verzweigt. Bewusst ohne Gleichungs- und Abschnittsverweise - die fachliche
Herleitung steht in der Dokumentation, die Abbildung zeigt den Programmaufbau.

Aufruf aus dem Projektverzeichnis:

    python abbildungen/erzeuge_ablaufdiagramm.py

Geschrieben werden abbildungen/Berechnungsablaufdiagramm.png und .svg.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

AUSGABE = Path(__file__).resolve().parent / "Berechnungsablaufdiagramm"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "none",
})

# --------------------------------------------------------------- Farbwelt
# Zurückhaltend und weitgehend einfarbig: Struktur entsteht über Rahmen,
# Flächenhelligkeit und Typografie, nicht über bunte Kategorien. Ein einziger
# Akzent hebt die Stufe hervor, die alle Modi gemeinsam durchlaufen.
TEXT = "#1B2733"
TEXT_SEK = "#55636F"
TEXT_MODUL = "#7C8794"
LINIE = "#8A96A3"
RAHMEN = "#BAC4CE"
FLAECHE = "#FBFCFD"
FLAECHE_STUFE = "#F1F4F7"
AKZENT = "#1F4E79"
AKZENT_FLAECHE = "#EAF1F8"

# --------------------------------------------------------------- Raster
SPALTE_W = 4.0          # einheitliche Spaltenbreite für alle Modi
SPALTE_GAP = 0.5
RAND_L, RAND_R = 2.9, 0.6   # links Platz für die Phasenbeschriftung

MODI = ["A", "B", "C", "D", "E", "F"]
mode_x = {}
cursor = RAND_L
for _m in MODI:
    mode_x[_m] = cursor + SPALTE_W / 2
    cursor += SPALTE_W + SPALTE_GAP
FIG_W = cursor - SPALTE_GAP + RAND_R
CENTER_X = RAND_L + (cursor - SPALTE_GAP - RAND_L) / 2

Y_MIN, Y_MAX = -10.1, 25.4
FIG_H = Y_MAX - Y_MIN   # 1:1 zwischen Datenmaß und Zoll, damit nichts verzerrt

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, FIG_W)
ax.set_ylim(Y_MIN, Y_MAX)
ax.axis("off")

boxes = {}

ZEILE_H = 0.42          # Zeilenabstand innerhalb einer Box
POLSTER = 0.62          # Luft über der ersten und unter der letzten Zeile


def box(key, cx, cy, titel, zeilen=(), modul=None, *, w=SPALTE_W,
        flaeche=FLAECHE, rahmen=RAHMEN, lw=1.1, titel_size=9.6,
        zeilen_size=8.3, titel_farbe=TEXT, breit=False):
    """Kasten mit fetter Überschrift, erläuternden Zeilen und Modulangabe.

    Die Höhe ergibt sich aus der Zeilenzahl, damit alle Kästen denselben
    inneren Rhythmus haben, statt jeden einzeln von Hand zu bemaßen.
    """
    zeilen = list(zeilen)
    n = 1 + len(zeilen) + (1 if modul else 0)
    h = POLSTER + n * ZEILE_H

    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.015,rounding_size=0.10",
        linewidth=lw, edgecolor=rahmen, facecolor=flaeche, zorder=2,
    ))

    y = cy + (n - 1) * ZEILE_H / 2
    ax.text(cx, y, titel, ha="center", va="center", fontsize=titel_size,
            fontweight="bold", color=titel_farbe, zorder=3)
    for zeile in zeilen:
        y -= ZEILE_H
        ax.text(cx, y, zeile, ha="center", va="center", fontsize=zeilen_size,
                color=TEXT_SEK, zorder=3)
    if modul:
        y -= ZEILE_H
        ax.text(cx, y, modul, ha="center", va="center", fontsize=7.6,
                color=TEXT_MODUL, family="DejaVu Sans Mono", zorder=3)

    boxes[key] = dict(cx=cx, cy=cy, w=w, h=h)


def raute(key, cx, cy, text, w=3.2, h=1.5):
    ax.add_patch(Polygon(
        [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
        closed=True, linewidth=1.1, edgecolor=LINIE, facecolor=FLAECHE_STUFE,
        zorder=2,
    ))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=9.6,
            fontweight="bold", color=TEXT, zorder=3)
    boxes[key] = dict(cx=cx, cy=cy, w=w, h=h)


def kante(key):
    b = boxes[key]
    return dict(oben=b["cy"] + b["h"] / 2, unten=b["cy"] - b["h"] / 2, x=b["cx"])


def senkrecht(von, nach, lw=1.1):
    """Pfeil von Unterkante zu Oberkante innerhalb derselben Spalte.

    Für Verbindungen zwischen verschiedenen Spalten werden verteiler() und
    sammler() verwendet: sie führen über eine waagrechte Schiene, sodass alle
    Verbindungen rechtwinklig bleiben und die Abbildung auch bei sechs Spalten
    ruhig wirkt.
    """
    a, b = kante(von), kante(nach)
    ax.add_patch(FancyArrowPatch(
        (a["x"], a["unten"]), (b["x"], b["oben"]), arrowstyle="-|>",
        mutation_scale=11, linewidth=lw, color=LINIE, zorder=1,
        shrinkA=0, shrinkB=1.5,
    ))


def kette(*keys):
    for oben, unten in zip(keys, keys[1:]):
        senkrecht(oben, unten)


def verteiler(von, ziele, y_bus):
    a = kante(von)
    ax.plot([a["x"], a["x"]], [a["unten"], y_bus], color=LINIE, lw=1.1, zorder=1)
    xs = [boxes[k]["cx"] for k in ziele]
    ax.plot([min(xs), max(xs)], [y_bus, y_bus], color=LINIE, lw=1.1, zorder=1)
    for k in ziele:
        b = kante(k)
        ax.add_patch(FancyArrowPatch(
            (b["x"], y_bus), (b["x"], b["oben"]), arrowstyle="-|>",
            mutation_scale=11, linewidth=1.1, color=LINIE, zorder=1,
            shrinkA=0, shrinkB=1.5,
        ))


def sammler(quellen, ziel, y_bus):
    xs = []
    for k in quellen:
        b = kante(k)
        xs.append(b["x"])
        ax.plot([b["x"], b["x"]], [b["unten"], y_bus], color=LINIE, lw=1.1, zorder=1)
    ax.plot([min(xs), max(xs)], [y_bus, y_bus], color=LINIE, lw=1.1, zorder=1)
    z = kante(ziel)
    ax.add_patch(FancyArrowPatch(
        (z["x"], y_bus), (z["x"], z["oben"]), arrowstyle="-|>",
        mutation_scale=11, linewidth=1.1, color=LINIE, zorder=1,
        shrinkA=0, shrinkB=1.5,
    ))


def phase(text, y):
    """Beschriftung der Ablaufphase am linken Rand, anstelle einer Legende."""
    ax.text(RAND_L - 0.75, y, text.upper(), ha="right", va="center",
            fontsize=8.6, fontweight="bold", color=TEXT_MODUL, zorder=3)


# =============================================================== Start
box("start", CENTER_X, 24.3, "Modusauswahl in der Bedienoberfläche",
    modul="app.py", w=13.0, flaeche=FLAECHE_STUFE, titel_size=10.4)

# =============================================================== Eingabe
SPUR = 8.6
box("in_anlage", CENTER_X - SPUR, 21.6, "Anlagenparameter",
    ["Speicher, Erzeuger, Verluste, Temperaturen",
     "mehrere Speicher als ein Rechenspeicher"],
    "core/modell.py · core/speicherverbund.py", w=7.6)
box("in_norm", CENTER_X, 21.6, "Bedarfsparameter",
    ["Personen, Nutzungseinheiten oder Wohnfläche",
     "Lastprofil aus Normwerten oder CSV-Datei"],
    "core/norm_daten.py · core/lastprofil.py", w=7.6)
box("in_mon", CENTER_X + SPUR, 21.6, "Messdaten aus dem Monitoring",
    ["Zapfprofil aus Excel, optional mit Zeitstempel",
     "Bemessungstag und Bemessungswoche"],
    "core/monitoring.py", w=7.6)

# =============================================================== Aufbereitung
box("p_norm", CENTER_X, 18.6, "Zapfprofil aus dem Tagesbedarf",
    ["Tagesvolumen gleichmäßig auf Minutenwerte verteilt"],
    "core/bedarf.py", w=7.6)
box("p_mon", CENTER_X + SPUR, 18.6, "Zapfprofil aus der Messreihe",
    ["Spalten- und Zeitstempelprüfung, Auflösung auf 1 min"],
    "core/monitoring.py", w=7.6)

box("zapfprofil", CENTER_X + SPUR / 2, 16.2,
    "Zapfprofil in Minutenwerten — ein Tag oder eine Woche",
    w=11.5, flaeche=FLAECHE_STUFE)

# =============================================================== Simulation
box("simulation", CENTER_X, 13.4, "Simulation der Energieversorgung",
    ["Der Speicherladezustand wird Minute für Minute fortgeschrieben:",
     "Entnahme, Speicher- und Verteilverluste, Nacherhitzung durch den Erzeuger",
     "Ergebnis: Bedarfs- und Versorgungskennlinie, Ladezustand, Einschaltzyklen"],
    "core/versorgung.py", w=17.0,
    flaeche=AKZENT_FLAECHE, rahmen=AKZENT, lw=1.6,
    titel_size=10.6, zeilen_size=8.8, titel_farbe=AKZENT)

box("kriterium", CENTER_X, 10.7, "Prüfung gegen das Normkriterium",
    ["Der Ladezustand darf zu keinem Zeitpunkt die zulässige Restkapazität unterschreiten.",
     "In den Optimierungsmodi zusätzlich: höchste Tageslaufzeit und Erholung des Speichers."],
    w=17.0, flaeche=FLAECHE_STUFE, rahmen=AKZENT, lw=1.1, titel_farbe=AKZENT)

raute("verzweigung", CENTER_X, 8.35, "Modus")

# =============================================================== Modi
kopf = {
    "A": ("Modus A / A2", ["Auslegung nach Norm"]),
    "B": ("Modus B", ["Auslegung nach Messdaten"]),
    "C": ("Modus C", ["Soll-Ist-Vergleich"]),
    "D": ("Modus D", ["Investitionsoptimierung"]),
    "E": ("Modus E", ["Optimierung über Kostenfunktionen"]),
    "F": ("Modus F", ["Techno-ökonomische Optimierung"]),
}
Y_KOPF = 6.5
for m in MODI:
    titel, zeilen = kopf[m]
    box(f"head_{m}", mode_x[m], Y_KOPF, titel, zeilen,
        flaeche=FLAECHE_STUFE, rahmen=LINIE, lw=1.3, titel_size=10.0)

Y1, Y2, Y3, Y4, Y5 = 4.1, 1.5, -1.1, -3.7, -6.3

box("A1", mode_x["A"], Y1, "Ergebnisdarstellung",
    ["Kennlinien, Ladezustand, Wochenprüfung",
     "A2 hinterlegt den Soll-Zustand für Modus C"],
    "core/visualisierung.py")
box("B1", mode_x["B"], Y1, "Ergebnisdarstellung",
    ["wie Modus A, jedoch mit gemessenem",
     "Zapfprofil und gemessenem Verlust"],
    "core/visualisierung.py")

box("C1", mode_x["C"], Y1, "Gegenüberstellung",
    ["Kennzahlen im Soll-Ist-Vergleich, Hinweis",
     "auf Unter- und Überdimensionierung"],
    "core/vergleich.py")
box("C2", mode_x["C"], Y2, "Ergebnis",
    ["überlagerte Kennlinien und Protokoll"])

KATALOG = ("Produktkataloge einlesen",
           ["Listenpreise, Rabatte und Montagekosten"],
           "core/katalog.py · rabatt.py · montage.py")

box("D1", mode_x["D"], Y1, *KATALOG)
box("D2", mode_x["D"], Y2, "Kombinationen prüfen",
    ["jede Paarung aus Erzeuger und Speicher",
     "wird einzeln simuliert und bewertet"],
    "core/investition.py")
box("D3", mode_x["D"], Y3, "Ergebnis",
    ["günstigste zulässige Kombination", "mit Rangliste"])

box("E1", mode_x["E"], Y1, *KATALOG)
box("E2", mode_x["E"], Y2, "Kostenfunktionen anpassen",
    ["degressiver Verlauf je Erzeuger und Speicher"],
    "core/kostenfunktion.py · kostenregression.py")
box("E3", mode_x["E"], Y3, "Rastersuche",
    ["stufenloser Auslegungsraum aus Volumen",
     "und Leistung, 30 bis 200 % des Referenzwerts"],
    "core/systemoptimierung.py")
box("E4", mode_x["E"], Y4, "Ergebnis",
    ["Kostenoptimum und Randpunkte, dazu die",
     "bewerteten Zustände aus A, A2 und B"])

box("F1", mode_x["F"], Y1, *KATALOG)
box("F2", mode_x["F"], Y2, "Kombinationen prüfen",
    ["jede Paarung gegen Bemessungstag",
     "und Bemessungswoche"],
    "core/investition.py")
box("F3", mode_x["F"], Y3, "Pareto-Front",
    ["nicht dominierte Kombinationen aus",
     "Investitionskosten und Schalthäufigkeit"],
    "core/investition.py")
box("F4", mode_x["F"], Y4, "Drei Vorzugsvarianten",
    ["technisch: geringste Schalthäufigkeit",
     "wirtschaftlich: geringste Kosten",
     "Kompromiss: gewichtete Summe beider Ziele"])
box("F5", mode_x["F"], Y5, "Ergebnis",
    ["Pareto-Diagramm und Variantenvergleich"])

# =============================================================== Ausgabe
box("ausgabe", CENTER_X, -8.6, "Ausgabe",
    ["Diagramme, Parameterprotokoll, PDF-Export, Projektstand sichern und laden"],
    "core/visualisierung.py · core/protokoll.py · core/projekt.py",
    w=FIG_W - RAND_L - RAND_R, flaeche=FLAECHE_STUFE, lw=1.3, titel_size=10.4)

# =============================================================== Verbindungen
verteiler("start", ["in_anlage", "in_norm", "in_mon"], y_bus=23.0)
senkrecht("in_norm", "p_norm")
senkrecht("in_mon", "p_mon")
sammler(["p_norm", "p_mon"], "zapfprofil", y_bus=17.0)
# Die Anlagenparameter gehen an der Zapfprofil-Aufbereitung vorbei direkt in
# die Simulation - ihre Spalte ist darunter frei, die Linie kreuzt nichts.
sammler(["in_anlage", "zapfprofil"], "simulation", y_bus=14.9)
kette("simulation", "kriterium", "verzweigung")

verteiler("verzweigung", [f"head_{m}" for m in MODI], y_bus=7.55)

kette("head_A", "A1")
kette("head_B", "B1")
kette("head_C", "C1", "C2")
kette("head_D", "D1", "D2", "D3")
kette("head_E", "E1", "E2", "E3", "E4")
kette("head_F", "F1", "F2", "F3", "F4", "F5")

sammler(["A1", "B1", "C2", "D3", "E4", "F5"], "ausgabe", y_bus=-7.6)

# =============================================================== Phasen links
phase("Eingabe", 21.6)
phase("Aufbereitung", 17.4)
phase("Simulation", 12.0)
phase("Auswertung\nje Modus", 1.0)
phase("Ausgabe", -8.6)

# =============================================================== Titel
fig.suptitle("Berechnungsablauf des TWW-Dimensionierungstools",
             fontsize=17, fontweight="bold", color=TEXT, y=0.9955)
fig.text(0.5, 0.9835,
         "Bedienoberfläche app.py mit den Berechnungsmodulen in core/ — "
         "Auslegung nach ÖNORM EN 12831-3",
         ha="center", fontsize=10.5, color=TEXT_SEK)

fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.978])

fig.savefig(f"{AUSGABE}.png", dpi=150, facecolor="white")
fig.savefig(f"{AUSGABE}.svg", facecolor="white")
print("geschrieben:", f"{AUSGABE}.png", "/", f"{AUSGABE}.svg",
      "| Größe:", fig.get_size_inches())
