"""Einlesen eigener Lastprofile aus CSV-Dateien.

Damit lässt sich das Tool auch ohne Eintragen der Werte in
core/norm_werte_lokal.py mit einem eigenen Profil betreiben: Wer die ÖNORM
EN 12831-3 besitzt, überträgt ein Profil aus Anhang B.1 einmal in eine
CSV-Datei; wer ein gemessenes Profil verwenden will, exportiert es aus seiner
Auswertung. Geladene Profile gelten nur für die laufende Sitzung.

Erwartet werden 24 Stundenanteile des Tagesbedarfs in Prozent, beginnend bei
00:00. Zulässig sind eine Wertespalte mit oder ohne vorangestellte
Stundenspalte, Semikolon, Komma, Tabulator oder Leerzeichen als Trennzeichen,
Dezimalpunkt oder Dezimalkomma sowie eine optionale Kopfzeile. Beispiel und
ausführliche Beschreibung: beispiele/LIESMICH.md.
"""

import re

STUNDEN_PRO_TAG = 24


class LastprofilFehler(Exception):
    """Die Datei enthält kein verwertbares Lastprofil."""


def _zahl(feld: str) -> float:
    """Wandelt ein Feld in eine Zahl, Dezimalkomma eingeschlossen."""
    text = feld.strip().replace("%", "").strip()
    if "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        raise LastprofilFehler(f"'{feld.strip()}' ist keine Zahl.") from None


def _werte_aus_text(text: str) -> list[float]:
    zeilen = [z.strip() for z in text.replace("﻿", "").splitlines()]
    zeilen = [z for z in zeilen if z and not z.startswith("#")]
    if not zeilen:
        raise LastprofilFehler("Die Datei ist leer.")

    # Kopfzeile erkennen: enthält Buchstaben (Spaltennamen), aber keine
    # verwertbaren Zahlen wie "1.5".
    if any(zeichen.isalpha() for zeichen in zeilen[0]):
        zeilen = zeilen[1:]
        if not zeilen:
            raise LastprofilFehler("Die Datei enthält nur eine Kopfzeile.")

    if len(zeilen) == 1:
        # Alle Werte stehen in einer einzigen Zeile.
        felder = [f for f in re.split(r"[;\t,\s]+", zeilen[0]) if f]
        return [_zahl(f) for f in felder]

    werte = []
    for zeile in zeilen:
        felder = [f for f in re.split(r"[;\t]+", zeile) if f]
        if len(felder) == 1:
            felder = [f for f in re.split(r"\s+", zeile) if f]
        # Bei zwei Spalten ist die erste die Stunde, die zweite der Anteil.
        werte.append(_zahl(felder[-1]))
    return werte


def lies_csv(datei, name: str | None = None) -> tuple[str, list[float]]:
    """Liest ein Lastprofil aus `datei` und gibt (Name, 24 Stundenanteile) zurück.

    `datei` ist ein Dateiobjekt (etwa aus st.file_uploader) oder ein Pfad.
    `name` überschreibt den aus dem Dateinamen abgeleiteten Profilnamen.
    """
    rohdaten = datei.read() if hasattr(datei, "read") else open(datei, "rb").read()
    if isinstance(rohdaten, bytes):
        for kodierung in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                text = rohdaten.decode(kodierung)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise LastprofilFehler("Die Zeichenkodierung der Datei wird nicht erkannt.")
    else:
        text = rohdaten

    werte = _werte_aus_text(text)

    if len(werte) != STUNDEN_PRO_TAG:
        raise LastprofilFehler(
            f"Erwartet werden {STUNDEN_PRO_TAG} Stundenwerte, gefunden wurden {len(werte)}."
        )
    if any(wert < 0 for wert in werte):
        raise LastprofilFehler("Negative Stundenanteile sind nicht zulässig.")
    if sum(werte) <= 0:
        raise LastprofilFehler("Die Summe der Stundenanteile muss größer als 0 sein.")

    if name is None:
        dateiname = getattr(datei, "name", "Eigenes Profil")
        name = str(dateiname).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        name = re.sub(r"\.(csv|txt)$", "", name, flags=re.IGNORECASE)
    return f"{name} (geladen) [%]", werte
