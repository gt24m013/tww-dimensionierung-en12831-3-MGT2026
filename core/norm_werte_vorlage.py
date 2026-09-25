"""VORLAGE für die anwenderseitig einzutragenden Werte aus Anhang B der
ÖNORM EN 12831-3.

Diese Datei enthält KEINE Normwerte. Die hier eingetragenen Zahlen sind frei
erfundene Platzhalter, damit das Tool ohne weitere Vorbereitung startet und
vollständig bedienbar ist. Rechenergebnisse, die auf diesen Platzhaltern
beruhen, sind NICHT normkonform - das Tool weist im Kopf der Oberfläche und in
jedem Ergebnisprotokoll darauf hin.

Der Grund für diese Trennung: Anhang B der ÖNORM EN 12831-3 ist urheberrechtlich
geschützt. Die Norm ist kostenpflichtig zu beziehen (in Österreich über Austrian
Standards, in Deutschland über den Beuth Verlag); ihre Tabellenwerke dürfen
nicht weitergegeben werden. Der Rechengang selbst - die Gleichungen 1 bis 21 und
der minutenweise Algorithmus nach 6.4.3.3 - ist als eigene Implementierung in
core/ enthalten und von dieser Einschränkung nicht betroffen.


SO TRAGEN SIE IHRE WERTE EIN
============================

1. Diese Datei kopieren und die Kopie `norm_werte_lokal.py` nennen, im selben
   Ordner (core/). Unter Windows in der PowerShell:

       Copy-Item core/norm_werte_vorlage.py core/norm_werte_lokal.py

2. In der Kopie die Platzhalter durch die Werte aus Ihrem Normexemplar ersetzen.
   Wo die Werte jeweils stehen, ist bei jedem Eintrag vermerkt.

3. Am Ende der Kopie IST_NORMKONFORM = True setzen.

`norm_werte_lokal.py` ist über .gitignore von der Versionsverwaltung
ausgenommen und wird dadurch nicht versehentlich veröffentlicht. Liegt die Datei
vor, verwendet das Tool automatisch sie statt dieser Vorlage.

Alternativ lassen sich Lastprofile auch ohne diese Datei nutzen: in der
Seitenleiste des Tools unter "Lastprofil aus CSV laden" (Format siehe
beispiele/demo_zapfprofil.csv).
"""

# ---------------------------------------------------------------------------
# Gebäudetypen des Verfahrens C. Reine Bezeichner, keine Normwerte - unverändert
# lassen, sie werden an mehreren Stellen im Programm zum Vergleich herangezogen.
# ---------------------------------------------------------------------------
GEBAEUDETYP_WOHNUNG = "Wohnung"
GEBAEUDETYP_EFH = "Einfamilien-/Reihenhaus"


# ---------------------------------------------------------------------------
# 1. Lastprofile: stündliche Anteile am Tagesbedarf [%], 24 Werte je Profil,
#    beginnend bei 00:00.
#
#    Quelle in der Norm: Anhang B.1 (Bild 4). Übernehmen Sie die Profile, die
#    Sie tatsächlich benötigen; die Namen der Einträge sind frei wählbar und
#    erscheinen unverändert in der Auswahlliste des Tools.
#
#    Die Anteile müssen sich nicht exakt auf 100 summieren - das Tool
#    normiert die Reihe ohnehin auf das berechnete Tagesvolumen.
# ---------------------------------------------------------------------------
LASTPROFILE_STUNDENANTEILE: dict[str, list[float]] = {
    # PLATZHALTER - frei erfundenes Profil eines Wohngebäudes mit Morgen- und
    # Abendspitze. Ersetzen oder löschen Sie diesen Eintrag.
    "Demo-Profil (synthetisch, nicht normkonform) [%]": [
        1.5, 0.8, 0.5, 0.4, 0.5, 1.2,   # 00:00-05:59
        3.5, 7.0, 8.5, 6.5, 5.0, 4.5,   # 06:00-11:59
        5.5, 4.5, 3.5, 3.5, 4.0, 5.5,   # 12:00-17:59
        7.5, 8.0, 7.0, 5.5, 3.5, 2.1,   # 18:00-23:59
    ],
    # Beispiel für einen eigenen Eintrag - Werte aus Anhang B.1 einsetzen:
    # "Profil M [%]": [0, 0, 0, ...],   # 24 Werte
}

# Profil, mit dem die Oberfläche startet. Muss ein Schlüssel aus
# LASTPROFILE_STUNDENANTEILE sein; ist der Name unbekannt, wird der erste
# Eintrag verwendet.
STANDARD_PROFIL = "Demo-Profil (synthetisch, nicht normkonform) [%]"

# ---------------------------------------------------------------------------
# 2. Vorgabewerte x und y der Gleichung (B.5):
#        V_W,P,day = min( x ; y * A_h / n_P,eq )
#
#    Quelle in der Norm: Anhang B.2.2. Liegt ein nationaler Anhang mit
#    abweichenden Werten vor, gelten dessen Werte; sie lassen sich zusätzlich
#    zur Laufzeit in der Seitenleiste des Tools überschreiben.
# ---------------------------------------------------------------------------
X_MAX_SPEZ_VOLUMEN = 40.0   # PLATZHALTER - x [l/(Person*d)]
Y_SPEZ_VOLUMEN = 3.0        # PLATZHALTER - y [l/(m²*d)]


# ---------------------------------------------------------------------------
# 3. Koeffizienten der äquivalenten Personenanzahl n_P,eq (Verfahren C).
#
#    Quelle in der Norm: Anhang B.2.2, Gleichungen (B.1)/(B.2) für
#    Einfamilien- und Reihenhäuser sowie (B.3)/(B.4) für Wohnungen.
#
#    n_P,eq,max(A_h) ist dort abschnittsweise über der bewohnbaren Fläche A_h
#    definiert und hat in beiden Fällen dieselbe Gestalt:
#
#        A_h  <  flaeche_min     ->  1
#        A_h  <  flaeche_bezug   ->  bezugswert - steigung * (flaeche_bezug - A_h)
#        A_h  >= flaeche_bezug   ->  flaechenfaktor * A_h
#
#    Tragen Sie je Gebäudetyp die drei Größen aus Ihrem Normexemplar ein:
#    die beiden Intervallgrenzen und den Faktor des oberen Astes.
# ---------------------------------------------------------------------------
#    Die Platzhalter unten sind so gewählt, dass die Funktion an beiden
#    Intervallgrenzen stetig ist (flaechenfaktor * flaeche_bezug = bezugswert
#    und bezugswert - steigung * (flaeche_bezug - flaeche_min) = 1). Achten Sie
#    beim Eintragen Ihrer Werte darauf, dass diese Bedingung erhalten bleibt -
#    tests/test_core.py prüft sie.
GEBAEUDETYP_KOEFFIZIENTEN: dict[str, tuple[float, float, float]] = {
    #                     flaeche_min, flaeche_bezug, flaechenfaktor
    GEBAEUDETYP_WOHNUNG: (20.0,        60.0,          0.0300),  # PLATZHALTER
    GEBAEUDETYP_EFH:     (40.0,        80.0,          0.0225),  # PLATZHALTER
}

# Gemeinsame Größen beider Gebäudetypen:
# - N_P_EQ_BEZUGSWERT ist der Funktionswert an der oberen Intervallgrenze und
#   zugleich die Schwelle, ab der n_P,eq gegenüber n_P,eq,max abgemindert wird.
# - N_P_EQ_STEIGUNG ist die Steigung des mittleren Astes.
# - N_P_EQ_DAEMPFUNG ist der Faktor der Abminderung oberhalb des Bezugswerts:
#       n_P,eq = bezugswert + daempfung * (n_P,eq,max - bezugswert)
N_P_EQ_BEZUGSWERT = 1.80    # PLATZHALTER
N_P_EQ_STEIGUNG = 0.02000   # PLATZHALTER
N_P_EQ_DAEMPFUNG = 0.25     # PLATZHALTER


# ---------------------------------------------------------------------------
# 4. Kennzeichnung der Herkunft.
#
#    Solange IST_NORMKONFORM auf False steht, blendet das Tool in der
#    Oberfläche und in jedem Ergebnisprotokoll einen Warnhinweis ein. Setzen
#    Sie den Wert in Ihrer Kopie auf True, sobald alle Platzhalter oben durch
#    die Werte Ihres Normexemplars ersetzt sind.
# ---------------------------------------------------------------------------
IST_NORMKONFORM = False
QUELLE = "Vorlage mit Platzhalterwerten (core/norm_werte_vorlage.py)"
