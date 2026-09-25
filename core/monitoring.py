"""Einlesen realer Zapfprofil-Messdaten (Monitoring) aus einer Excel-Datei.

Die Datei wird im Tool hochgeladen. Erwartet wird eine Zapfprofil-Spalte mit
einer Auflösung von 1 oder 5 Minuten; bei 5 Minuten werden die Werte
gleichmäßig auf 1-Minuten-Werte verteilt.

Sind zusätzlich Spalten 'Datum' und 'Uhrzeit' vorhanden, werden die
Zeitstempel zur Plausibilitätsprüfung herangezogen (Sortierung, Duplikate,
Lücken, tatsächlicher Zeitschritt, Gesamtdauer) - die Energieberechnung
selbst basiert weiterhin nur auf den Zapfprofil-Werten.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

MINUTEN_PRO_TAG = 1440
SPALTENNAME = "Zapfprofil in Liter"
SPALTE_DATUM = "Datum"
SPALTE_UHRZEIT = "Uhrzeit"


class MonitoringDatenFehler(Exception):
    pass


@dataclass
class MonitoringErgebnis:
    zapfprofil_l_min: np.ndarray  # Länge 1440, [l/min]
    anzahl_rohwerte: int
    aufloesung: str
    warnungen: list[str] = field(default_factory=list)


def _pruefe_zeitstempel(df: pd.DataFrame, aufloesung: str) -> list[str]:
    """Plausibilitätsprüfung anhand Datum/Uhrzeit, falls vorhanden.

    Wirft MonitoringDatenFehler bei groben Fehlern (nicht sortiert, doppelte
    Zeitstempel). Unregelmäßige Zeitschritte oder eine von 24 h abweichende
    Gesamtspanne führen nur zu einer Warnung, da die Werte trotzdem
    gleichmäßig weiterverarbeitet werden.
    """
    if SPALTE_DATUM not in df.columns or SPALTE_UHRZEIT not in df.columns:
        return []

    try:
        zeitstempel = pd.to_datetime(
            df[SPALTE_DATUM].astype(str) + " " + df[SPALTE_UHRZEIT].astype(str),
            dayfirst=True, errors="coerce",
        )
    except Exception:
        return ["Zeitstempel (Datum/Uhrzeit) konnten nicht interpretiert werden, Prüfung übersprungen."]

    if zeitstempel.isna().any():
        return ["Einzelne Zeitstempel konnten nicht gelesen werden, Prüfung übersprungen."]

    if not zeitstempel.is_monotonic_increasing:
        raise MonitoringDatenFehler("Zeitstempel (Datum/Uhrzeit) sind nicht chronologisch sortiert.")

    if zeitstempel.duplicated().any():
        anzahl = int(zeitstempel.duplicated().sum())
        raise MonitoringDatenFehler(f"{anzahl} doppelte Zeitstempel gefunden.")

    warnungen = []
    erwarteter_schritt = pd.Timedelta(minutes=1 if aufloesung == "1min" else 5)
    deltas = zeitstempel.diff().dropna()
    abweichend = deltas[deltas != erwarteter_schritt]
    if not abweichend.empty:
        warnungen.append(
            f"{len(abweichend)} unregelmäßige Zeitabstände gefunden (erwartet: {erwarteter_schritt}, "
            f"größte Abweichung: {abweichend.max()}). Werte werden trotzdem als gleichmäßige "
            f"{erwarteter_schritt}-Schritte behandelt - bei Lücken verschiebt sich die zeitliche Zuordnung."
        )

    gesamtspanne = zeitstempel.iloc[-1] - zeitstempel.iloc[0] + erwarteter_schritt
    if abs(gesamtspanne - pd.Timedelta(hours=24)) > erwarteter_schritt:
        warnungen.append(f"Zeitspanne der Messdaten beträgt {gesamtspanne} statt 24 h.")

    return warnungen


def lade_zapfprofil(datei, aufloesung: str, sheet_name: str | None = None) -> MonitoringErgebnis:
    """Lädt das Zapfprofil aus einer Excel-Datei.

    Parameters
    ----------
    datei : Pfad oder datei-ähnliches Objekt (z. B. aus st.file_uploader)
    aufloesung : "1min" oder "5min"
    sheet_name : optionales Arbeitsblatt; None = erstes Blatt
    """
    try:
        df = pd.read_excel(datei, sheet_name=sheet_name if sheet_name else 0)
    except Exception as exc:
        raise MonitoringDatenFehler(f"Datei konnte nicht gelesen werden: {exc}") from exc

    df.columns = df.columns.astype(str).str.strip()
    if SPALTENNAME not in df.columns:
        raise MonitoringDatenFehler(
            f"Spalte '{SPALTENNAME}' fehlt. Gefundene Spalten: {list(df.columns)}"
        )

    werte = pd.to_numeric(df[SPALTENNAME], errors="coerce")
    if werte.isna().any():
        raise MonitoringDatenFehler(
            f"Spalte '{SPALTENNAME}' enthält nicht-numerische oder leere Werte."
        )
    werte = werte.to_numpy(dtype=float)

    if (werte < 0).any():
        raise MonitoringDatenFehler("Zapfprofil enthält negative Werte.")

    if aufloesung == "1min":
        erwartete_laenge = MINUTEN_PRO_TAG
        zapfprofil = werte
    elif aufloesung == "5min":
        erwartete_laenge = MINUTEN_PRO_TAG // 5
        zapfprofil = np.repeat(werte / 5.0, 5)
    else:
        raise MonitoringDatenFehler(f"Unbekannte Auflösung: {aufloesung}")

    if len(werte) != erwartete_laenge:
        raise MonitoringDatenFehler(
            f"Erwartet wurden {erwartete_laenge} Werte für Auflösung '{aufloesung}' "
            f"(= 24 h), gefunden wurden {len(werte)}."
        )

    warnungen = _pruefe_zeitstempel(df, aufloesung)

    return MonitoringErgebnis(
        zapfprofil_l_min=zapfprofil[:MINUTEN_PRO_TAG],
        anzahl_rohwerte=len(werte),
        aufloesung=aufloesung,
        warnungen=warnungen,
    )


class WochenMonitoringDatenFehler(Exception):
    pass


@dataclass
class WochenMonitoringErgebnis:
    zapfprofil_l_min: np.ndarray  # Länge 1440 * anzahl_tage, [l/min]
    anzahl_tage: int
    tagesblaetter: list[str]
    aufloesung: str
    warnungen: list[str] = field(default_factory=list)


def _als_bytes(datei) -> bytes:
    """Normalisiert Pfad/Datei-Objekt (z. B. st.file_uploader) auf Bytes, damit
    dieselbe Datei mehrfach (einmal je Tagesblatt) gelesen werden kann, ohne
    an eine bereits vorgerückte Leseposition zu geraten."""
    if isinstance(datei, (str, Path)):
        with open(datei, "rb") as f:
            return f.read()
    if hasattr(datei, "getvalue"):
        return datei.getvalue()
    position = datei.tell() if hasattr(datei, "tell") else None
    daten = datei.read()
    if position is not None and hasattr(datei, "seek"):
        datei.seek(position)
    return daten


def lade_wochenzapfprofil(datei, aufloesung: str) -> WochenMonitoringErgebnis:
    """Lädt eine Wochen-Monitoring-Datei: ein Tagesblatt je Wochentag, jedes
    Blatt im selben Format wie lade_zapfprofil() (Spalte 'Zapfprofil in
    Liter', optional Datum/Uhrzeit ab 00:00 je Blatt). Die Blätter werden in
    ihrer Reihenfolge in der Excel-Datei aneinandergehängt (Blattreihenfolge
    = zeitliche Reihenfolge).
    """
    rohbytes = _als_bytes(datei)
    try:
        blaetter = pd.ExcelFile(io.BytesIO(rohbytes)).sheet_names
    except Exception as exc:
        raise WochenMonitoringDatenFehler(f"Datei konnte nicht gelesen werden: {exc}") from exc

    if len(blaetter) < 2:
        raise WochenMonitoringDatenFehler(
            f"Für eine Wochenanalyse werden mehrere Tagesblätter (ein Blatt je Tag) erwartet, "
            f"gefunden wurde nur: {blaetter}."
        )

    teile = []
    warnungen = []
    for blatt in blaetter:
        try:
            tag = lade_zapfprofil(io.BytesIO(rohbytes), aufloesung, sheet_name=blatt)
        except MonitoringDatenFehler as exc:
            raise WochenMonitoringDatenFehler(f"Blatt '{blatt}': {exc}") from exc
        teile.append(tag.zapfprofil_l_min)
        warnungen.extend(f"Blatt '{blatt}': {w}" for w in tag.warnungen)

    return WochenMonitoringErgebnis(
        zapfprofil_l_min=np.concatenate(teile),
        anzahl_tage=len(blaetter),
        tagesblaetter=list(blaetter),
        aufloesung=aufloesung,
        warnungen=warnungen,
    )
