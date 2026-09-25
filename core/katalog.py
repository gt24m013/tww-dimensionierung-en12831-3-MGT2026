"""Einlesen der Investitionskosten-Kataloge (Wärmepumpen, Speicher) aus Excel.

Die Spaltenzuordnung erfolgt über Präfix-/Substring-Suche, damit kleinere
Abweichungen in der genauen Spaltenbeschriftung (Einheiten in Klammern,
Leerzeichen, "Gesamthöhe" vs. "Höhe") nichts ausmachen. Reine
Herkunfts-/Basisspalten (z. B. "... lt. Quelle", die nur der Indexierung auf
den aktuellen Preisstand dienen) werden dabei bewusst ausgeschlossen, damit
nicht versehentlich ein veralteter Ausgangswert statt des aktuellen Preises
gematcht wird.

Fehlt eine ganze Pflichtspalte, ist das ein struktureller Fehler
(KatalogFehler) - eine sinnvolle Berechnung ist dann für keine Zeile
möglich. Fehlt dagegen nur in einzelnen Zeilen ein Pflichtwert (leere
Zelle, Text statt Zahl, Wert <= 0 wo physikalisch nicht sinnvoll), wird nur
diese eine Zeile übersprungen und eine Warnung ausgegeben - der Rest des
Katalogs wird trotzdem geladen.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class KatalogFehler(Exception):
    pass


@dataclass
class WpKatalogErgebnis:
    katalog: pd.DataFrame
    warnungen: list[str] = field(default_factory=list)


@dataclass
class SpeicherKatalogErgebnis:
    katalog: pd.DataFrame
    warnungen: list[str] = field(default_factory=list)


def _lese_excel(datei, sheet_name=None) -> pd.DataFrame:
    try:
        df = pd.read_excel(datei, sheet_name=sheet_name if sheet_name else 0)
    except Exception as exc:
        raise KatalogFehler(f"Datei konnte nicht gelesen werden: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _spalte(df: pd.DataFrame, praefix: str) -> str:
    for spalte in df.columns:
        if spalte.lower().startswith(praefix.lower()):
            return spalte
    raise KatalogFehler(f"Spalte beginnend mit '{praefix}' fehlt. Gefundene Spalten: {list(df.columns)}")


def _spalte_optional(df: pd.DataFrame, praefix: str) -> str | None:
    for spalte in df.columns:
        if spalte.lower().startswith(praefix.lower()):
            return spalte
    return None


def _spalte_kurzmass(df: pd.DataFrame, buchstabe: str) -> str | None:
    """Findet eine Maß-Spalte, die mit dem gegebenen Einzelbuchstaben beginnt
    und 'mm' enthält (z. B. 'H [mm]', 'B [mm]', 'L [mm]') - ohne mit anders
    lautenden Spalten wie 'Hersteller' zu kollidieren (die kein 'mm' enthalten)."""
    for spalte in df.columns:
        s = spalte.strip().lower()
        if s.startswith(buchstabe.lower()) and "mm" in s:
            return spalte
    return None


def _spalte_masswort(df: pd.DataFrame, wort: str) -> str | None:
    """Findet eine Maß-Spalte über ein Stichwort plus 'mm' (z. B. 'wort'="höhe"
    matcht sowohl 'Höhe [mm]' als auch 'Gesamthöhe [mm]')."""
    for spalte in df.columns:
        s = spalte.strip().lower()
        if wort.lower() in s and "mm" in s:
            return spalte
    return None


_AUSSCHLUSS_MARKER = ("quelle",)  # Herkunfts-/Basisspalten (z. B. "... lt. Quelle") nie matchen


def _spalte_varianten(df: pd.DataFrame, *varianten: tuple[str, ...]) -> str | None:
    """Sucht eine Spalte über mehrere alternative, nach Präferenz geordnete
    Token-Mengen (z. B. weil die Beschriftung je nach Herstellerliste oder
    Preisstand variiert). Jede Variante ist eine Menge von Substrings, die
    (alle, case-insensitive) im Spaltennamen vorkommen müssen; die erste
    passende Variante (in Reihenfolge der Übergabe) gewinnt. Spalten, die
    einen Ausschluss-Marker enthalten (z. B. "Quelle"), werden nie
    zurückgegeben - so wird z. B. "Listenpreis 2026" der Vorzug vor
    "Listenpreis netto lt. Quelle" gegeben, auch wenn diese ebenfalls
    "listenpreis" enthält."""
    kandidaten = [s for s in df.columns if not any(a in s.lower() for a in _AUSSCHLUSS_MARKER)]
    for tokens in varianten:
        for spalte in kandidaten:
            s = spalte.lower()
            if all(t.lower() in s for t in tokens):
                return spalte
    return None


def normalisiere_material(wert):
    """Normalisiert einen Material-Bezeichner für tolerante Vergleiche
    (Groß-/Kleinschreibung, Kommas, doppelte Leerzeichen - z. B. "Stahl
    emailliert" vs. "Stahl, emailliert" werden als gleich behandelt)."""
    if isinstance(wert, pd.Series):
        return wert.astype(str).str.lower().str.replace(",", "", regex=False).str.split().str.join(" ")
    return " ".join(str(wert).lower().replace(",", "").split())


def _numerisch_optional(df: pd.DataFrame, praefix: str | None, spalte: str | None = None) -> pd.Series:
    """Liefert eine numerische Spalte, die fehlen oder einzelne leere Zeilen
    enthalten darf (z. B. Durchmesser bei eckigen, Breite/Länge bei runden
    Speichern; optionale Kostenbestandteile wie Transportkosten)."""
    if spalte is None:
        spalte = _spalte_optional(df, praefix) if praefix else None
    if spalte is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return pd.to_numeric(df[spalte], errors="coerce")


def _filtere_unvollstaendige_zeilen(
    df: pd.DataFrame, pflichtfelder: dict[str, str], produkt_spalte: str = "produkt"
) -> tuple[pd.DataFrame, list[str]]:
    """Entfernt Zeilen, denen mindestens eines der Pflichtfelder fehlt (NaN),
    und protokolliert je betroffener Zeile eine Warnung statt die gesamte
    Berechnung zu stoppen.

    `pflichtfelder`: {Spaltenname im Ergebnis-DataFrame: Anzeigename für die
    Warnmeldung}.
    """
    fehlend_je_zeile: dict[int, list[str]] = {}
    for feld, anzeigename in pflichtfelder.items():
        for idx in df.index[df[feld].isna()]:
            fehlend_je_zeile.setdefault(idx, []).append(anzeigename)

    if not fehlend_je_zeile:
        return df.reset_index(drop=True), []

    warnungen = []
    for idx, felder in fehlend_je_zeile.items():
        produkt = df.loc[idx, produkt_spalte] if produkt_spalte in df.columns else None
        produkt = produkt if pd.notna(produkt) and str(produkt).strip() not in ("", "nan") else f"Zeile {idx + 2}"
        warnungen.append(
            f"'{produkt}': fehlende/ungültige Pflichtangabe(n) {felder} – Zeile wird übersprungen."
        )
    gueltige_zeilen = df.index.difference(fehlend_je_zeile.keys())
    return df.loc[gueltige_zeilen].reset_index(drop=True), warnungen


def lade_wp_katalog(datei, sheet_name=None, betriebspunkt: str = "W55") -> WpKatalogErgebnis:
    """Lädt den Wärmepumpen-Katalog (Herstellerpreisliste mit Leistung/COP an
    zwei Normbetriebspunkten B0/W35 und B0/W55, Abmessungen H/B/L [mm],
    Listenpreis und Inbetriebnahmekosten).

    Pflichtspalten je Modell: Hersteller, Produkt, Leistung [kW] und COP
    jeweils bei B0/W35 und B0/W55, Höhe/Breite/Länge [mm], Listenpreis,
    Inbetriebnahmekosten. Optional: Transportkosten [€] (Default 0, falls
    nicht vorhanden), max. Vorlauftemperatur (nur informativ). Reine
    Herkunfts-/Basisspalten (z. B. "Listenpreis netto lt. Quelle", die nur
    der Indexierung auf den aktuellen Preisstand dienen) werden ignoriert -
    bei mehreren möglichen Preisspalten wird die mit "2026" im Namen
    bevorzugt (aktueller Preisstand).

    `betriebspunkt`: "W35" oder "W55" - legt fest, welcher der beiden
    Punkte als 'leistung_kw'/'cop' für die Auslegungsrechnung (core/
    investition.py, core/kostenfunktion.py) herangezogen wird. Beide
    Betriebspunkte bleiben zusätzlich unter leistung_kw_w35/_w55 bzw.
    cop_w35/_w55 erhalten.

    Investkosten (ungerabattet) = Listenpreis + Inbetriebnahme + Transport.
    Die Einzelbestandteile bleiben erhalten, damit Rabatte gezielt nur auf
    den Listenpreis angewendet werden können (siehe core/rabatt.py).

    Zeilen mit fehlenden/ungültigen Pflichtangaben werden übersprungen und
    im zurückgegebenen `.warnungen` protokolliert statt die Berechnung zu
    stoppen; fehlt dagegen eine ganze Pflichtspalte, wird ein KatalogFehler
    ausgelöst.
    """
    if betriebspunkt not in ("W35", "W55"):
        raise KatalogFehler(f"Unbekannter Betriebspunkt '{betriebspunkt}', erwartet 'W35' oder 'W55'.")

    df = _lese_excel(datei, sheet_name)

    leistung_w35_spalte = _spalte_varianten(df, ("35", "kw"), ("35", "leistung"))
    leistung_w55_spalte = _spalte_varianten(df, ("55", "kw"), ("55", "leistung"))
    cop_w35_spalte = _spalte_varianten(df, ("35", "cop"))
    cop_w55_spalte = _spalte_varianten(df, ("55", "cop"))
    listenpreis_spalte = _spalte_varianten(df, ("listenpreis", "2026"), ("netto",), ("listenpreis",))
    ibn_spalte = _spalte_varianten(df, ("inbetriebnahme", "2026"), ("ibn",), ("inbetriebnahme",))
    hoehe_spalte = _spalte_kurzmass(df, "h")
    breite_spalte = _spalte_kurzmass(df, "b")
    laenge_spalte = _spalte_kurzmass(df, "l")

    fehlend = [
        bezeichnung for bezeichnung, spalte in [
            ("Leistung B0/W35", leistung_w35_spalte), ("COP B0/W35", cop_w35_spalte),
            ("Leistung B0/W55", leistung_w55_spalte), ("COP B0/W55", cop_w55_spalte),
            ("Listenpreis", listenpreis_spalte), ("Inbetriebnahmekosten", ibn_spalte),
            ("Höhe [mm]", hoehe_spalte), ("Breite [mm]", breite_spalte), ("Länge [mm]", laenge_spalte),
        ] if spalte is None
    ]
    if fehlend:
        raise KatalogFehler(
            f"Folgende Pflichtspalten fehlen im WP-Katalog: {fehlend}. Gefundene Spalten: {list(df.columns)}"
        )

    ergebnis = pd.DataFrame({
        "hersteller": df[_spalte(df, "Hersteller")].astype(str).str.strip(),
        "produkt": df[_spalte(df, "Produkt")].astype(str).str.strip(),
        "leistung_kw_w35": pd.to_numeric(df[leistung_w35_spalte], errors="coerce"),
        "cop_w35": pd.to_numeric(df[cop_w35_spalte], errors="coerce"),
        "leistung_kw_w55": pd.to_numeric(df[leistung_w55_spalte], errors="coerce"),
        "cop_w55": pd.to_numeric(df[cop_w55_spalte], errors="coerce"),
        "listenpreis": pd.to_numeric(df[listenpreis_spalte], errors="coerce"),
        "ibn_kosten": pd.to_numeric(df[ibn_spalte], errors="coerce"),
        "hoehe_mm": pd.to_numeric(df[hoehe_spalte], errors="coerce"),
        "breite_mm": pd.to_numeric(df[breite_spalte], errors="coerce"),
        "laenge_mm": pd.to_numeric(df[laenge_spalte], errors="coerce"),
    })

    # Werte <= 0 dort, wo physikalisch sinnlos, wie fehlende Werte behandeln
    for spalte in ("leistung_kw_w35", "leistung_kw_w55", "hoehe_mm", "breite_mm", "laenge_mm"):
        ergebnis.loc[ergebnis[spalte] <= 0, spalte] = float("nan")

    vl_max_spalte = _spalte_varianten(df, ("vl", "max"), ("vorlauf", "max"))
    ergebnis["vl_max_c"] = _numerisch_optional(df, None, vl_max_spalte)

    transport_spalte = _spalte_optional(df, "Transportkosten")
    ergebnis["transport_kosten"] = _numerisch_optional(df, None, transport_spalte).fillna(0.0)

    ergebnis, warnungen = _filtere_unvollstaendige_zeilen(ergebnis, {
        "leistung_kw_w35": "Leistung B0/W35", "cop_w35": "COP B0/W35",
        "leistung_kw_w55": "Leistung B0/W55", "cop_w55": "COP B0/W55",
        "listenpreis": "Listenpreis", "ibn_kosten": "Inbetriebnahmekosten",
        "hoehe_mm": "Höhe", "breite_mm": "Breite", "laenge_mm": "Länge",
    })
    if ergebnis.empty:
        raise KatalogFehler("WP-Katalog enthält nach Prüfung der Pflichtangaben keine verwendbare Zeile mehr.")

    ergebnis["platzbedarf_m3"] = (
        ergebnis["hoehe_mm"] / 1000 * ergebnis["breite_mm"] / 1000 * ergebnis["laenge_mm"] / 1000
    )
    ergebnis["investkosten"] = ergebnis["listenpreis"] + ergebnis["ibn_kosten"] + ergebnis["transport_kosten"]

    if betriebspunkt == "W55":
        ergebnis["leistung_kw"] = ergebnis["leistung_kw_w55"]
        ergebnis["cop"] = ergebnis["cop_w55"]
    else:
        ergebnis["leistung_kw"] = ergebnis["leistung_kw_w35"]
        ergebnis["cop"] = ergebnis["cop_w35"]

    return WpKatalogErgebnis(
        katalog=ergebnis.sort_values("leistung_kw").reset_index(drop=True),
        warnungen=warnungen,
    )


def lade_speicher_katalog(datei, sheet_name=None) -> SpeicherKatalogErgebnis:
    """Lädt den Speicher-Katalog.

    Pflichtspalten je Modell: Hersteller, Produktname, Nennvolumen [l],
    Höhe [mm], Nettokosten - sowie für den Grundriss entweder Durchmesser
    [mm] (runde Speicher) oder Länge + Breite [mm] (eckige Speicher). Welche
    der beiden Maßangaben vorliegt, wird je Zeile unabhängig ausgewertet, da
    nicht jeder Speicher rund ist; es muss lediglich mindestens eine
    vollständige Angabe vorhanden sein. Daraus wird 'grundflaeche_m2'
    abgeleitet (für eine spätere Optimierung nach Platzbedarf). Material ist
    optional (nur für die Rabattgruppen-/Kostenfunktions-Filterung nach
    Werkstoff nützlich); fehlt die Spalte oder eine einzelne Zeile, wird
    "unbekannt" eingesetzt.

    Warmhalteverlust [W] ist optional (Spalte und einzelne Zeilen): er wird
    für Investkosten-/Volumenauswertungen (Kostenregressionen, Modus D/E/F-
    Optimierung nach Kosten) nicht gebraucht, nur für den daraus
    abgeleiteten Bereitschaftsverlust q_sb,sto. Fehlt er, bleibt die Zeile
    im Katalog (anders als bei den übrigen Pflichtfeldern), erhält aber
    q_sb,sto = NaN und wird dafür in .warnungen vermerkt - Modelle ohne
    Warmhalteverlust können damit nicht normkonform simuliert werden
    (core/investition.py: SOC_min >= NaN ist immer False, die Kombination
    gilt also als unzulässig statt einen Fehler auszulösen).

    Der Warmhalteverlust (EU-812/2013-Wert "S" in Watt) wird, wo vorhanden,
    nach Gl. 7 der ÖNORM EN 12831-3 in den Bereitschaftsverlust q_sb,sto
    [kWh/24h] umgerechnet (q_sb,sto = S * 0,024), der anstelle des sonst
    global manuell eingegebenen Werts je Speichermodell in die Norm-
    Simulation eingeht (siehe core/investition.py).

    Die Spalte 'nettokosten' bleibt zusätzlich zu 'investkosten' erhalten,
    damit Rabatte gezielt darauf angewendet werden können.

    Zeilen mit fehlenden/ungültigen Pflichtangaben werden übersprungen und
    im zurückgegebenen `.warnungen` protokolliert statt die Berechnung zu
    stoppen; fehlt dagegen eine ganze Pflichtspalte, wird ein KatalogFehler
    ausgelöst.
    """
    df = _lese_excel(datei, sheet_name)

    volumen_spalte = _spalte_optional(df, "Nennvolumen")
    hoehe_spalte = _spalte_masswort(df, "höhe")
    nettokosten_spalte = _spalte_varianten(df, ("nettokosten", "2026"), ("nettokosten",))
    warmhalteverlust_spalte = _spalte_varianten(df, ("warmhalteverlust",), ("bereitschaftsverlust",))

    fehlend = [
        bezeichnung for bezeichnung, spalte in [
            ("Nennvolumen [l]", volumen_spalte), ("Höhe [mm]", hoehe_spalte),
            ("Nettokosten", nettokosten_spalte),
        ] if spalte is None
    ]
    if fehlend:
        raise KatalogFehler(
            f"Folgende Pflichtspalten fehlen im Speicher-Katalog: {fehlend}. Gefundene Spalten: {list(df.columns)}"
        )

    ergebnis = pd.DataFrame({
        "hersteller": df[_spalte(df, "Hersteller")].astype(str).str.strip(),
        "produkt": df[_spalte(df, "Produktname")].astype(str).str.strip(),
        "volumen_l": pd.to_numeric(df[volumen_spalte], errors="coerce"),
        "hoehe_mm": pd.to_numeric(df[hoehe_spalte], errors="coerce"),
        "nettokosten": pd.to_numeric(df[nettokosten_spalte], errors="coerce"),
        "warmhalteverlust_w": _numerisch_optional(df, None, warmhalteverlust_spalte),
    })

    material_spalte = _spalte_optional(df, "Material")
    if material_spalte is not None:
        material = df[material_spalte].astype(str).str.strip()
        material = material.mask(material.isin(["", "nan", "None"]), "unbekannt")
    else:
        material = pd.Series(["unbekannt"] * len(df), index=df.index)
    ergebnis["material"] = material

    for spalte in ("volumen_l", "hoehe_mm"):
        ergebnis.loc[ergebnis[spalte] <= 0, spalte] = float("nan")
    ergebnis.loc[ergebnis["warmhalteverlust_w"] < 0, "warmhalteverlust_w"] = float("nan")

    ergebnis["breite_mm"] = _numerisch_optional(df, None, _spalte_masswort(df, "breite"))
    ergebnis["laenge_mm"] = _numerisch_optional(df, None, _spalte_masswort(df, "länge"))
    ergebnis["durchmesser_mm"] = _numerisch_optional(df, None, _spalte_masswort(df, "durchmesser"))

    hat_durchmesser = ergebnis["durchmesser_mm"].notna() & (ergebnis["durchmesser_mm"] > 0)
    hat_rechteckig = (
        ergebnis["breite_mm"].notna() & (ergebnis["breite_mm"] > 0)
        & ergebnis["laenge_mm"].notna() & (ergebnis["laenge_mm"] > 0)
    )
    # Platzhalterspalte, damit die fehlende Grundriss-Angabe über denselben
    # Mechanismus wie die übrigen Pflichtfelder protokolliert wird
    ergebnis["_grundriss_vorhanden"] = np.where(hat_durchmesser | hat_rechteckig, 1.0, float("nan"))

    ergebnis, warnungen = _filtere_unvollstaendige_zeilen(ergebnis, {
        "volumen_l": "Nennvolumen", "hoehe_mm": "Höhe", "nettokosten": "Nettokosten",
        "_grundriss_vorhanden": "Grundriss (Durchmesser oder Länge+Breite)",
    })
    if ergebnis.empty:
        raise KatalogFehler("Speicher-Katalog enthält nach Prüfung der Pflichtangaben keine verwendbare Zeile mehr.")

    ergebnis = ergebnis.drop(columns=["_grundriss_vorhanden"])
    hat_durchmesser = ergebnis["durchmesser_mm"].notna() & (ergebnis["durchmesser_mm"] > 0)
    # rund geht vor eckig, falls (unüblich) beide Maßangaben vorhanden sind
    ergebnis["grundflaeche_m2"] = np.where(
        hat_durchmesser,
        np.pi * (ergebnis["durchmesser_mm"] / 1000 / 2) ** 2,
        (ergebnis["breite_mm"] / 1000) * (ergebnis["laenge_mm"] / 1000),
    )

    ergebnis["investkosten"] = ergebnis["nettokosten"]
    ergebnis["q_sb_sto"] = ergebnis["warmhalteverlust_w"] * 0.024  # Gl. 7

    for idx in ergebnis.index[ergebnis["warmhalteverlust_w"].isna()]:
        warnungen.append(
            f"'{ergebnis.loc[idx, 'produkt']}': kein Warmhalteverlust angegeben - Modell wird bei "
            "Investkosten-/Volumenauswertungen berücksichtigt, ist aber ohne Bereitschaftsverlust "
            "(q_sb,sto) für die normbasierte Investitionsoptimierung (Modus D/F) nicht nutzbar."
        )

    return SpeicherKatalogErgebnis(
        katalog=ergebnis.sort_values("volumen_l").reset_index(drop=True),
        warnungen=warnungen,
    )
