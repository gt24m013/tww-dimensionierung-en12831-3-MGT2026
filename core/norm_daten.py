"""Zugriff auf die anwenderseitig bereitgestellten Werte aus Anhang B der
ÖNORM EN 12831-3.

Die Werte selbst sind nicht Bestandteil dieses Programms: Anhang B ist
urheberrechtlich geschützt und darf nicht weitergegeben werden. Dieses Modul
lädt sie deshalb aus einer der beiden folgenden Quellen, in dieser Reihenfolge:

1. `core/norm_werte_lokal.py` - Ihre eigene Kopie mit den Werten aus Ihrem
   Normexemplar. Diese Datei ist über .gitignore von der Versionsverwaltung
   ausgenommen.
2. `core/norm_werte_vorlage.py` - die mitgelieferte Vorlage mit frei erfundenen
   Platzhaltern. Damit startet und rechnet das Tool, die Ergebnisse sind aber
   NICHT normkonform.

Welche Quelle aktiv ist, steht in QUELLE; IST_NORMKONFORM zeigt an, ob mit
echten Normwerten gerechnet wird. Beides wird in der Oberfläche und in den
Ergebnisprotokollen ausgewiesen.

Wie Sie Ihre Werte eintragen, steht im Kopf von core/norm_werte_vorlage.py.
"""

import importlib.util

# Gezielt nachsehen, ob die lokale Datei existiert, statt den Import in ein
# try/except zu setzen: so bleibt ein Fehler INNERHALB von norm_werte_lokal.py
# (Tippfehler, unvollständige Werte) sichtbar, statt stillschweigend auf die
# Vorlage zurückzufallen.
if importlib.util.find_spec("core.norm_werte_lokal") is not None:  # pragma: no cover
    from core import norm_werte_lokal as _quelle
else:
    from core import norm_werte_vorlage as _quelle

GEBAEUDETYP_WOHNUNG: str = _quelle.GEBAEUDETYP_WOHNUNG
GEBAEUDETYP_EFH: str = _quelle.GEBAEUDETYP_EFH

LASTPROFILE_STUNDENANTEILE: dict[str, list[float]] = dict(_quelle.LASTPROFILE_STUNDENANTEILE)

X_MAX_SPEZ_VOLUMEN: float = _quelle.X_MAX_SPEZ_VOLUMEN
Y_SPEZ_VOLUMEN: float = _quelle.Y_SPEZ_VOLUMEN

GEBAEUDETYP_KOEFFIZIENTEN: dict[str, tuple[float, float, float]] = dict(
    _quelle.GEBAEUDETYP_KOEFFIZIENTEN
)
N_P_EQ_BEZUGSWERT: float = _quelle.N_P_EQ_BEZUGSWERT
N_P_EQ_STEIGUNG: float = _quelle.N_P_EQ_STEIGUNG
N_P_EQ_DAEMPFUNG: float = _quelle.N_P_EQ_DAEMPFUNG

IST_NORMKONFORM: bool = bool(getattr(_quelle, "IST_NORMKONFORM", False))
QUELLE: str = str(getattr(_quelle, "QUELLE", _quelle.__name__))

HINWEIS_PLATZHALTER = (
    "Es wird mit Platzhalterwerten gerechnet, nicht mit den Werten aus Anhang B "
    "der ÖNORM EN 12831-3. Die Ergebnisse sind daher nicht normkonform. Wie Sie "
    "Ihre eigenen Normwerte eintragen, steht im Kopf von "
    "core/norm_werte_vorlage.py."
)

if not LASTPROFILE_STUNDENANTEILE:
    raise ValueError(f"Es ist kein einziges Lastprofil hinterlegt (Quelle: {QUELLE}).")

for _name, _werte in LASTPROFILE_STUNDENANTEILE.items():
    if len(_werte) != 24:
        raise ValueError(
            f"Lastprofil '{_name}' hat {len(_werte)} statt 24 Stundenwerte "
            f"(Quelle: {QUELLE})."
        )

for _typ in (GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH):
    if _typ not in GEBAEUDETYP_KOEFFIZIENTEN:
        raise ValueError(
            f"Für den Gebäudetyp '{_typ}' fehlen die Koeffizienten des "
            f"Verfahrens C (Quelle: {QUELLE})."
        )

# Profil, mit dem Datenmodell und Oberfläche starten. Bewusst namentlich
# festgelegt statt über die Position in der Liste, damit ein Umsortieren oder
# Ergänzen der Profile die Vorbelegung nicht still verändert.
STANDARD_PROFIL: str = str(getattr(_quelle, "STANDARD_PROFIL", ""))
if STANDARD_PROFIL not in LASTPROFILE_STUNDENANTEILE:
    STANDARD_PROFIL = next(iter(LASTPROFILE_STUNDENANTEILE))


def ergaenze_lastprofil(name: str, stundenanteile: list[float]) -> None:
    """Nimmt ein zur Laufzeit geladenes Lastprofil in die Auswahl auf.

    Wird vom CSV-Import der Oberfläche verwendet, damit ein Profil auch ohne
    Anlegen von `core/norm_werte_lokal.py` genutzt werden kann. Das Profil gilt
    nur für die laufende Sitzung und wird nirgends gespeichert.
    """
    if len(stundenanteile) != 24:
        raise ValueError(
            f"Ein Lastprofil braucht genau 24 Stundenwerte, erhalten: {len(stundenanteile)}."
        )
    if sum(stundenanteile) <= 0:
        raise ValueError("Die Summe der Stundenanteile muss größer als 0 sein.")
    LASTPROFILE_STUNDENANTEILE[name] = [float(w) for w in stundenanteile]
