"""Projektdatei: alle Eingaben eines Laufs sichern und wieder einlesen.

Zweck ist, dass die Sidebar nicht bei jedem Start neu ausgefüllt werden muss.
Gesichert wird beides - die eingegebenen Parameter UND die hochgeladenen
Excel-Dateien (Bemessungstag, Bemessungswoche, WP-Katalog, Speicher-Katalog).
Die Projektdatei ist damit in sich geschlossen: nach dem Laden ist das Tool
ohne weiteren Upload rechenbereit.

Format ist JSON (lesbar, versionierbar, als Anhang einer Arbeit zitierfähig).
Die Excel-Dateien liegen als Base64 ihrer Originalbytes darin - beim Laden
gehen sie unverändert durch dieselben Leser wie beim Hochladen, sodass sich
Parsen und Warnungen nicht unterscheiden können.

Reine Serialisierungslogik ohne Streamlit-Bezug, damit sie testbar bleibt.
"""

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

KENNUNG = "tww-dimensionierungstool-projekt"
FORMAT_VERSION = 1

# Dateislots, die eine Projektdatei transportieren kann. Der Schlüssel ist
# zugleich der Schlüssel im Datei-Depot der App.
SLOT_BEMESSUNGSTAG = "bemessungstag"
SLOT_BEMESSUNGSWOCHE = "bemessungswoche"
SLOT_WP_KATALOG = "wp_katalog"
SLOT_SPEICHER_KATALOG = "speicher_katalog"
SLOTS = (SLOT_BEMESSUNGSTAG, SLOT_BEMESSUNGSWOCHE, SLOT_WP_KATALOG, SLOT_SPEICHER_KATALOG)

SLOT_TITEL = {
    SLOT_BEMESSUNGSTAG: "Bemessungstag / Monitoring-Zapfprofil",
    SLOT_BEMESSUNGSWOCHE: "Bemessungswoche",
    SLOT_WP_KATALOG: "WP-Katalog",
    SLOT_SPEICHER_KATALOG: "Speicher-Katalog",
}

# Nur Eingabewerte werden gesichert, keine Rechenergebnisse und keine
# Zwischenstände. Erkennbar sind sie am Präfix ihres session_state-Schlüssels.
PARAMETER_PRAEFIXE = ("eg_", "rabatt_wp_", "rabatt_sp_", "wp_aktiv_", "sp_aktiv_")

ERLAUBTE_TYPEN = (str, int, float, bool)


class ProjektFehler(Exception):
    """Die Datei ist keine (lesbare) Projektdatei dieses Tools."""


@dataclass
class Datei:
    name: str
    inhalt: bytes

    @property
    def groesse_kb(self) -> float:
        return len(self.inhalt) / 1024


@dataclass
class Projekt:
    parameter: dict[str, Any] = field(default_factory=dict)
    dateien: dict[str, Datei] = field(default_factory=dict)
    erstellt: str = ""
    version: int = FORMAT_VERSION

    @property
    def anzahl_dateien(self) -> int:
        return len(self.dateien)


def ist_parameterschluessel(schluessel: str) -> bool:
    """Gehört ein session_state-Schlüssel zu den zu sichernden Eingaben?

    Die Schattenschlüssel aus `halte()` (Präfix `_halt_`) bleiben außen vor -
    sie tragen denselben Wert wie der eigentliche Schlüssel und würden die
    Datei nur verdoppeln.
    """
    return not schluessel.startswith("_halt_") and schluessel.startswith(PARAMETER_PRAEFIXE)


def sammle_parameter(zustand) -> dict[str, Any]:
    """Alle sicherbaren Eingabewerte aus einem session_state-artigen Mapping.

    Werte, die sich nicht als JSON darstellen lassen (etwa hochgeladene
    Dateiobjekte), werden übergangen statt den Export scheitern zu lassen.
    """
    return {
        schluessel: zustand[schluessel]
        for schluessel in sorted(zustand)
        if ist_parameterschluessel(schluessel) and isinstance(zustand[schluessel], ERLAUBTE_TYPEN)
    }


def als_json(parameter: dict[str, Any], dateien: dict[str, Datei] | None = None) -> bytes:
    """Serialisiert Parameter und Dateien zu den Bytes der Projektdatei."""
    inhalt = {
        "kennung": KENNUNG,
        "version": FORMAT_VERSION,
        "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "parameter": parameter,
        "dateien": {
            slot: {
                "name": datei.name,
                "inhalt_b64": base64.b64encode(datei.inhalt).decode("ascii"),
            }
            for slot, datei in (dateien or {}).items()
        },
    }
    return json.dumps(inhalt, indent=1, ensure_ascii=False).encode("utf-8")


def lade(rohbytes: bytes) -> Projekt:
    """Liest eine Projektdatei ein und prüft sie auf Kennung und Version."""
    try:
        inhalt = json.loads(rohbytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjektFehler(f"Datei ist kein lesbares JSON: {exc}") from exc

    if not isinstance(inhalt, dict) or inhalt.get("kennung") != KENNUNG:
        raise ProjektFehler(
            "Datei stammt nicht aus diesem Tool (Kennung fehlt oder passt nicht)."
        )

    version = inhalt.get("version", 0)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise ProjektFehler(
            f"Projektdatei hat Format-Version {version}, dieses Tool kennt höchstens "
            f"{FORMAT_VERSION}. Bitte das Tool aktualisieren."
        )

    parameter = inhalt.get("parameter") or {}
    if not isinstance(parameter, dict):
        raise ProjektFehler("Abschnitt 'parameter' ist beschädigt.")
    # Fremde oder nicht mehr existierende Schlüssel werden verworfen, statt
    # unbrauchbare Werte in den Widget-Zustand zu schreiben.
    parameter = {
        k: v for k, v in parameter.items()
        if ist_parameterschluessel(str(k)) and isinstance(v, ERLAUBTE_TYPEN)
    }

    dateien: dict[str, Datei] = {}
    for slot, eintrag in (inhalt.get("dateien") or {}).items():
        if slot not in SLOTS or not isinstance(eintrag, dict):
            continue
        try:
            dateien[slot] = Datei(
                name=str(eintrag.get("name", slot)),
                inhalt=base64.b64decode(eintrag["inhalt_b64"], validate=True),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ProjektFehler(f"Eingebettete Datei '{slot}' ist beschädigt: {exc}") from exc

    return Projekt(
        parameter=parameter, dateien=dateien,
        erstellt=str(inhalt.get("erstellt", "")), version=version,
    )


def dateiname(zeitpunkt: datetime | None = None) -> str:
    """Vorschlag für den Dateinamen des Exports."""
    return f"TWW_Projekt_{(zeitpunkt or datetime.now()).strftime('%Y-%m-%d_%H%M')}.json"
