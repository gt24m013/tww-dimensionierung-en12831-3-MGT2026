"""TWW-Dimensionierungstool nach ÖNORM EN 12831-3.

Modus A: reine Normauslegung (Norm-Lastprofil)
Modus B: reales Monitoring (Zapfprofil aus Excel-Messdaten)
Modus C: Vergleich Norm (Soll) vs. Monitoring (Ist) für dieselbe Anlage.
         Verglichen werden die beiden in Modus A und B gerechneten und
         hinterlegten Fälle - jeder mit seinen eigenen Eingaben, damit der
         Norm-Fall mit geschätzten Verlusten (Gl. 6/9) gegen den
         Monitoring-Fall mit gemessenem Summenverlust antreten kann.
Modus D: Investitionsoptimierung (kostenoptimale WP-/Speicher-Kombination
         aus realen Katalogprodukten)
Modus E: Optimierung über Kostenfunktionen (kontinuierliches Raster mit aus den
         Katalogen abgeleiteten degressiven Kostenfunktionen statt einer
         abstrakten Gewichtung)
Modus F: Techno-ökonomische Optimierung über reale Katalogprodukte, immer
         gegen die Monitoring-Messdaten geprüft (Norm-Kriterium SOC_min >=
         Q_sto,min) - drei Zielvarianten (technisch: min. Schalthäufigkeit,
         ökonomisch: min. Investkosten, techno-ökonomisch: gewichteter
         Kompromiss auf der Pareto-Front beider Zielgrößen)

Start lokal mit:  .venv/Scripts/streamlit run app.py
"""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from core.modell import Eingabedaten
from core.speicherverbund import (
    Speicherverbund, SCHALTUNGEN, FUEHLER_POSITIONEN, SERIE, FUEHLER_ZAPFSEITIG,
)
from core.norm_daten import (
    LASTPROFILE_STUNDENANTEILE, GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH,
    X_MAX_SPEZ_VOLUMEN, Y_SPEZ_VOLUMEN,
    HINWEIS_PLATZHALTER, IST_NORMKONFORM, QUELLE, STANDARD_PROFIL, ergaenze_lastprofil,
)
from core.bedarf import aequivalente_personen, tagesvolumen_liter, zapfprofil_minutenwerte
from core.lastprofil import LastprofilFehler, lies_csv as lies_lastprofil_csv
from core.monitoring import (
    lade_zapfprofil, MonitoringDatenFehler, lade_wochenzapfprofil, WochenMonitoringDatenFehler,
)
from core.versorgung import berechne_versorgungskennlinie, tagesauswertung
from core.vergleich import vergleiche
from core.protokoll import (
    parametersatz, parametersatz_text, vergleiche_parametersaetze,
    vergleichstabelle_text, unterschiede, sichtbare_zeilen,
    ABSCHNITT_ANLAGE, ABSCHNITT_TEMPERATUREN,
)
from core.katalog import lade_wp_katalog, lade_speicher_katalog, KatalogFehler
from core.rabatt import wende_wp_rabatt_an, wende_speicher_rabatt_an
from core.montage import wende_wp_montage_an, wende_speicher_montage_an
from core.investition import (
    optimiere, guenstigste_zulaessige,
    materialschonendste_zulaessige, pareto_front, kompromiss_zulaessige,
)
from core.kostenfunktion import (
    wp_kostenfunktion, wp_kostenfunktion_listenpreis, wp_kostenfunktion_inkl_ibn,
    speicher_kostenfunktion, KostenfunktionFehler, bestimmtheitsmass,
)
from core.systemoptimierung import (
    optimiere_raster, guenstigster_punkt, kleinste_leistung, kleinstes_volumen, bewerte_anlagen,
)
from core.kostenregression import (
    wp_regression_je_hersteller, wp_regression_gesamt,
    speicher_regression_je_hersteller, speicher_regression_je_material,
    speicher_verlust_je_hersteller, speicher_verlust_je_material,
)
from core.projekt import (
    Datei as projekt_datei, ProjektFehler, als_json as projekt_als_json,
    lade as projekt_laden, sammle_parameter, dateiname as projekt_dateiname,
    SLOTS, SLOT_TITEL, SLOT_BEMESSUNGSTAG, SLOT_BEMESSUNGSWOCHE,
    SLOT_WP_KATALOG, SLOT_SPEICHER_KATALOG,
)
from core.visualisierung import (
    plot_ergebnis, plot_vergleich, plot_investitionsoptimierung, plot_systemoptimierung, plot_pareto_front,
    plot_anlagenkosten_vergleich,
    farbzuordnung, einzelfigur_regression, einzelfigur_kombiniert, einzelfigur_verlust_kombiniert,
    einzelfiguren_ergebnis, einzelfiguren_vergleich, funktions_label, PANEL_ERGEBNIS, PANEL_VERGLEICH,
    MINUTEN_PRO_TAG, FARBE_ZAPFPROFIL_NORM, FARBE_ZAPFPROFIL_MONITORING,
)

st.set_page_config(page_title="TWW-Normauslegung (ÖNORM EN 12831-3)", layout="wide")
st.title("🚰 TWW-Dimensionierungstool — ÖNORM EN 12831-3")

if not IST_NORMKONFORM:
    st.warning(f"**Keine Normwerte hinterlegt.** {HINWEIS_PLATZHALTER}", icon="⚠️")
else:
    st.caption(f"Normwerte: {QUELLE}")

# Herkunft der Anhang-B-Werte in jedem Ergebnisprotokoll mitführen, damit ein
# exportiertes Protokoll für sich allein erkennen lässt, worauf es beruht.
NORMWERTE_PROTOKOLLZEILE = f"Normwerte: {QUELLE}" + (
    "" if IST_NORMKONFORM
    else "\nACHTUNG: Platzhalterwerte — die Ergebnisse sind NICHT normkonform."
)


# --------------------------------------------------------------------------
# Eingaben über Moduswechsel hinweg halten
# --------------------------------------------------------------------------
def halte(widget, key: str, standard, **kwargs):
    """Rendert ein Widget, dessen Wert einen Moduswechsel überdauert.

    Streamlit verwirft den session_state-Eintrag eines Widgets, sobald es in
    einem Rerun nicht mehr gezeichnet wird. Beim Wechsel von Modus A nach B
    würden so sämtliche Norm-Eingaben verloren gehen (und umgekehrt). Jeder
    Wert wird deshalb zusätzlich unter einem Schattenschlüssel gehalten und
    vor dem Zeichnen zurückgespielt, sodass der Anwender in Modus B genau auf
    den Eingaben aus Modus A aufsetzt und dort nur noch die Abweichungen
    (z. B. den gemessenen Verlustwert) ändern muss.
    """
    schatten = f"_halt_{key}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(schatten, standard)
    wert = widget(key=key, **kwargs)
    st.session_state[schatten] = wert
    return wert


# --------------------------------------------------------------------------
# Datei-Depot: hochgeladene Dateien im Original behalten
#
# Streamlit verwirft den Inhalt eines file_uploaders, sobald das Widget in
# einem Rerun nicht mehr gezeichnet wird (z. B. beim Moduswechsel). Die
# Originalbytes werden deshalb je Slot gemerkt - damit überstehen die Dateien
# den Moduswechsel und können zugleich in die Projektdatei geschrieben werden.
# --------------------------------------------------------------------------
DATEI_DEPOT = "_datei_depot"


def merke_datei(slot: str, hochgeladen) -> None:
    depot = st.session_state.setdefault(DATEI_DEPOT, {})
    depot[slot] = projekt_datei(name=hochgeladen.name, inhalt=hochgeladen.getvalue())


def hole_datei(slot: str) -> "projekt_datei | None":
    return st.session_state.get(DATEI_DEPOT, {}).get(slot)


def datei_quelle(slot: str, hochgeladen):
    """Einzulesende Datei eines Slots: neuer Upload schlägt Depot.

    Gibt (BytesIO, Dateiname) zurück oder (None, None), wenn für diesen Slot
    weder hochgeladen noch gemerkt wurde.
    """
    if hochgeladen is not None:
        merke_datei(slot, hochgeladen)
    datei = hole_datei(slot)
    if datei is None:
        return None, None
    return io.BytesIO(datei.inhalt), datei.name


# --------------------------------------------------------------------------
# Projektdatei einlesen, BEVOR irgendein Widget gezeichnet wird
#
# Streamlit lässt den session_state eines Widgets nur ändern, solange das
# Widget im laufenden Durchlauf noch nicht erzeugt wurde. Der Import wird in
# der Sidebar deshalb nur vorgemerkt und hier - vor allen Eingabefeldern - in
# den Zustand geschrieben.
# --------------------------------------------------------------------------
IMPORT_VORGEMERKT = "_import_vorgemerkt"
IMPORT_MELDUNG = "_import_meldung"


def wende_projekt_an() -> None:
    vorgemerkt = st.session_state.pop(IMPORT_VORGEMERKT, None)
    if vorgemerkt is None:
        return
    for schluessel, wert in vorgemerkt.parameter.items():
        st.session_state[schluessel] = wert
        # Schattenschlüssel mitziehen, damit halte() den Wert auch nach einem
        # Moduswechsel nicht wieder auf den Standard zurückdreht.
        st.session_state[f"_halt_{schluessel}"] = wert
    if vorgemerkt.dateien:
        depot = st.session_state.setdefault(DATEI_DEPOT, {})
        depot.update(vorgemerkt.dateien)
    # Gerechnete Fälle und geparste Messdaten des vorherigen Projekts passen
    # nicht mehr zu den neuen Eingaben.
    for veraltet in (FALL_NORM, FALL_NORM_SOLL, FALL_MONITORING, MONITORING_DATEN,
                     WOCHEN_DATEN, FALL_KOSTENOPTIMUM):
        st.session_state.pop(veraltet, None)
    st.session_state[IMPORT_MELDUNG] = (
        f"✅ Projekt geladen: {len(vorgemerkt.parameter)} Parameter"
        + (f" und {vorgemerkt.anzahl_dateien} Datei(en)" if vorgemerkt.dateien else "")
        + (f" (gesichert am {vorgemerkt.erstellt})" if vorgemerkt.erstellt else "")
    )


# --------------------------------------------------------------------------
# Gerechnete Fälle für den Vergleich in Modus C hinterlegen
# --------------------------------------------------------------------------
FALL_NORM = "fall_norm"
# Selbst dimensionierter Soll-Zustand aus Modus A2: dieselben Eingangsgrößen
# wie der Norm-Fall, nur V_sto und Φ_N vom Anwender iterativ angepasst.
FALL_NORM_SOLL = "fall_norm_soll"
FALL_MONITORING = "fall_monitoring"
MONITORING_DATEN = "_monitoring_daten"
# Bemessungswoche für Modus F - getrennt gemerkt, weil dort Bemessungstag und
# Bemessungswoche gleichzeitig vorliegen müssen.
WOCHEN_DATEN = "_wochen_daten"
# Rasteroptimum aus Modus E - hinterlegt, damit Modus F seine drei Varianten
# gegen dasselbe Kostenoptimum stellen kann, ohne das Raster erneut zu rechnen.
FALL_KOSTENOPTIMUM = "fall_kostenoptimum"


@dataclass
class GespeicherterFall:
    """Ein vollständig gerechneter Fall samt der Eingaben, mit denen er
    gerechnet wurde - Grundlage des Vergleichs in Modus C."""

    modus: str
    daten: Eingabedaten
    zapfprofil: np.ndarray
    ergebnis: object                      # Versorgungsergebnis
    quelle_label: str
    parameter: dict[str, dict[str, str]]  # Echo aller Eingaben dieses Falls
    volumen_l: float
    zeitstempel: str
    anzahl_tage: int = 1
    warnungen: list[str] = field(default_factory=list)

    @property
    def kurzinfo(self) -> str:
        zeitraum = f"{self.anzahl_tage} Tage" if self.anzahl_tage > 1 else "1 Tag"
        return (
            f"{self.volumen_l:,.0f} l über {zeitraum} · "
            f"{len(self.ergebnis.zyklen)} Zyklen · gerechnet {self.zeitstempel}"
        )


@dataclass
class GespeichertesKostenoptimum:
    """Das Rasteroptimum aus Modus E, so wie Modus F es für seinen
    Kostenvergleich braucht.

    Gespeichert werden nur die Auslegungsgrößen und der Kontext, unter dem sie
    entstanden sind - nicht das ganze Raster. Die Kosten werden in Modus F
    ohnehin mit den dort abgeleiteten Kostenfunktionen neu bewertet, damit alle
    Balken auf derselben Basis stehen; `kosten` dient nur dem Abgleich.
    """

    v_sto: float
    phi_n: float
    kosten: float
    lastprofil_basis: str
    material: str
    raster_schritte: int
    zeitstempel: str


def hinterlege_fall(schluessel: str, fall: GespeicherterFall) -> None:
    st.session_state[schluessel] = fall


def geholter_fall(schluessel: str) -> GespeicherterFall | None:
    return st.session_state.get(schluessel)


# Muss vor dem ersten Eingabe-Widget laufen (siehe wende_projekt_an).
wende_projekt_an()
if st.session_state.get(IMPORT_MELDUNG):
    st.success(st.session_state.pop(IMPORT_MELDUNG))

modus = halte(
    st.radio, "eg_modus", "A: Normauslegung (Norm-Lastprofil)",
    label="Modus",
    options=[
        "A: Normauslegung (Norm-Lastprofil)",
        "A2: Eigene Dimensionierung (Norm-Soll-Zustand)",
        "B: Reales Monitoring (Messdaten)",
        "C: Vergleich (Norm vs. Monitoring)",
        "D: Investitionsoptimierung (WP + Speicher)",
        "E: Optimierung über Kostenfunktionen",
        "F: Techno-ökonomische Optimierung (Monitoring)",
    ],
    horizontal=True,
)
# "A2" beginnt ebenfalls mit "A": überall den vollständigen Präfix prüfen,
# sonst liefe Modus A2 in den Zweig von Modus A.
ist_norm_zustand = modus.startswith("A:")
ist_norm_soll = modus.startswith("A2")
ist_vergleich = modus.startswith("C")
ist_investition = modus.startswith("D")
ist_kostenfunktion = modus.startswith("E")
ist_technoeko = modus.startswith("F")
braucht_kataloge = ist_investition or ist_kostenfunktion or ist_technoeko

investitions_basis = "Norm-Lastprofil"
if ist_technoeko:
    investitions_basis = "Monitoring-Messdaten"
    st.caption(
        "Modus F prüft alle Kombinationen immer gegen die Monitoring-Messdaten (kein "
        "Norm-Lastprofil-Umschalter, da alle drei Varianten explizit 'mit den Monitoringdaten "
        "funktionierend' sein sollen) — und zwar gegen **zwei** Profile: den Bemessungstag "
        "und die Bemessungswoche."
    )
elif braucht_kataloge:
    investitions_basis = halte(
        st.radio, "eg_investitions_basis", "Norm-Lastprofil",
        label="Lastprofil-Basis für die Optimierung",
        options=["Norm-Lastprofil", "Monitoring-Messdaten"],
        horizontal=True,
    )

# Modus C rechnet nicht selbst, sondern vergleicht die in Modus A und B
# hinterlegten Fälle - jeder mit seinem eigenen Parametersatz. Deshalb blendet
# er die Eingabebereiche aus; live eingegebene Werte hätten dort keine Wirkung
# und würden nur verschleiern, mit welchen Eingaben tatsächlich gerechnet wurde.
braucht_norm_eingabe = ist_norm_zustand or ist_norm_soll or (
    braucht_kataloge and investitions_basis == "Norm-Lastprofil"
)
braucht_monitoring_eingabe = modus.startswith("B") or (
    braucht_kataloge and investitions_basis == "Monitoring-Messdaten"
)
braucht_anlagen_eingabe = not ist_vergleich

# Defaults, falls der jeweilige Eingabebereich nicht angezeigt wird
methode, n_personen, v_pro_person, n_einheiten, v_pro_einheit = "A", 268, 40.0, 1, 70.0
methode_label = "Verfahren A: nach Personenzahl (Gl. 20)"
wohnungstyp, wohnflaeche, anzahl_wohneinheiten = GEBAEUDETYP_WOHNUNG, 70.0, 1
x_max_spez_volumen, y_spez_volumen = X_MAX_SPEZ_VOLUMEN, Y_SPEZ_VOLUMEN
profil = next(iter(LASTPROFILE_STUNDENANTEILE))
hochgeladene_datei, aufloesung = None, "5min"
aufloesung_label, analysezeitraum = "5 Minuten", "Ein Tag (24 h)"
wochenanalyse = False
wochen_datei = None          # zweite Datei in Modus F: Bemessungswoche
speicher_typ, phi_n, f_l, t_lag_hg = "Speicherladesystem", 70.5, 1.0, 4.0
# Speichergrößen werden je Einzelspeicher eingegeben und in core/speicherverbund.py
# auf die Normgrößen V_sto / h_sto / h_sensor / q_sb,sto umgerechnet (anzahl = 1:
# identisch zur bisherigen Eingabe).
anzahl_speicher, speicher_schaltung, fuehler_position = 1, SERIE, FUEHLER_ZAPFSEITIG
v_je_speicher, h_je_speicher, h_sensor_je_speicher, q_sb_je_speicher = 3000.0, 2.0, 0.6, 3.48
q_dis_spec, l_dis = 7.0, 150.0
je_speicher = ""
verlust_aus_messung, verlust_gesamt_je_minute = False, None
theta_draw, theta_c, theta_sto_max, theta_a = 60.0, 10.0, 63.0, 15.0

with st.sidebar:
    with st.expander("💾 Projektdatei — sichern & laden", expanded=False):
        st.caption(
            "Sichert **alle** Eingaben der Sidebar samt der hochgeladenen Excel-Dateien in einer "
            "einzigen JSON-Datei. Beim nächsten Start diese Datei hier laden — das Tool ist dann "
            "sofort rechenbereit, ohne dass etwas neu eingegeben oder hochgeladen werden muss."
        )

        geladene_dateien = st.session_state.get(DATEI_DEPOT, {})
        if geladene_dateien:
            st.caption("Enthaltene Dateien: " + " · ".join(
                f"**{SLOT_TITEL[s]}**: {geladene_dateien[s].name} ({geladene_dateien[s].groesse_kb:.0f} KB)"
                for s in SLOTS if s in geladene_dateien
            ))
        else:
            st.caption("Noch keine Datei hochgeladen — gesichert werden dann nur die Parameter.")

        st.download_button(
            "⬇️ Projektdatei speichern",
            data=projekt_als_json(sammle_parameter(st.session_state), geladene_dateien),
            file_name=projekt_dateiname(),
            mime="application/json",
            use_container_width=True,
        )

        projektdatei = st.file_uploader(
            "Projektdatei laden", type=["json"], key="projekt_upload",
            help="Überschreibt sämtliche Eingaben und hochgeladenen Dateien mit dem Stand aus "
                 "der Datei. Bereits gerechnete Fälle (Modus A/B) werden dabei verworfen, weil "
                 "sie nicht mehr zu den neuen Eingaben passen.",
        )
        if projektdatei is not None:
            rohbytes = projektdatei.getvalue()
            # Kennzeichen der Datei merken, damit derselbe Upload nicht bei
            # jedem Rerun erneut angewendet wird und laufende Änderungen
            # überschreibt.
            kennzeichen = f"{projektdatei.name}:{len(rohbytes)}"
            if st.session_state.get("_import_zuletzt") != kennzeichen:
                try:
                    st.session_state[IMPORT_VORGEMERKT] = projekt_laden(rohbytes)
                except ProjektFehler as e:
                    st.error(f"Projektdatei konnte nicht gelesen werden: {e}")
                else:
                    st.session_state["_import_zuletzt"] = kennzeichen
                    st.rerun()

    if braucht_monitoring_eingabe:
        st.header("0. Monitoring-Daten")
        if ist_technoeko:
            # Modus F prüft jede Kombination gegen BEIDE Profile: der
            # Bemessungstag deckt die Spitze ab, die Bemessungswoche den
            # Dauerbetrieb. Der Analysezeitraum ist deshalb nicht wählbar -
            # die erste Datei ist immer der Tag, die zweite immer die Woche.
            analysezeitraum = "Ein Tag (24 h)"
            wochenanalyse = False
            st.caption(
                "Modus F braucht **beide** Profile: den **Bemessungstag** (Spitzendeckung) und die "
                "**Bemessungswoche** (Dauerbetrieb und Erholung des Speichers). Zulässig ist nur, "
                "was in beiden besteht."
            )
        else:
            analysezeitraum = halte(
                st.radio, "eg_analysezeitraum", "Ein Tag (24 h)",
                label="Analysezeitraum", options=["Ein Tag (24 h)", "Eine Woche (7 Tage)"],
                horizontal=True,
            )
            wochenanalyse = analysezeitraum.startswith("Eine Woche")

        hochgeladene_datei = st.file_uploader(
            "Excel-Datei mit Bemessungstag" if ist_technoeko else "Excel-Datei mit Zapfprofil",
            type=["xlsx", "xls"],
        )
        gemerkte_messdaten = st.session_state.get(MONITORING_DATEN)
        if hochgeladene_datei is None and gemerkte_messdaten is not None:
            st.caption(
                f"📎 Zuletzt geladen: **{gemerkte_messdaten['dateiname']}** — wird weiterverwendet. "
                "Zum Ersetzen einfach eine neue Datei hochladen."
            )
        aufloesung_label = halte(
            st.radio, "eg_aufloesung", "5 Minuten",
            label="Zeitschrittweite der Messdaten", options=["1 Minute", "5 Minuten"],
        )
        aufloesung = "1min" if aufloesung_label == "1 Minute" else "5min"

        werte_je_tag = "1440 Werte (24 h, 1-Minuten-Schritte)" if aufloesung == "1min" \
            else "288 Werte (24 h, 5-Minuten-Schritte, werden gleichverteilt auf 1-Minuten-Werte)"
        if wochenanalyse:
            st.caption(
                "**Wochenanalyse:** ein Tagesblatt je Wochentag (mehrere Arbeitsblätter in derselben "
                "Excel-Datei), jedes Blatt im unten beschriebenen Format und beginnend bei 00:00. "
                "Die Blattreihenfolge in der Datei bestimmt die zeitliche Reihenfolge. "
                f"Benötigte Spalte je Blatt: **Zapfprofil in Liter** · genau {werte_je_tag}."
            )
        else:
            st.caption(
                f"Benötigte Spalte: **Zapfprofil in Liter** (numerisch, keine Lücken, keine negativen Werte) · "
                f"genau {werte_je_tag}."
            )
        st.caption(
            "Optional: **Datum** und **Uhrzeit** je Zeile für eine automatische Plausibilitätsprüfung "
            "der Zeitstempel (Lücken, Reihenfolge, bei Wochenanalyse je Blatt)."
        )

        if ist_technoeko:
            wochen_datei = st.file_uploader(
                "Excel-Datei mit Bemessungswoche", type=["xlsx", "xls"], key="f_wochendatei",
            )
            gemerkte_woche = st.session_state.get(WOCHEN_DATEN)
            if wochen_datei is None and gemerkte_woche is not None:
                st.caption(
                    f"📎 Zuletzt geladen: **{gemerkte_woche['dateiname']}** — wird weiterverwendet."
                )
            st.caption(
                "Ein Tagesblatt je Wochentag (mehrere Arbeitsblätter in derselben Datei), jedes Blatt "
                f"im Format oben und beginnend bei 00:00 · genau {werte_je_tag} je Blatt. Die "
                "Blattreihenfolge bestimmt die zeitliche Reihenfolge."
            )

    if braucht_norm_eingabe:
        st.header("1. Tagesbedarf (Norm)")
        methode_label = halte(
            st.radio, "eg_methode", "Verfahren A: nach Personenzahl (Gl. 20)",
            label="Berechnungsverfahren",
            options=[
                "Verfahren A: nach Personenzahl (Gl. 20)",
                "Verfahren B: nach Einheiten/Fläche (Gl. 21)",
                "Verfahren C: über äquivalente Personenanzahl (Anhang B.2.2, Gl. B.1–B.5)",
            ],
        )
        methode = methode_label.split(":")[0].removeprefix("Verfahren ").strip()

        if methode == "C":
            st.caption(
                "Anhang B.2.2: Für Wohnungen und Einfamilien-/Reihenhäuser wird "
                r"$V_{W,P,day}$ aus der bewohnbaren Fläche $A_h$ über die äquivalente "
                r"Personenanzahl $n_{P,eq}$ berechnet (Gl. B.1–B.5) und anschließend "
                "nach Gl. 20 zum Tagesvolumen aufmultipliziert."
            )
            wohnungstyp = halte(
                st.selectbox, "eg_wohnungstyp", GEBAEUDETYP_WOHNUNG,
                label="Gebäudetyp", options=[GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH],
                help="Wohnung → Gl. B.3/B.4, Einfamilien-/Reihenhaus → Gl. B.1/B.2.",
            )
            wohnflaeche = halte(
                st.number_input, "eg_wohnflaeche", 70.0,
                label=r"Bewohnbare Fläche je Einheit $A_h$ [m²]", min_value=1.0, step=5.0,
            )
            anzahl_wohneinheiten = halte(
                st.number_input, "eg_wohneinheiten", 1,
                label="Anzahl gleichartiger Wohneinheiten [-]", min_value=1,
                help="n_P,eq gilt je Wohneinheit (Personengruppe an derselben TWW-Leitung) "
                     "und wird mit dieser Anzahl auf das Gesamtgebäude hochgerechnet.",
            )
            with st.expander("Vorgabewerte x und y (Gl. B.5)"):
                x_max_spez_volumen = halte(
                    st.number_input, "eg_x_spez", X_MAX_SPEZ_VOLUMEN,
                    label=r"$x$ [l/(Person·d)]", min_value=0.0, step=0.01, format="%.2f",
                )
                y_spez_volumen = halte(
                    st.number_input, "eg_y_spez", Y_SPEZ_VOLUMEN,
                    label=r"$y$ [l/(m²·d)]", min_value=0.0, step=0.01, format="%.2f",
                )
                st.caption(
                    "Vorgabewerte aus Anhang B.2.2; ein nationaler Anhang mit abweichenden "
                    "Werten kann hier eingetragen werden."
                )
        else:
            n_personen = halte(st.number_input, "eg_n_personen", 268,
                               label=r"Personenzahl $n_P$ [-]", min_value=1)
            v_pro_person = halte(st.number_input, "eg_v_person", 40.0,
                                 label=r"Spez. Bedarf pro Person $V_{W,P,day}$ [l]", min_value=0.0)
            n_einheiten = halte(st.number_input, "eg_n_einheiten", 1,
                                label=r"Anzahl Einheiten $f$ [-]", min_value=1)
            v_pro_einheit = halte(st.number_input, "eg_v_einheit", 70.0,
                                  label=r"Spez. Bedarf pro Einheit $V_{W,f,day}$ [l]", min_value=0.0)
        with st.expander("Lastprofil aus CSV laden"):
            st.caption(
                "24 Stundenanteile des Tagesbedarfs in Prozent, beginnend bei 00:00. "
                "Format und Beispiel: beispiele/LIESMICH.md. Das geladene Profil steht "
                "danach in der Auswahl und gilt für die laufende Sitzung."
            )
            profil_datei = st.file_uploader(
                "CSV-Datei", type=["csv", "txt"], key="eg_profil_csv",
            )
            if profil_datei is not None:
                try:
                    profil_name, stundenanteile = lies_lastprofil_csv(profil_datei)
                    ergaenze_lastprofil(profil_name, stundenanteile)
                    st.success(f"Profil „{profil_name}“ geladen.")
                except LastprofilFehler as fehler:
                    st.error(str(fehler))

        profil = halte(
            st.selectbox, "eg_profil", STANDARD_PROFIL,
            label="Lastprofil (Anhang B.1 oder eigenes Profil)",
            options=list(LASTPROFILE_STUNDENANTEILE),
        )

    if braucht_anlagen_eingabe:
        st.header("2. Speicher & Erzeuger")
        speicher_typ = halte(
            st.selectbox, "eg_speicher_typ", "Speicherladesystem",
            label="Speichertyp", options=["Speicherladesystem", "Gemischtes Speichersystem"],
        )
        if ist_investition or ist_technoeko:
            st.caption(r"$V_{sto}$ und $\Phi_N$ werden in Modus D/F aus den Katalogen unten durchprobiert.")
            v_je_speicher, phi_n = 3000.0, 70.5  # Platzhalter, wird pro Kombination überschrieben
        else:
            # Mehrere baugleiche Speicher (z. B. 2 x 1500 l statt 1 x 3000 l) werden in
            # core/speicherverbund.py auf die Normgrößen V_sto/h_sto/h_sensor/q_sb,sto
            # umgerechnet. In Modus D/F entfällt die Auswahl, weil dort je Kombination
            # genau ein Katalogprodukt eingesetzt wird.
            anzahl_speicher = int(halte(
                st.number_input, "eg_n_speicher", 1,
                label="Anzahl baugleicher Speicher [-]", min_value=1, max_value=10, step=1,
                help="Mehrere Speicher werden zu einem Rechenspeicher zusammengefasst: Volumen "
                     "und Bereitschaftsverlust addieren sich, die Höhe nur bei Serienschaltung.",
            ))
            if anzahl_speicher > 1:
                speicher_schaltung = halte(
                    st.radio, "eg_speicher_schaltung", SERIE,
                    label="Hydraulische Einbindung", options=list(SCHALTUNGEN), horizontal=True,
                    help="Serie: nacheinander durchströmt, die Schichtung läuft durch alle Speicher "
                         "→ rechnerische Höhe n · h. Parallel: gleichzeitig durchströmt, alle "
                         "entschichten synchron → rechnerische Höhe bleibt die Einzelhöhe h.",
                )
                if speicher_schaltung == SERIE:
                    fuehler_position = halte(
                        st.radio, "eg_fuehler_position", FUEHLER_ZAPFSEITIG,
                        label="Temperaturfühler sitzt im", options=list(FUEHLER_POSITIONEN),
                        help="Bei Serienschaltung zählt h_sensor ab der Oberkante des zapfseitigen "
                             "Speichers durch den Stapel nach unten. Ein Fühler im ersten (kalten) "
                             "Speicher liegt deshalb um (n−1)·h tiefer und die WP schaltet später ein.",
                    )
            je_speicher = " je Speicher" if anzahl_speicher > 1 else ""
            if ist_norm_soll:
                # Modus A2 dimensioniert eine eigene Anlage. V_sto und Φ_N liegen
                # deshalb auf eigenen Schlüsseln: Die reale Anlage aus Modus A
                # bleibt beim Iterieren unverändert stehen, und beide Zustände
                # können gleichzeitig hinterlegt sein (Kostenvergleich in Modus E).
                # Startwert ist die reale Anlage - von dort aus wird iteriert.
                st.caption(
                    "🎯 **Norm-Soll-Zustand:** $V_{sto}$ und $\\Phi_N$ hier selbst verändern, bis "
                    "die Auslegung passt. Alle übrigen Eingaben sind dieselben wie in Modus A, und "
                    "die reale Anlage aus Modus A bleibt davon unberührt."
                )
            schluessel_v = "eg_v_sto_soll" if ist_norm_soll else "eg_v_sto"
            schluessel_phi = "eg_phi_n_soll" if ist_norm_soll else "eg_phi_n"
            standard_v = st.session_state.get("_halt_eg_v_sto", 3000.0) if ist_norm_soll else 3000.0
            standard_phi = st.session_state.get("_halt_eg_phi_n", 70.5) if ist_norm_soll else 70.5
            v_je_speicher = halte(st.number_input, schluessel_v, standard_v,
                                  label=r"Bruttovolumen Speicher $V_{sto}$ [l]" + je_speicher, min_value=1.0)
            phi_n = halte(st.number_input, schluessel_phi, standard_phi,
                          label=r"Nennleistung Erzeuger $\Phi_N$ [kW]", min_value=0.1)
        je_speicher = " je Speicher" if anzahl_speicher > 1 else ""
        h_je_speicher = halte(st.number_input, "eg_h_sto", 2.0,
                              label=r"Gesamthöhe Speicher $h_{sto}$ [m]" + je_speicher, min_value=0.1)
        h_sensor_je_speicher = halte(
            st.number_input, "eg_h_sensor", 0.6,
            label=r"Fühlerhöhe $h_{sensor}$ [m] (ab Oberkante)", min_value=0.0,
            help="Abstand des Temperaturfühlers von der Oberkante des Speichers, in dem er sitzt, "
                 "so wie h_sensor in Gl. 5/10 eingeht (0 = Fühler ganz oben). Die Einbauhöhe über "
                 "dem Speicherboden ergibt sich daraus als h_sto − h_sensor und steht so auch im "
                 "Ergebnisprotokoll.")
        if h_sensor_je_speicher < h_je_speicher:
            st.caption(f"→ Einbauhöhe Fühler über Boden: {h_je_speicher - h_sensor_je_speicher:.2f} m")
        f_l = halte(st.number_input, "eg_f_l", 1.0,
                    label=r"Ladungsfaktor $f_l$ [-]", min_value=0.0, max_value=1.0)
        t_lag_hg = halte(st.number_input, "eg_t_lag", 4.0,
                         label=r"Zeitverzögerung Erzeuger $t_{lag,HG}$ [min]", min_value=0.0)

        st.header("3. Verluste & Netz")
        if braucht_monitoring_eingabe:
            verlust_aus_messung = halte(
                st.checkbox, "eg_verlust_aus_messung", False,
                label="Gemessenen Gesamtverlust verwenden (statt Gl. 6/9 zu schätzen)",
                help="Ersetzt die Norm-Schätzung für Speicher- und Verteilverlust durch einen "
                     "aus den IST-Messdaten bestimmten Summenwert.",
            )
        if verlust_aus_messung:
            verlust_gesamt_je_minute = halte(
                st.number_input, "eg_q_v_ges", 0.19,
                label=r"Gemessener Gesamtverlust (Speicher + Verteilung) $q_{V,ges}$ [kWh/min]",
                min_value=0.0,
            )
            st.caption(
                "Gl. 6 (Speicherverlust) und Gl. 9 (Verteilverlust) entfallen dadurch; "
                "es wird direkt mit diesem Messwert je Minute gerechnet."
            )
            q_sb_je_speicher, q_dis_spec, l_dis = 0.0, 0.0, 0.0
        else:
            q_sb_je_speicher = halte(
                st.number_input, "eg_q_sb_sto", 3.48,
                label=r"Bereitschaftsverlust Speicher $q_{sb,sto}$ [kWh/24h]" + je_speicher,
                min_value=0.0,
                help="Bei mehreren Speichern der Wert EINES Speichers - die Verluste werden addiert. "
                     "Zwei kleine Speicher verlieren mehr als einer mit gleichem Gesamtvolumen.")
            q_dis_spec = halte(st.number_input, "eg_q_dis_spec", 7.0,
                               label=r"Spez. Leitungsverlust $q'_{dis}$ [W/m]", min_value=0.0)
            l_dis = halte(st.number_input, "eg_l_dis", 150.0,
                          label=r"Rohrleitungslänge $l_{dis}$ [m]", min_value=0.0)

        st.header("4. Temperaturen")
        theta_draw = halte(st.number_input, "eg_theta_draw", 60.0,
                           label=r"Zapftemperatur $\vartheta_{draw}$ [°C]")
        theta_c = halte(st.number_input, "eg_theta_c", 10.0,
                        label=r"Kaltwassertemperatur $\vartheta_c$ [°C]")
        theta_sto_max = halte(st.number_input, "eg_theta_sto_max", 63.0,
                              label=r"Max. Speichertemperatur $\vartheta_{sto,max}$ [°C]")
        theta_a = halte(st.number_input, "eg_theta_a", 15.0,
                        label=r"Umgebungstemperatur $\vartheta_a$ [°C]")

    if ist_vergleich:
        st.header("Hinterlegte Fälle")
        st.caption(
            "Modus C vergleicht die in Modus A und B gerechneten Fälle. Jeder Fall bringt "
            "die Eingaben mit, mit denen er gerechnet wurde — die Eingabefelder sind hier "
            "deshalb ausgeblendet."
        )
        for schluessel, bezeichnung in (
            (FALL_NORM, "Norm-Fall (Modus A)"), (FALL_MONITORING, "Monitoring-Fall (Modus B)"),
        ):
            fall = geholter_fall(schluessel)
            if fall is None:
                st.warning(f"⚠️ {bezeichnung}: noch nicht gerechnet")
                continue
            st.success(f"✅ {bezeichnung}")
            st.caption(f"{fall.quelle_label}\n\n{fall.kurzinfo}")
            if st.button(f"{bezeichnung} verwerfen", key=f"verwerfen_{schluessel}"):
                del st.session_state[schluessel]
                st.rerun()

    wp_katalog_datei = speicher_katalog_datei = None
    wp_katalog_name = sp_katalog_name = None
    wp_katalog = speicher_katalog = speicher_katalog_ohne_montage = None
    wp_rabatte = sp_rabatte = {}
    wp_montagekosten = 0.0
    sp_montage_pct = 0.0
    material_wahl = "Alle"
    max_laufzeit_h = 24.0
    raster_schritte = 25
    if braucht_kataloge:
        st.header("5. Investitionskataloge")
        wp_katalog_datei = st.file_uploader("WP-Katalog (Excel)", type=["xlsx", "xls"], key="wp_katalog")
        if wp_katalog_datei is None and hole_datei(SLOT_WP_KATALOG) is not None:
            st.caption(f"📎 Zuletzt geladen: **{hole_datei(SLOT_WP_KATALOG).name}** — wird weiterverwendet.")
        betriebspunkt_label = halte(
            st.radio, "eg_betriebspunkt", "B0/W55 (Trinkwassererwärmung, empfohlen)",
            label="Betriebspunkt für die Auslegung (Φ_N)",
            options=["B0/W55 (Trinkwassererwärmung, empfohlen)", "B0/W35"],
            help="Legt fest, welche der beiden Leistungsangaben je Modell als Nennleistung "
                 "für die Berechnung verwendet wird. W55 liegt näher an der üblichen "
                 "Speicher-Ladetemperatur für Trinkwassererwärmung.",
        )
        betriebspunkt = "W55" if betriebspunkt_label.startswith("B0/W55") else "W35"
        st.caption(
            "Benötigte Spalten (Substring-Suche, Reihenfolge egal): **Hersteller**, **Produkt**, "
            "Leistung **[kW]** und **COP** jeweils bei **B0/W35** und **B0/W55** (z. B. \"Leistung B0/W35 [kW]\", "
            "\"COP B0/W55\"), Abmessungen **Höhe**/**Breite**/**Länge** **[mm]**, **Listenpreis**, "
            "**Inbetriebnahme**-Kosten. Optional: **Transportkosten** (Default 0, falls nicht vorhanden), "
            "max. **Vorlauftemperatur** (nur informativ). Reine Herkunfts-/Basisspalten (z. B. \"... lt. Quelle\") "
            "werden ignoriert, bei mehreren Preisspalten wird die mit \"2026\" im Namen bevorzugt. "
            "Einzelne Zeilen mit fehlenden Pflichtangaben werden übersprungen (Warnung), nicht die ganze Datei."
        )
        speicher_katalog_datei = st.file_uploader("Speicher-Katalog (Excel)", type=["xlsx", "xls"], key="sp_katalog")
        if speicher_katalog_datei is None and hole_datei(SLOT_SPEICHER_KATALOG) is not None:
            st.caption(f"📎 Zuletzt geladen: **{hole_datei(SLOT_SPEICHER_KATALOG).name}** — wird weiterverwendet.")
        st.caption(
            "Benötigte Spalten: **Hersteller**, **Produktname**, **Nennvolumen** [l], **Höhe** [mm], "
            "**Nettokosten**. Optional: **Warmhalteverlust** [W] (EU-812/2013-Wert \"S\", wird nach Gl. 7 "
            "in q_sb,sto umgerechnet und ersetzt je Speichermodell den manuellen Bereitschaftsverlust-Wert "
            "aus Abschnitt 3) - fehlt er (Spalte oder einzelne Zeile), bleibt das Modell für Investkosten-/"
            "Volumenauswertungen nutzbar, nur für die normbasierte Optimierung (Modus D/F) nicht. "
            "Für den Grundriss zusätzlich entweder **Durchmesser** [mm] (runde Speicher) "
            "oder **Länge** + **Breite** [mm] (eckige Speicher) - je Zeile reicht die jeweils zutreffende "
            "Angabe. **Material** ist optional (nur für die Filterung nach Werkstoff). "
            "Einzelne Zeilen mit fehlenden Pflichtangaben werden übersprungen (Warnung), nicht die ganze Datei."
        )
        material_wahl = halte(
            st.selectbox, "eg_material", "Alle",
            label="Speicher-Material" + (" (Basis der Kostenfunktion)" if ist_kostenfunktion else ""),
            options=["Alle", "Edelstahl", "Stahl emailliert"],
        )

        # Über das Datei-Depot gelesen: so überstehen die Kataloge einen
        # Moduswechsel und landen zugleich in der Projektdatei.
        wp_bytes, wp_katalog_name = datei_quelle(SLOT_WP_KATALOG, wp_katalog_datei)
        sp_bytes, sp_katalog_name = datei_quelle(SLOT_SPEICHER_KATALOG, speicher_katalog_datei)
        if wp_bytes is not None and sp_bytes is not None:
            try:
                wp_katalog_ergebnis = lade_wp_katalog(wp_bytes, betriebspunkt=betriebspunkt)
                speicher_katalog_ergebnis = lade_speicher_katalog(sp_bytes)
            except KatalogFehler as e:
                st.error(f"Fehler beim Einlesen der Kataloge: {e}")
                st.stop()

            wp_katalog_roh = wp_katalog_ergebnis.katalog
            speicher_katalog_roh = speicher_katalog_ergebnis.katalog
            for w in wp_katalog_ergebnis.warnungen:
                st.warning(f"⚠️ WP-Katalog – {w}")
            for w in speicher_katalog_ergebnis.warnungen:
                st.warning(f"⚠️ Speicher-Katalog – {w}")

            st.subheader("Rabattgruppen")
            st.caption(
                "Herstellerspezifischer Rabatt auf den Listenpreis (WP) bzw. die Nettokosten "
                "(Speicher), fließt in Modus D, E und F ein."
            )
            wp_rabatte = {
                h: halte(st.number_input, f"rabatt_wp_{h}", 0.0,
                         label=f"Rabatt {h} (WP) [%]", min_value=0.0, max_value=100.0, step=1.0)
                for h in sorted(wp_katalog_roh["hersteller"].unique())
            }
            sp_rabatte = {
                h: halte(st.number_input, f"rabatt_sp_{h}", 0.0,
                         label=f"Rabatt {h} (Speicher) [%]", min_value=0.0, max_value=100.0, step=1.0)
                for h in sorted(speicher_katalog_roh["hersteller"].unique())
            }
            wp_katalog = wende_wp_rabatt_an(wp_katalog_roh, wp_rabatte)
            speicher_katalog = wende_speicher_rabatt_an(speicher_katalog_roh, sp_rabatte)

            st.subheader("Hersteller-Auswahl")
            st.caption(
                "Nur ausgewählte Hersteller fließen in Optimierung, Kostenfunktionen und die "
                "Kostenregressions-Plots ein - z. B. um einzelne Hersteller mit unplausiblen "
                "Katalogpreisen testweise auszuschließen."
            )
            wp_hersteller_auswahl = {
                h: halte(st.checkbox, f"wp_aktiv_{h}", True, label=h)
                for h in sorted(wp_katalog["hersteller"].unique())
            }
            sp_hersteller_auswahl = {
                h: halte(st.checkbox, f"sp_aktiv_{h}", True, label=h)
                for h in sorted(speicher_katalog["hersteller"].unique())
            }
            wp_katalog = wp_katalog[
                wp_katalog["hersteller"].map(wp_hersteller_auswahl)
            ].reset_index(drop=True)
            speicher_katalog = speicher_katalog[
                speicher_katalog["hersteller"].map(sp_hersteller_auswahl)
            ].reset_index(drop=True)

            st.subheader("Montagekosten")
            st.caption(
                "Zusätzlicher Investitionskostenbestandteil neben Listenpreis (und bei WP: "
                "Inbetriebnahme), fließt in Modus D, E und F ein. Bei der WP eine über alle "
                "Leistungsbereiche konstante, hier einzugebende Pauschale. Beim Speicher ein "
                "hier einzugebender Prozentsatz, der auf die bereits rabattierten Investkosten "
                "(nach Abzug der Rabattgruppen oben) aufgeschlagen wird."
            )
            wp_montagekosten = halte(
                st.number_input, "eg_montage_wp", 0.0,
                label="Montagekosten WP [€] (konstant über alle Leistungsbereiche)",
                min_value=0.0, step=50.0,
            )
            sp_montage_pct = halte(
                st.number_input, "eg_montage_sp_pct", 0.0,
                label="Montagekosten Speicher [% der rabattierten Investkosten]",
                min_value=0.0, step=1.0,
            )
            speicher_katalog_ohne_montage = speicher_katalog
            wp_katalog = wende_wp_montage_an(wp_katalog, wp_montagekosten)
            speicher_katalog = wende_speicher_montage_an(speicher_katalog, sp_montage_pct)

        if ist_kostenfunktion:
            st.header("6. Parameter für Systemoptimierung")
            max_laufzeit_h = halte(
                st.slider, "eg_max_laufzeit_e", 24,
                label="Max. zulässige WP-Laufzeit pro Tag [h]", min_value=1, max_value=24)
            raster_schritte = halte(
                st.slider, "eg_raster_schritte", 25,
                label="Rasterauflösung (Schritte je Achse)", min_value=5, max_value=40)

        if ist_technoeko:
            st.header("6. Randbedingungen der Optimierung")
            # Sperrzeiten des Netzbetreibers begrenzen die tatsächlich nutzbare
            # Laufzeit; geprüft wird je Kalendertag, nicht über die Summe des
            # Zeitraums. 18 h/d ist der in der Praxis übliche Richtwert.
            max_laufzeit_h = halte(
                st.slider, "eg_max_laufzeit_f", 18,
                label="Max. zulässige WP-Laufzeit pro Tag [h]", min_value=1, max_value=24,
                help="Begrenzt die Erzeugerlaufzeit je Kalendertag (Sperrzeiten). Geprüft wird "
                     "der längste Tag im jeweiligen Zapfprofil, nicht die Summe über den Zeitraum.",
            )

# Einzelspeicher-Eingaben -> Normgrößen eines gedachten Gesamtspeichers.
verbund = Speicherverbund(
    anzahl=anzahl_speicher,
    v_je_speicher=v_je_speicher,
    h_je_speicher=h_je_speicher,
    h_sensor_je_speicher=h_sensor_je_speicher,
    q_sb_je_speicher=q_sb_je_speicher,
    schaltung=speicher_schaltung,
    fuehler_position=fuehler_position,
)

daten = Eingabedaten(
    tagesbedarf_methode=methode,
    n_personen=n_personen,
    v_pro_person=v_pro_person,
    n_einheiten=n_einheiten,
    v_pro_einheit=v_pro_einheit,
    wohnungstyp=wohnungstyp,
    wohnflaeche=wohnflaeche,
    anzahl_wohneinheiten=anzahl_wohneinheiten,
    x_max_spez_volumen=x_max_spez_volumen,
    y_spez_volumen=y_spez_volumen,
    gewaehltes_profil=profil,
    speicher_typ=speicher_typ,
    v_sto=verbund.v_sto,
    h_sto=verbund.h_sto,
    h_sensor=verbund.h_sensor,
    f_l=f_l,
    phi_n=phi_n,
    t_lag_hg=t_lag_hg,
    q_sb_sto=verbund.q_sb_sto,
    q_dis_spec=q_dis_spec,
    l_dis=l_dis,
    verlust_gesamt_je_minute=verlust_gesamt_je_minute,
    theta_draw=theta_draw,
    theta_c=theta_c,
    theta_sto_max=theta_sto_max,
    theta_a=theta_a,
)

fehler = daten.validieren()
if fehler:
    for f in fehler:
        st.error(f)
    st.stop()

zapf_ist = ergebnis_ist = monitoring = wochen_monitoring = monitoring_quelle_label = None
monitoring_dateiname = None
anzahl_tage = 1
warnliste: list[str] = []
if braucht_monitoring_eingabe:
    # Neuer Upload wandert ins Datei-Depot; von dort wird gelesen. Liegt schon
    # ein geparstes Ergebnis im Cache (MONITORING_DATEN), wird dieses genommen
    # und die Datei nicht erneut eingelesen.
    neu_hochgeladen = hochgeladene_datei is not None
    quelle_bytes, quelle_name = datei_quelle(SLOT_BEMESSUNGSTAG, hochgeladene_datei)
    if quelle_bytes is not None and (neu_hochgeladen or st.session_state.get(MONITORING_DATEN) is None):
        hochgeladene_datei = quelle_bytes
        try:
            if wochenanalyse:
                wochen_monitoring = lade_wochenzapfprofil(hochgeladene_datei, aufloesung)
                zapf_ist = wochen_monitoring.zapfprofil_l_min
                anzahl_tage = wochen_monitoring.anzahl_tage
                monitoring_quelle_label = (
                    f"Monitoring-Woche ({wochen_monitoring.anzahl_tage} Tage, {wochen_monitoring.aufloesung}, "
                    f"Blätter: {', '.join(wochen_monitoring.tagesblaetter)})"
                )
                warnliste = wochen_monitoring.warnungen
            else:
                monitoring = lade_zapfprofil(hochgeladene_datei, aufloesung)
                zapf_ist = monitoring.zapfprofil_l_min
                monitoring_quelle_label = f"Monitoring ({monitoring.anzahl_rohwerte} Rohwerte, {monitoring.aufloesung})"
                warnliste = monitoring.warnungen
        except (MonitoringDatenFehler, WochenMonitoringDatenFehler) as e:
            st.error(f"Fehler beim Einlesen der Monitoring-Daten: {e}")
            st.stop()
        monitoring_dateiname = quelle_name
        st.session_state[MONITORING_DATEN] = {
            "zapfprofil": zapf_ist,
            "quelle_label": monitoring_quelle_label,
            "dateiname": monitoring_dateiname,
            "anzahl_tage": anzahl_tage,
            "warnungen": warnliste,
            "analysezeitraum": analysezeitraum,
            "aufloesung_label": aufloesung_label,
        }
    elif st.session_state.get(MONITORING_DATEN) is not None:
        gemerkt = st.session_state[MONITORING_DATEN]
        zapf_ist = gemerkt["zapfprofil"]
        monitoring_quelle_label = gemerkt["quelle_label"]
        monitoring_dateiname = gemerkt["dateiname"]
        anzahl_tage = gemerkt["anzahl_tage"]
        warnliste = gemerkt["warnungen"]
        if (analysezeitraum, aufloesung_label) != (gemerkt["analysezeitraum"], gemerkt["aufloesung_label"]):
            st.warning(
                f"⚠️ Die zuletzt geladene Datei **{monitoring_dateiname}** wurde als "
                f"„{gemerkt['analysezeitraum']} / {gemerkt['aufloesung_label']}\" eingelesen. "
                "Analysezeitraum oder Zeitschrittweite lassen sich nur beim Hochladen "
                "anwenden — bitte die Datei mit der neuen Einstellung erneut hochladen."
            )
        # Es gilt, womit die gemerkten Messdaten tatsächlich eingelesen wurden
        analysezeitraum = gemerkt["analysezeitraum"]
        aufloesung_label = gemerkt["aufloesung_label"]
    else:
        st.info("Bitte eine Excel-Datei mit den Monitoring-Zapfdaten hochladen.")
        st.stop()

    ergebnis_ist = berechne_versorgungskennlinie(daten, zapf_ist)
    for w in warnliste:
        st.warning(f"⚠️ {w}")

# --- Bemessungswoche (nur Modus F) ---------------------------------------
# Zweites, unabhängiges Zapfprofil: der Bemessungstag prüft die Spitzendeckung,
# die Bemessungswoche den Dauerbetrieb. Beide müssen bestehen.
zapf_woche = None
wochen_quelle_label = wochen_dateiname = None
if ist_technoeko:
    neu_woche = wochen_datei is not None
    woche_bytes, woche_name = datei_quelle(SLOT_BEMESSUNGSWOCHE, wochen_datei)
    if woche_bytes is not None and (neu_woche or st.session_state.get(WOCHEN_DATEN) is None):
        try:
            woche_geladen = lade_wochenzapfprofil(woche_bytes, aufloesung)
        except (MonitoringDatenFehler, WochenMonitoringDatenFehler) as e:
            st.error(f"Fehler beim Einlesen der Bemessungswoche: {e}")
            st.stop()
        zapf_woche = woche_geladen.zapfprofil_l_min
        wochen_quelle_label = (
            f"Bemessungswoche ({woche_geladen.anzahl_tage} Tage, {woche_geladen.aufloesung}, "
            f"Blätter: {', '.join(woche_geladen.tagesblaetter)})"
        )
        wochen_dateiname = woche_name
        st.session_state[WOCHEN_DATEN] = {
            "zapfprofil": zapf_woche,
            "quelle_label": wochen_quelle_label,
            "dateiname": wochen_dateiname,
            "warnungen": woche_geladen.warnungen,
        }
        for w in woche_geladen.warnungen:
            st.warning(f"⚠️ Bemessungswoche — {w}")
    elif st.session_state.get(WOCHEN_DATEN) is not None:
        gemerkt_w = st.session_state[WOCHEN_DATEN]
        zapf_woche = gemerkt_w["zapfprofil"]
        wochen_quelle_label = gemerkt_w["quelle_label"]
        wochen_dateiname = gemerkt_w["dateiname"]

zapf_soll = ergebnis_soll = None
if braucht_norm_eingabe:
    zapf_soll = zapfprofil_minutenwerte(daten)
    if anzahl_tage > 1:
        # An Wochenanalyse-Länge angleichen: Normtag als "typische Woche" wiederholen,
        # damit Modus C (Vergleich) und ein Norm-basierter Modus D/E-Raster über
        # denselben Zeitraum wie die Monitoring-Woche rechnen.
        zapf_soll = np.tile(zapf_soll, anzahl_tage)
    ergebnis_soll = berechne_versorgungskennlinie(daten, zapf_soll)


def monitoring_zeilen() -> dict[str, str]:
    """Herkunftsangaben der Messdaten für das Parameterprotokoll."""
    if monitoring_quelle_label is None:
        return {}
    return {
        "Monitoring-Datei": monitoring_dateiname or "—",
        "Analysezeitraum": analysezeitraum,
        "Auflösung Messdaten": aufloesung_label,
    }


def aktueller_parametersatz(*, ist_monitoring: bool, quelle_label: str) -> dict[str, dict[str, str]]:
    """Parametersatz des gerade gerechneten Falls - Grundlage für das
    Ergebnisprotokoll und für den in Modus C hinterlegten Fall."""
    return parametersatz(
        daten,
        methode_label=methode_label,
        quelle_label=quelle_label,
        ist_monitoring=ist_monitoring,
        monitoring_zeilen=monitoring_zeilen() if ist_monitoring else None,
        verbund=verbund,
    )


def eingabeparameter_block(parameter: dict[str, dict[str, str]] | None = None) -> str:
    """Vollständiger Echo aller Eingabewerte, die tatsächlich in die Berechnung
    eingeflossen sind - für Nachvollziehbarkeit im Ergebnisprotokoll/PDF-Export."""
    teile = ["EINGABEPARAMETER (vollständig, wie in die Berechnung eingeflossen)", "-" * 70]

    if parameter is None:
        # Modus D/E/F: Das Raster läuft je nach Auswahl entweder gegen das
        # Norm-Lastprofil oder gegen die Messdaten - nie gegen beide.
        parameter = aktueller_parametersatz(
            ist_monitoring=braucht_monitoring_eingabe,
            quelle_label=monitoring_quelle_label or daten.gewaehltes_profil,
        )

    if ist_investition or ist_kostenfunktion:
        hinweis = (
            "werden je Kombination durch den Katalog ersetzt, siehe unten" if ist_investition
            else "dienen hier nur als Referenzwerte für den Rasterbereich, siehe unten"
        )
        anlage = parameter[ABSCHNITT_ANLAGE]
        parameter = dict(parameter)
        parameter[ABSCHNITT_ANLAGE] = {"Hinweis V_sto / Φ_N": hinweis, **anlage}

    teile.append(parametersatz_text(parameter))

    if braucht_kataloge and wp_katalog is not None and speicher_katalog is not None:
        wp_rabatt_text = ", ".join(f"{h}: {p:.0f} %" for h, p in wp_rabatte.items() if p > 0) or "keine"
        sp_rabatt_text = ", ".join(f"{h}: {p:.0f} %" for h, p in sp_rabatte.items() if p > 0) or "keine"
        katalog_block = (
            f"WP-Katalog                          : {wp_katalog_name} ({len(wp_katalog)} Modelle)\n"
            f"WP-Betriebspunkt (Φ_N)              : {betriebspunkt_label}\n"
            f"Speicher-Katalog                    : {sp_katalog_name} ({len(speicher_katalog)} Modelle)\n"
            f"Speicher-Material (Filter)          : {material_wahl}\n"
            f"Rabattgruppen WP                    : {wp_rabatt_text}\n"
            f"Rabattgruppen Speicher              : {sp_rabatt_text}\n"
            f"Montagekosten WP (Pauschale)        : {wp_montagekosten:,.2f} €\n"
            f"Montagekosten Speicher (% auf rabattierte Investkosten) : {sp_montage_pct:.1f} %"
        )
        if ist_kostenfunktion:
            katalog_block += (
                f"\nMax. zulässige WP-Laufzeit          : {max_laufzeit_h:.0f} h/d\n"
                f"Rasterauflösung                     : {raster_schritte} x {raster_schritte}"
            )
        if ist_technoeko:
            katalog_block += (
                f"\nMax. zulässige WP-Laufzeit          : {max_laufzeit_h:.0f} h/d (je Kalendertag)\n"
                f"Bemessungswoche                     : {wochen_dateiname or '— (nicht geladen)'}"
            )
        teile.append(katalog_block)

    return "\n\n".join(teile)


def anlagenkosten_text(anlagen: list) -> str:
    """Kostentabelle der bewerteten Anlagen (Modus E) für das Ergebnisprotokoll.

    Die erste Zeile ist der Ausgangszustand; ihre Differenzspalten bleiben leer,
    alle weiteren Zeilen zeigen die Mehr-/Minderkosten gegenüber dieser Zeile."""
    kopf = (
        f"{'Anlage':<30} | {'V_sto [l]':>9} | {'Φ_N [kW]':>10} | {'WP [€]':>12} | "
        f"{'Speicher [€]':>14} | {'Gesamt [€]':>13} | {'Δ [€]':>13} | {'Δ [%]':>9}"
    )
    zeilen = [kopf, "-" * len(kopf)]
    for a in anlagen:
        diff_abs = "—" if a.ist_ausgangszustand else f"{a.diff_abs:>+,.2f}"
        diff_pct = "—" if a.ist_ausgangszustand else f"{a.diff_pct:>+.1f}"
        zeilen.append(
            f"{a.bezeichnung:<30} | {a.v_sto:>9,.0f} | {a.phi_n:>10.1f} | {a.wp_kosten:>12,.2f} | "
            f"{a.speicher_kosten:>14,.2f} | {a.gesamtkosten:>13,.2f} | {diff_abs:>13} | {diff_pct:>9}"
        )
    return "\n".join(zeilen)


def verlustzeilen(v) -> list[tuple[str, str, str, str]]:
    """Gegenüberstellung der Wärmeverluste beider Fälle (Modus C).

    Liefert (Bezeichnung, Norm-Wert, Monitoring-Wert, Abweichung) - dieselbe
    Quelle für die Tabelle in der App und für das Ergebnisprotokoll/PDF. Der
    Norm-Fall schätzt die Verluste nach Gl. 6/9 und weist sie getrennt aus; beim
    gemessenen Summenverlust ist die Aufteilung unbekannt und bleibt leer.
    """
    s, i = v.verlust_soll, v.verlust_ist
    if s is None or i is None:
        return []

    def posten(wert: float | None) -> str:
        return "—" if wert is None else f"{wert:,.2f}"

    zeilen = [
        ("Verlustansatz", s.ansatz, i.ansatz, ""),
        ("Speicher Q_W,sto,t (Gl. 6) [kWh/d]", posten(s.speicher_kwh_tag), posten(i.speicher_kwh_tag), ""),
        ("Verteilung Q_W,dis,t (Gl. 9) [kWh/d]", posten(s.verteilung_kwh_tag), posten(i.verteilung_kwh_tag), ""),
        ("Gesamttagesverlust q_V,ges [kWh/d]", f"{s.gesamt_kwh_tag:,.2f}", f"{i.gesamt_kwh_tag:,.2f}",
         "—" if v.diff_verlust_pct is None else f"{v.diff_verlust_pct:+.1f} %"),
    ]
    # Der Auslegungszeitraum ist in Modus C für beide Fälle gleich lang; die
    # Summe über den Zeitraum ist nur dann eine eigene Information.
    if s.minuten != MINUTEN_PRO_TAG or i.minuten != MINUTEN_PRO_TAG:
        zeilen.append((
            "Verlust über Auslegungszeitraum [kWh]",
            f"{s.gesamt_kwh_zeitraum:,.2f}", f"{i.gesamt_kwh_zeitraum:,.2f}",
            "—" if v.diff_verlust_pct is None else f"{v.diff_verlust_pct:+.1f} %",
        ))
    return zeilen


def verlusttabelle_text(v, titel_links: str = "Norm (Soll)", titel_rechts: str = "Monitoring (Ist)") -> str:
    """Verlustgegenüberstellung als Textblock für das Ergebnisprotokoll."""
    zeilen = verlustzeilen(v)
    if not zeilen:
        return ""
    breite = max(len(z[0]) for z in zeilen)
    kopf = f"{'Wärmeverlust'.ljust(breite)} | {titel_links:>26} | {titel_rechts:>26} | {'Abweichung':>10}"
    ausgabe = [kopf, "-" * len(kopf)]
    for name, links, rechts, abw in zeilen:
        ausgabe.append(f"{name.ljust(breite)} | {links:>26} | {rechts:>26} | {abw:>10}")
    return "\n".join(ausgabe)


A4_HOCH = (8.27, 11.69)
A4_QUER = (11.69, 8.27)


# Zeichenbreite der Monospace-Schrift (DejaVu Sans Mono, matplotlibs Vorgabe für
# family="monospace") als Anteil der Schriftgröße - Grundlage dafür, die
# Zeilenbreite in Zeichen auszurechnen. Nachgemessen gegen den PDF-Renderer, der
# den Export tatsächlich schreibt; der Agg-Renderer rundet Zeichenbreiten auf
# ganze Pixel und liefert deshalb größere Werte, die hier nicht maßgeblich sind.
MONO_ZEICHENBREITE = 0.6022
# Reserve auf die rechnerische Seitenbreite, damit Rundung und eine eventuell
# abweichende Ersatzschrift die letzte Spalte nicht doch über den Rand schieben.
BREITEN_RESERVE = 0.97
SCHRIFTGROESSE_PROTOKOLL = 8.0
SCHRIFTGROESSE_MIN = 6.0
RAND_QUER, RAND_HOCH = 0.05, 0.06


def _passende_schriftgroesse(zeilen: list[str], nutzbare_breite_zoll: float) -> tuple[float, int]:
    """Schriftgröße und daraus folgende Zeichen je Zeile für den Textblock.

    Die längste Zeile bestimmt die Schrift: Passt sie bei 8 pt nicht auf die
    Seite, wird verkleinert, bis sie passt - höchstens jedoch bis
    SCHRIFTGROESSE_MIN, darunter wäre der Ausdruck nicht mehr lesbar. Ohne das
    schnitt matplotlib rechts einfach ab, ohne Hinweis; betroffen waren die
    breiten Tabellen (Anlagenkosten in Modus E/F: rund 131 Zeichen, die
    Parametergegenüberstellung in Modus C, die Laufkennzahlen in Modus F).
    """
    breite = nutzbare_breite_zoll * BREITEN_RESERVE
    laengste = max((len(z) for z in zeilen), default=0)
    groesse = SCHRIFTGROESSE_PROTOKOLL
    if laengste > 0:
        passend = breite * 72.0 / (laengste * MONO_ZEICHENBREITE)
        groesse = max(SCHRIFTGROESSE_MIN, min(groesse, passend))

    zeichen_je_zeile = int(breite * 72.0 / (groesse * MONO_ZEICHENBREITE))
    if groesse > SCHRIFTGROESSE_MIN:
        # Die Schrift wurde gerade so gewählt, dass die längste Zeile passt -
        # ein Rundungsrest darf sie nicht doch noch umbrechen.
        zeichen_je_zeile = max(zeichen_je_zeile, laengste)
    return groesse, zeichen_je_zeile


def _harte_umbrueche(zeilen: list[str], zeichen_je_zeile: int) -> list[str]:
    """Bricht Zeilen um, die selbst bei kleinster Schrift nicht passen.

    Greift praktisch nur, wenn ein sehr langer Einzelwert (etwa ein langer
    Dateiname) in einer Zeile steht. Lieber umgebrochen und eingerückt
    weitergeführt als stillschweigend abgeschnitten.
    """
    ausgabe: list[str] = []
    for zeile in zeilen:
        rest = zeile
        while len(rest) > zeichen_je_zeile:
            ausgabe.append(rest[:zeichen_je_zeile])
            rest = "    " + rest[zeichen_je_zeile:]
        ausgabe.append(rest)
    return ausgabe


def pdf_textseiten(
    pdf: PdfPages, text: str, zeilen_pro_seite: int | None = None, *,
    querformat: bool = False,
) -> None:
    """Schreibt einen (langen) Text als eine oder mehrere A4-Textseiten ins PDF.

    `querformat=True` dreht die Seite auf A4 quer. Das Ergebnisprotokoll wird in
    allen Modi quer ausgegeben: Die Tabellen (Eingangs- und Anlagenparameter,
    Kostenvergleiche, Laufkennzahlen) sind durchweg breiter als die rund 110
    Monospace-Zeichen, die im Hochformat auf die Seite passen. Quer sind es rund
    160 Zeichen, dafür passen weniger Zeilen auf die Seite.

    Reicht auch das nicht, wird zuerst die Schrift verkleinert und erst zuletzt
    umgebrochen - abgeschnitten wird nichts mehr.
    """
    breite_zoll, hoehe_zoll = A4_QUER if querformat else A4_HOCH
    rand = RAND_QUER if querformat else RAND_HOCH
    nutzbare_breite = breite_zoll * (1 - 2 * rand)

    zeilen = text.split("\n")
    groesse, zeichen_je_zeile = _passende_schriftgroesse(zeilen, nutzbare_breite)
    zeilen = _harte_umbrueche(zeilen, zeichen_je_zeile)

    if zeilen_pro_seite is None:
        # Zeilenhöhe = Schriftgröße x Zeilenabstand; 0,90 lässt oben und unten Rand.
        zeilenhoehe_zoll = groesse * 1.35 / 72.0
        zeilen_pro_seite = max(20, int(hoehe_zoll * 0.90 / zeilenhoehe_zoll))

    for i in range(0, len(zeilen), zeilen_pro_seite):
        chunk = "\n".join(zeilen[i:i + zeilen_pro_seite])
        text_fig = plt.figure(figsize=A4_QUER if querformat else A4_HOCH)
        text_fig.text(rand, 0.95, chunk,
                      transform=text_fig.transFigure, size=groesse,
                      family="monospace", va="top", ha="left")
        pdf.savefig(text_fig)
        plt.close(text_fig)


def einzelplot_downloads(figuren: dict, panel_titel: dict, key_prefix: str) -> None:
    """Download-Button je Panel: titellose Einzel-PDFs zum direkten Einfügen
    in die Arbeit (Bildunterschrift dann selbst ergänzen)."""
    with st.expander("📑 Einzelne Diagramme ohne Titel als PDF exportieren"):
        for key, efig in figuren.items():
            buf = io.BytesIO()
            efig.savefig(buf, format="pdf", bbox_inches="tight")
            st.download_button(
                f"📄 {panel_titel[key]}", data=buf.getvalue(),
                file_name=f"{key}.pdf", mime="application/pdf",
                key=f"dl_{key_prefix}_{key}",
            )


def _dateiname(text: str) -> str:
    return re.sub(r"[^\w\-]+", "_", text).strip("_")


def zeige_kostenregressionen(wp_katalog, speicher_katalog, key_prefix: str, speicher_katalog_ohne_montage) -> None:
    """Kostenregressionen je Hersteller (und bei Speichern zusätzlich je
    Material) - vor der eigentlichen Optimierung, zur visuellen Prüfung der
    Katalogdaten und der daraus abgeleiteten degressiven Kostenfunktionen.
    Jeder Plot ist einzeln als titelloses PDF exportierbar; am Seitenende
    steht zusätzlich ein Sammel-PDF mit allen Diagrammen (mit Titel) und
    einer Tabelle aller Kostenfunktionen.

    `wp_katalog`/`speicher_katalog` enthalten die Investkosten INKLUSIVE
    Montagepauschale bzw. -Prozentsatz (siehe core/montage.py) - das ist die
    auch in Modus D/E/F tatsächlich verwendete Definition. `speicher_katalog_
    ohne_montage` (vor core.montage.wende_speicher_montage_an, sonst
    identisch inkl. Rabatt und Hersteller-Auswahl) dient nur dem direkten
    Vergleich "ohne vs. mit Montage" in der Speicher-Gesamtübersicht je
    Material."""
    st.subheader("💶 Kostenregressionen je Hersteller")
    st.caption(
        "Degressive Kostenfunktion (Potenzansatz K = a · x^b) je Hersteller - zur Prüfung, wie gut "
        "sich die tatsächlich verwendeten Kostenfunktionen an die Katalogdaten anpassen. Speicher "
        "werden dabei immer nach Material unterschieden, auch in der Gesamtübersicht. Jeder Plot ist "
        "einzeln als PDF ohne Überschrift exportierbar; am Seitenende steht ein Sammel-PDF mit allen "
        "Diagrammen und einer Tabelle aller Kostenfunktionen."
    )
    ansicht = st.radio(
        "Kostenbasis", ["Absolute Kosten [€]", "Spezifische Kosten [€/kW bzw. €/l]"],
        horizontal=True, key=f"kostenansicht_{key_prefix}",
    )
    spezifisch = ansicht.startswith("Spezifische")
    y_label_wp = "Investkosten $C_I$ [€]" if not spezifisch else "Spez. Kosten $C_I$ [€/kW]"
    y_label_wp_lp = (
        "Investkosten $C_{I,LP}$ [€]" if not spezifisch else "Spez. Kosten $C_{I,LP}$ [€/kW]")
    y_label_wp_inkl_ibn = (
        "Investkosten $C_{I,LP+IBN}$ [€]" if not spezifisch else "Spez. Kosten $C_{I,LP+IBN}$ [€/kW]")
    y_label_wp_inkl_ibn_montage = (
        "Investkosten $C_I$ [€]" if not spezifisch else "Spez. Kosten $C_I$ [€/kW]")
    y_label_sp = (
        "Investkosten $C_{I,sto}$ [€]" if not spezifisch else "Spez. Kosten $C_{I,sto}$ [€/l]")
    y_label_sp_ohne = (
        "Investkosten $C_{I,NK,sto}$ [€]" if not spezifisch else "Spez. Kosten $C_{I,NK,sto}$ [€/l]")
    x_label_wp = r"Leistung $\Phi_N$ [kW]"
    x_label_sp = r"Volumen $V_{sto}$ [l]"
    # Mathtext-Symbole passend zur Notation der Masterthesis (Ĉ_I(Φ_N) = x·Φ_N^y für die WP,
    # Ĉ_I,sto(V_sto) = x·V_sto^y für den Speicher) - für die automatisch generierten
    # Legendenbeschriftungen der Potenzfits (core.visualisierung.funktions_label).
    x_mathtext_wp = r"\Phi_N"
    x_mathtext_sp = r"V_{sto}"
    sym_wp_gesamt = r"\hat{C}_\mathrm{I}"
    sym_wp_lp = r"\hat{C}_{I,LP}"
    sym_wp_lp_ibn = r"\hat{C}_{I,LP+IBN}"
    sym_wp_ibn = r"\hat{C}_{I,IBN}"
    sym_sp_gesamt = r"\hat{C}_{I,sto}"
    sym_sp_nk = r"\hat{C}_{I,NK,sto}"
    # Absolute Kosten steigen mit x (Punkte dicht oben rechts) -> Legende oben links frei;
    # spezifische Kosten fallen mit x (Punkte dicht oben links) -> Legende oben rechts frei.
    legend_loc = "upper right" if spezifisch else "upper left"
    material_linienfarben_liste = ["#00008B", "#006400", "#8B008B", "#B8860B"]

    wp_je_hersteller = wp_regression_je_hersteller(wp_katalog, spezifisch)
    # Schichtweise Aggregation für die Gesamtübersicht - Fit 1/2/3 sind exakt die
    # core.kostenfunktion-Funktionen, die auch tatsächlich verwendet werden (Fit 3 =
    # wp_kostenfunktion() ist die für Modus E/F verwendete Kostenfunktion), Diagramm und
    # Berechnung stimmen damit exakt überein. transport_kosten fließt hier bewusst nicht
    # ein, da die core.kostenfunktion-Fits das ebenfalls nicht berücksichtigen.
    listenpreis_spalte = "listenpreis_rabattiert" if "listenpreis_rabattiert" in wp_katalog.columns else "listenpreis"
    montagekosten_wp = (
        float(wp_katalog["montage_kosten"].iloc[0])
        if "montage_kosten" in wp_katalog.columns and not wp_katalog.empty else 0.0
    )
    wp_je_hersteller_fit1 = wp_regression_je_hersteller(
        wp_katalog, spezifisch, spalten=(listenpreis_spalte,))
    wp_je_hersteller_inkl_ibn = wp_regression_je_hersteller(
        wp_katalog, spezifisch, spalten=(listenpreis_spalte, "ibn_kosten"))
    wp_je_hersteller_fit3 = wp_regression_je_hersteller(
        wp_katalog, spezifisch, spalten=(listenpreis_spalte, "ibn_kosten", "montage_kosten"))
    try:
        wp_f1_diag = wp_kostenfunktion_listenpreis(wp_katalog)                          # Fit 1: nur Listenpreis
        wp_f_diag = wp_kostenfunktion_inkl_ibn(wp_katalog)                              # Fit 2: Listenpreis + IBN
        wp_f3_diag = wp_kostenfunktion(wp_katalog, montagekosten=montagekosten_wp)      # Fit 3: + Montage (Modus E/F)
    except KostenfunktionFehler:
        wp_f1_diag = wp_f_diag = wp_f3_diag = None
    sp_je_hersteller = speicher_regression_je_hersteller(speicher_katalog, spezifisch)
    sp_je_material = speicher_regression_je_material(speicher_katalog, spezifisch)

    wp_farben = farbzuordnung(list(wp_je_hersteller.keys()))
    sp_farben = farbzuordnung(list(sp_je_hersteller.keys()))

    pdf_eintraege = []       # (Anzeigename, Funktion(titel=None) -> Figure)
    tabellen_zeilen = []     # (Gruppe, Material, n, a, b, R²)

    def _erfasse_tabelle(name: str, material: str, g) -> None:
        if g.funktion is not None:
            tabellen_zeilen.append(
                (name, material, g.anzahl, g.funktion.koeffizient_a, g.funktion.exponent_b, g.funktion.r_quadrat)
            )
        else:
            tabellen_zeilen.append((name, material, g.anzahl, float("nan"), float("nan"), float("nan")))

    def _zeige_2spaltig(eintraege: list) -> None:
        for i in range(0, len(eintraege), 2):
            cols = st.columns(2)
            for col, (name, builder) in zip(cols, eintraege[i:i + 2]):
                fig = builder()
                with col:
                    st.markdown(f"**{name}**")
                    st.pyplot(fig)
                    buf = io.BytesIO()
                    fig.savefig(buf, format="pdf", bbox_inches="tight")
                    st.download_button(
                        "📄 PDF (ohne Titel)", data=buf.getvalue(),
                        file_name=f"{_dateiname(name)}.pdf", mime="application/pdf",
                        key=f"dl_{key_prefix}_{_dateiname(name)}",
                    )
                plt.close(fig)
                pdf_eintraege.append((name, builder))

    st.markdown("### Wärmepumpen — je Hersteller")
    wp_eintraege = []
    for name, g in wp_je_hersteller.items():
        farbe = wp_farben[name]
        wp_eintraege.append((
            g.bezeichnung,
            lambda titel=None, g=g, f=farbe: einzelfigur_regression(
                g, x_label_wp, y_label_wp, x_mathtext_wp, f, funktions_praefix=sym_wp_gesamt,
                titel=titel, legend_loc=legend_loc),
        ))
        _erfasse_tabelle(g.bezeichnung, "-", g)
    _zeige_2spaltig(wp_eintraege)

    st.markdown("### Wärmepumpe — Inbetriebnahmekosten je Leistung")
    st.caption(
        "Kostenfunktion für die Inbetriebnahmekosten aller Modelle der hochgeladenen WP-Excel "
        "(herstellerübergreifend gepoolt) in Abhängigkeit von der WP-Leistung - rein diagnostisch, "
        "zur Einordnung der Streuung dieses Kostenbestandteils. In die tatsächliche WP-Kostenfunktion "
        "(core.kostenfunktion.wp_kostenfunktion) fließt IBN nicht getrennt ein, sondern gemeinsam mit "
        "Listenpreis und Montage über einen einzigen Potenzfit (siehe Abschnitt 'Gesamtübersicht' unten, "
        "Fit 3, sowie Abschnitt 5, Montagekosten)."
    )
    y_label_ibn = "Inbetriebnahmekosten [€]" if not spezifisch else "Spez. IBN-Kosten [€/kW]"
    wp_ibn_gesamt = wp_regression_gesamt(wp_katalog, spezifisch, spalten=("ibn_kosten",))
    ibn_eintraege = [(
        "WP — Inbetriebnahmekosten (alle Hersteller)",
        lambda titel=None: einzelfigur_regression(
            wp_ibn_gesamt, x_label_wp, y_label_ibn, x_mathtext_wp, "#8B0000", funktions_praefix=sym_wp_ibn,
            titel=titel, legend_loc=legend_loc),
    )]
    _erfasse_tabelle("Alle Hersteller (gepoolt, IBN)", "-", wp_ibn_gesamt)
    _zeige_2spaltig(ibn_eintraege)

    st.markdown("### Speicher — je Hersteller und Material")
    sp_eintraege = []
    for name, g in sp_je_hersteller.items():
        farbe = sp_farben[name]
        anzeigename = f"{g.bezeichnung} ({g.material})"
        sp_eintraege.append((
            anzeigename,
            lambda titel=None, g=g, f=farbe: einzelfigur_regression(
                g, x_label_sp, y_label_sp, x_mathtext_sp, f, funktions_praefix=sym_sp_gesamt,
                titel=titel, legend_loc=legend_loc),
        ))
        _erfasse_tabelle(g.bezeichnung, g.material, g)
    _zeige_2spaltig(sp_eintraege)

    st.markdown("### Speicher — Wärmeverlust vs. Speichergröße")
    st.caption(
        "Bereitschaftsverlust q_sb,sto (aus dem katalogeigenen Warmhalteverlust je Modell, Gl. 7) in "
        "Abhängigkeit vom Speichervolumen - unabhängig von der oben gewählten Kostenbasis, je "
        "Material ein eigenes Diagramm. Zeigt, wie stark der Verlust materialabhängig degressiv mit "
        "der Speichergröße skaliert (vgl. Tabelle B.8 der Norm)."
    )
    sp_verlust_hersteller = speicher_verlust_je_hersteller(speicher_katalog)
    sp_verlust_material = speicher_verlust_je_material(speicher_katalog)
    verlust_linienfarben = {
        material: material_linienfarben_liste[i % len(material_linienfarben_liste)]
        for i, material in enumerate(sp_verlust_material.keys())
    }
    verlust_tabellen_zeilen = []
    for material, g in sp_verlust_material.items():
        if g.funktion is not None:
            verlust_tabellen_zeilen.append((
                "Alle Hersteller (gepoolt)", material, g.anzahl,
                g.funktion.koeffizient_a, g.funktion.exponent_b, g.funktion.r_quadrat,
            ))
    # Je Material ein eigenes Diagramm (statt beider Materialien in einer Achse):
    # die Punktwolken überlagern sich sonst, und die materialabhängige Degression
    # ist im direkten Nebeneinander besser ablesbar.
    verlust_eintraege = []
    for material, g_material in sp_verlust_material.items():
        punkte_material = {k: g for k, g in sp_verlust_hersteller.items() if g.material == material}
        if not punkte_material:
            continue
        funktion_material = (
            {material: g_material.funktion} if g_material.funktion is not None else {}
        )
        verlust_eintraege.append((
            f"Speicher — Wärmeverlust ({material}, alle Hersteller)",
            lambda titel=None, p=punkte_material, f=funktion_material: einzelfigur_verlust_kombiniert(
                p, sp_farben, f,
                x_label_sp, r"Bereitschaftsverlust $q_{sb,sto}$ [kWh/24h]", "V", verlust_linienfarben,
                titel=titel, legend_loc="upper left",
            ),
        ))
    _zeige_2spaltig(verlust_eintraege)

    st.markdown("### Gesamtübersicht (alle Hersteller)")

    def _wp_fit_kurve(f, _spezifisch=spezifisch):
        # Fit-Objekte sind stets auf absolute Kosten gefittet (core.kostenfunktion) - bei
        # "Spezifische Kosten" wird die Kurve für die Anzeige durch Φ geteilt, statt neu zu fitten.
        def kurve(x, _f=f, _spezifisch=_spezifisch):
            x = np.asarray(x, dtype=float)
            werte = _f(x)
            return werte / x if _spezifisch else werte
        return kurve

    def _r2_fuer_ansicht(gruppen: dict, kurve) -> float:
        # Die Kurve selbst ist unabhängig davon, ob durch Φ/V vor oder nach dem Fit geteilt wird
        # (log-log-Potenzfit ist unter dieser Transformation invariant), aber R² hängt von der
        # Skala ab, auf der es berechnet wird - hier konsistent auf der gerade angezeigten Skala
        # (absolut oder spezifisch), statt immer das R² des ursprünglichen (absoluten) Fits zu zeigen.
        gruppen_mit_daten = [g for g in gruppen.values() if len(g.x) > 0]
        if not gruppen_mit_daten:
            return float("nan")
        x = np.concatenate([g.x for g in gruppen_mit_daten])
        y = np.concatenate([g.y for g in gruppen_mit_daten])
        return bestimmtheitsmass(y, kurve(x))

    def _wp_fit_label(f, r2: float, praefix: str):
        return f"{funktions_label(praefix, x_mathtext_wp, f.koeffizient_a, f.exponent_b)}\nR² = {r2:.4f}"

    _wp_kurve1 = _wp_fit_kurve(wp_f1_diag) if wp_f1_diag is not None else None
    _wp_r2_1 = _r2_fuer_ansicht(wp_je_hersteller_fit1, _wp_kurve1) if wp_f1_diag is not None else float("nan")
    _label1 = _wp_fit_label(wp_f1_diag, _wp_r2_1, sym_wp_lp) if wp_f1_diag is not None else None
    _wp_kurve2 = _wp_fit_kurve(wp_f_diag) if wp_f_diag is not None else None
    _wp_r2_2 = _r2_fuer_ansicht(wp_je_hersteller_inkl_ibn, _wp_kurve2) if wp_f_diag is not None else float("nan")
    _label2 = _wp_fit_label(wp_f_diag, _wp_r2_2, sym_wp_lp_ibn) if wp_f_diag is not None else None
    _wp_kurve3 = _wp_fit_kurve(wp_f3_diag) if wp_f3_diag is not None else None
    _wp_r2_3 = _r2_fuer_ansicht(wp_je_hersteller_fit3, _wp_kurve3) if wp_f3_diag is not None else float("nan")
    _label3 = _wp_fit_label(wp_f3_diag, _wp_r2_3, sym_wp_gesamt) if wp_f3_diag is not None else None

    gesamt_eintraege = [
        (
            "WP — Listenpreis aller Hersteller (Fit 1: nur Listenpreis)",
            lambda titel=None: einzelfigur_kombiniert(
                wp_je_hersteller_fit1, wp_farben, _wp_kurve1, x_label_wp, y_label_wp_lp, x_mathtext_wp,
                linienfarbe="black", titel=titel, legend_loc=legend_loc, gesamt_label=_label1,
                funktions_praefix=sym_wp_lp,
            ),
        ),
        (
            "WP — Listenpreis aller Hersteller (Fit 2: inkl. IBN)",
            lambda titel=None: einzelfigur_kombiniert(
                wp_je_hersteller_inkl_ibn, wp_farben, _wp_kurve2, x_label_wp,
                y_label_wp_inkl_ibn, x_mathtext_wp,
                linienfarbe="black", titel=titel, legend_loc=legend_loc, gesamt_label=_label2,
                funktions_praefix=sym_wp_lp_ibn,
            ),
        ),
        (
            "WP — Listenpreis aller Hersteller (Fit 3: inkl. IBN + Montage — für Modus E/F)",
            lambda titel=None: einzelfigur_kombiniert(
                wp_je_hersteller_fit3, wp_farben, _wp_kurve3, x_label_wp,
                y_label_wp_inkl_ibn_montage, x_mathtext_wp,
                linienfarbe="black", titel=titel, legend_loc=legend_loc, gesamt_label=_label3,
                funktions_praefix=sym_wp_gesamt,
            ),
        ),
    ]
    if wp_f1_diag is not None:
        tabellen_zeilen.append((
            "Alle Hersteller (gepoolt, Fit 1: nur Listenpreis)", "-",
            wp_f1_diag.stuetzstellen, wp_f1_diag.koeffizient_a, wp_f1_diag.exponent_b, _wp_r2_1,
        ))
    if wp_f_diag is not None:
        tabellen_zeilen.append((
            "Alle Hersteller (gepoolt, Fit 2: inkl. IBN)", "-",
            wp_f_diag.stuetzstellen, wp_f_diag.koeffizient_a, wp_f_diag.exponent_b, _wp_r2_2,
        ))
    if wp_f3_diag is not None:
        tabellen_zeilen.append((
            "Alle Hersteller (gepoolt, Fit 3: inkl. IBN+Montage — für Modus E/F)", "-",
            wp_f3_diag.stuetzstellen, wp_f3_diag.koeffizient_a, wp_f3_diag.exponent_b, _wp_r2_3,
        ))

    sp_je_hersteller_ohne = speicher_regression_je_hersteller(speicher_katalog_ohne_montage, spezifisch)
    sp_je_material_ohne = speicher_regression_je_material(speicher_katalog_ohne_montage, spezifisch)

    for i, material in enumerate(sp_je_material.keys()):
        linienfarbe = material_linienfarben_liste[i % len(material_linienfarben_liste)]

        g_material_ohne = sp_je_material_ohne.get(material)
        if g_material_ohne is not None:
            punkte_ohne = {k: g for k, g in sp_je_hersteller_ohne.items() if g.material == material}
            farben_ohne = {k: sp_farben[k] for k in punkte_ohne}
            gesamt_eintraege.append((
                f"Speicher — alle Hersteller ({material}, ohne Montage)",
                lambda titel=None, p=punkte_ohne, f=farben_ohne, fn=g_material_ohne.funktion, lf=linienfarbe:
                einzelfigur_kombiniert(
                    p, f, fn, x_label_sp, y_label_sp_ohne, x_mathtext_sp, linienfarbe=lf, titel=titel,
                    legend_loc=legend_loc, funktions_praefix=sym_sp_nk,
                ),
            ))
            if g_material_ohne.funktion is not None:
                tabellen_zeilen.append((
                    "Alle Hersteller (gepoolt, ohne Montage)", material, g_material_ohne.anzahl,
                    g_material_ohne.funktion.koeffizient_a, g_material_ohne.funktion.exponent_b,
                    g_material_ohne.funktion.r_quadrat,
                ))

        # Zeigt exakt die Kostenfunktion, die core.kostenfunktion.speicher_kostenfunktion() für
        # Modus D/E/F tatsächlich verwendet: EIN Potenzfit auf die Investkosten inkl. Rabatt und
        # Montage-Prozentsatz (core/montage.py) - Diagramm und Berechnung stimmen damit exakt
        # überein. Der Montage-Prozentsatz wirkt rein multiplikativ auf die bereits rabattierten
        # Kosten, verschiebt also nur den Vorfaktor gegenüber "ohne Montage" oben, nicht den
        # Exponenten (siehe core.kostenfunktion.speicher_kostenfunktion).
        try:
            sp_f_diag = speicher_kostenfunktion(speicher_katalog, material=material)
        except KostenfunktionFehler:
            sp_f_diag = None

        punkte = {k: g for k, g in sp_je_hersteller.items() if g.material == material}
        farben = {k: sp_farben[k] for k in punkte}
        if sp_f_diag is not None:
            def _sp_kurve(x, _f=sp_f_diag, _spezifisch=spezifisch):
                x = np.asarray(x, dtype=float)
                werte = _f(x)
                return werte / x if _spezifisch else werte

            # R² auf der gerade angezeigten Skala (absolut oder spezifisch) statt immer auf dem
            # ursprünglichen (absoluten) Fit von speicher_kostenfunktion() - siehe _r2_fuer_ansicht.
            _r2_sp_montage = _r2_fuer_ansicht(punkte, _sp_kurve)
            _label_sp_montage = (
                f"{funktions_label(sym_sp_gesamt, x_mathtext_sp, sp_f_diag.koeffizient_a, sp_f_diag.exponent_b)}\n"
                f"R² = {_r2_sp_montage:.4f}"
            )
        else:
            _sp_kurve = None
            _label_sp_montage = None
            _r2_sp_montage = float("nan")
        gesamt_eintraege.append((
            f"Speicher — alle Hersteller ({material}, mit Montage)",
            lambda titel=None, p=punkte, f=farben, fn=_sp_kurve, lb=_label_sp_montage, lf=linienfarbe:
            einzelfigur_kombiniert(
                p, f, fn, x_label_sp, y_label_sp, x_mathtext_sp, linienfarbe=lf, titel=titel,
                legend_loc=legend_loc, gesamt_label=lb, funktions_praefix=sym_sp_gesamt,
            ),
        ))
        if sp_f_diag is not None:
            tabellen_zeilen.append((
                "Alle Hersteller (gepoolt, mit Montage)", material, sp_f_diag.stuetzstellen,
                sp_f_diag.koeffizient_a, sp_f_diag.exponent_b, _r2_sp_montage,
            ))
    _zeige_2spaltig(gesamt_eintraege)

    st.divider()
    pdf_buffer = io.BytesIO()
    with PdfPages(pdf_buffer) as pdf:
        deckblatt = plt.figure(figsize=(8.27, 11.69))
        deckblatt.text(0.5, 0.58, "Kostenregressionen", ha="center", size=20, weight="bold")
        deckblatt.text(0.5, 0.52, "Wärmepumpen und Speicher je Hersteller (und Material)", ha="center", size=12)
        deckblatt.text(0.5, 0.47, f"Kostenbasis: {ansicht}", ha="center", size=10)
        pdf.savefig(deckblatt)
        plt.close(deckblatt)

        tabelle = (
            "KOSTENFUNKTIONEN (Potenzfit Ĉ_I = x * Baugröße^y; x=Vorfaktor, y=Degressionsexponent)\n"
            + "-" * 78 + "\n"
            f"{'Gruppe':<28}{'Material':<18}{'n':>4}{'x':>12}{'y':>9}{'R²':>8}\n" + "-" * 78 + "\n"
        )
        for name, material, n, a, b, r2 in tabellen_zeilen:
            a_text = f"{a:,.2f}" if a == a else "-"
            b_text = f"{b:.4f}" if b == b else "-"
            r2_text = f"{r2:.4f}" if r2 == r2 else "-"
            tabelle += f"{name[:27]:<28}{material[:17]:<18}{n:>4}{a_text:>12}{b_text:>9}{r2_text:>8}\n"
        pdf_textseiten(pdf, tabelle, zeilen_pro_seite=50)

        if verlust_tabellen_zeilen:
            verlust_tabelle = (
                "WÄRMEVERLUSTFUNKTIONEN  q_sb,sto(V) = a * V^b [kWh/24h]\n" + "-" * 78 + "\n"
                f"{'Gruppe':<28}{'Material':<18}{'n':>4}{'a':>12}{'b':>9}{'R²':>8}\n" + "-" * 78 + "\n"
            )
            for name, material, n, a, b, r2 in verlust_tabellen_zeilen:
                verlust_tabelle += f"{name[:27]:<28}{material[:17]:<18}{n:>4}{a:>12,.4f}{b:>9.4f}{r2:>8.4f}\n"
            pdf_textseiten(pdf, verlust_tabelle, zeilen_pro_seite=50)

        for name, builder in pdf_eintraege:
            fig = builder(titel=name)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

    st.download_button(
        "📚 Sammel-PDF: alle Kostenregressionen + Funktionstabelle",
        data=pdf_buffer.getvalue(), file_name=f"kostenregressionen_{key_prefix}.pdf",
        mime="application/pdf", key=f"dl_sammel_{key_prefix}",
    )


# Wie ein hinterlegter Fall in der Oberfläche heißt und wozu er weiterverwendet wird.
FALL_TITEL = {
    FALL_NORM: ("Norm-Fall",
                "wird in Modus C verglichen und ist in Modus E der Ausgangszustand"),
    FALL_NORM_SOLL: ("Norm-Soll-Fall",
                     "wird in Modus E im Kostenvergleich mitgeführt"),
    FALL_MONITORING: ("Monitoring-Fall",
                      "wird in Modus C mit genau diesen Eingaben verglichen"),
}


def zeige_einzelergebnis(
    zapfprofil, ergebnis, tagesvolumen, quelle_label, ist_monitoring: bool = False,
    *, key_prefix: str = "ergebnis", fall_hinterlegen: bool = True,
    gleichgewicht_hinweis: bool = True, wochenpruefung_folgt: bool = False,
    fall_schluessel: str | None = None,
):
    """Kennzahlen, Diagramme und Ergebnisprotokoll eines gerechneten Laufs.

    `key_prefix` trennt die Streamlit-Widget-Schlüssel, wenn auf derselben Seite
    mehrere Läufe dargestellt werden (Modus A: Auslegungstag + Wochenprüfung).
    `fall_hinterlegen=False` unterdrückt das Hinterlegen für Modus C - dort wird
    immer der Auslegungstag verglichen, nicht die Wochenvariante.
    `fall_schluessel` legt fest, unter welchem Fall der Lauf abgelegt wird;
    ohne Angabe entscheidet `ist_monitoring` zwischen Norm- und Monitoring-Fall.
    """
    gesamtlaufzeit = sum(z.dauer_min for z in ergebnis.zyklen)
    min_soc = ergebnis.ladezustand.min()
    dauer_tage = max(1, len(zapfprofil) // MINUTEN_PRO_TAG)
    volumen_label = "Wochenvolumen" if dauer_tage > 1 else "Tagesvolumen V_W,day"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(volumen_label, f"{tagesvolumen:,.0f} l")
    col2.metric("Q_sto,max", f"{ergebnis.q_sto_max:.1f} kWh")
    col3.metric("WP-Einschaltungen", f"{len(ergebnis.zyklen)}")
    col4.metric("WP-Gesamtlaufzeit", f"{gesamtlaufzeit} min")

    if min_soc < ergebnis.q_sto_min:
        kritischer_tag = f" (Tag {int(ergebnis.ladezustand.argmin()) // MINUTEN_PRO_TAG + 1} des Auslegungszeitraums)" \
            if dauer_tage > 1 else ""
        st.warning(
            f"⚠️ Nach Norm-Kriterium (6.4.3.3) unterdimensioniert: minimaler Ladezustand "
            f"{min_soc:.1f} kWh fällt unter Q_sto,min = {ergebnis.q_sto_min:.1f} kWh{kritischer_tag}. "
            "Speichervolumen oder Erzeugerleistung erhöhen."
        )
    if gleichgewicht_hinweis and ergebnis.ladezustand_ende < ergebnis.q_sto_max * 0.95:
        zeitraum_text = f"über den gesamten Auslegungszeitraum ({dauer_tage} Tage)" if dauer_tage > 1 else "über 24 h"
        hinweis = (
            f"ℹ️ Speicher ist am Ende des Auslegungszeitraums nicht vollständig geladen "
            f"({ergebnis.ladezustand_ende:.1f} von {ergebnis.q_sto_max:.1f} kWh) — "
            f"die Anlage läuft {zeitraum_text} nicht im Gleichgewicht."
        )
        if wochenpruefung_folgt:
            # Die entnahmearme Zeit beginnt erst nach dem Auslegungstag - ob sich das
            # Defizit über die Folgetage ausgleicht, beantwortet erst die Wochenprüfung.
            hinweis += " Ob sich das über die Folgetage ausgleicht, zeigt die **Wochenprüfung** unten."
        st.info(hinweis)

    farbe_zapfprofil = FARBE_ZAPFPROFIL_MONITORING if ist_monitoring else FARBE_ZAPFPROFIL_NORM
    fig = plot_ergebnis(zapfprofil, ergebnis, farbe_zapfprofil=farbe_zapfprofil)
    st.pyplot(fig)
    fig_ohne_titel = plot_ergebnis(zapfprofil, ergebnis, titel=False, farbe_zapfprofil=farbe_zapfprofil)
    einzelplot_downloads(
        einzelfiguren_ergebnis(zapfprofil, ergebnis, farbe_zapfprofil=farbe_zapfprofil),
        PANEL_ERGEBNIS, key_prefix)

    protokoll = f"""TWW-AUSLEGUNG NACH ÖNORM EN 12831-3
{'=' * 60}
{NORMWERTE_PROTOKOLLZEILE}
Modus                         : {modus}
Speichertyp                   : {daten.speicher_typ}
Datenquelle Zapfprofil        : {quelle_label}
Auslegungszeitraum            : {dauer_tage} Tag{'e' if dauer_tage != 1 else ''}
{volumen_label:<30}: {tagesvolumen:,.1f} l

Q_sto,max                     : {ergebnis.q_sto_max:.2f} kWh
Q_sto,ON                      : {ergebnis.q_sto_on:.2f} kWh
Q_sto,min                     : {ergebnis.q_sto_min:.2f} kWh
Minimaler Ladezustand (SOC)   : {min_soc:.2f} kWh
Ladezustand am Ende           : {ergebnis.ladezustand_ende:.2f} kWh

WP-Einschaltungen             : {len(ergebnis.zyklen)}
WP-Gesamtlaufzeit             : {gesamtlaufzeit} min
"""
    if dauer_tage > 1:
        # Tagesweise Aufschlüsselung: zeigt, ob der Speicher den Ladezustand über
        # die Folgetage aufholt oder das Defizit von Tag zu Tag größer wird.
        kopf = (f"{'Tag':>3} | {'Zapfvolumen [l]':>15} | {'SOC_min [kWh]':>13} | "
                f"{'SOC Ende [kWh]':>14} | {'Einschaltungen':>14} | {'Laufzeit [min]':>14}")
        zeilen = [kopf, "-" * len(kopf)]
        for t in tagesauswertung(zapfprofil, ergebnis):
            zeilen.append(
                f"{t.tag:>3} | {t.zapfvolumen_l:>15,.1f} | {t.soc_min:>13.2f} | "
                f"{t.soc_ende:>14.2f} | {t.zyklen:>14} | {t.laufzeit_min:>14}"
            )
        protokoll += "\nTAGESWEISE AUSWERTUNG\n" + "-" * len(kopf) + "\n" + "\n".join(zeilen) + "\n"

    parameter = aktueller_parametersatz(ist_monitoring=ist_monitoring, quelle_label=quelle_label)
    protokoll += "\n" + eingabeparameter_block(parameter)
    st.text_area("Ergebnisprotokoll", protokoll, height=280, key=f"protokoll_{key_prefix}")

    if not fall_hinterlegen:
        return fig, fig_ohne_titel, protokoll

    # Fall mit seinem eigenen Parametersatz für den Vergleich in Modus C hinterlegen.
    # Jeder Neulauf überschreibt den jeweiligen Fall, sodass in Modus C immer der
    # zuletzt in Modus A bzw. B gerechnete Stand verglichen wird.
    schluessel = fall_schluessel or (FALL_MONITORING if ist_monitoring else FALL_NORM)
    hinterlege_fall(
        schluessel,
        GespeicherterFall(
            modus=modus, daten=daten, zapfprofil=zapfprofil, ergebnis=ergebnis,
            quelle_label=quelle_label, parameter=parameter, volumen_l=tagesvolumen,
            zeitstempel=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            anzahl_tage=dauer_tage, warnungen=list(warnliste) if ist_monitoring else [],
        ),
    )
    bezeichnung, verwendung = FALL_TITEL[schluessel]
    st.caption(f"💾 Als **{bezeichnung}** hinterlegt — {verwendung}.")
    return fig, fig_ohne_titel, protokoll


if braucht_norm_eingabe and daten.tagesbedarf_methode == "C":
    eq = aequivalente_personen(daten)
    with st.expander("Tagesbedarf über die äquivalente Personenanzahl (Anhang B.2.2)", expanded=True):
        gl_max = "Gl. B.3" if daten.wohnungstyp == GEBAEUDETYP_WOHNUNG else "Gl. B.1"
        gl_eq = "Gl. B.4" if daten.wohnungstyp == GEBAEUDETYP_WOHNUNG else "Gl. B.2"
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"n_P,eq,max je Einheit ({gl_max})", f"{eq.n_p_eq_max:.2f}")
        c2.metric(f"n_P,eq je Einheit ({gl_eq})", f"{eq.n_p_eq:.2f}")
        c3.metric("n_P,eq gesamt", f"{eq.n_p_eq_gesamt:.2f}")
        c4.metric("V_W,P,day (Gl. B.5)", f"{eq.v_w_p_day:.2f} l/(P·d)")
        flaechenbezogen = daten.y_spez_volumen * daten.wohnflaeche / eq.n_p_eq
        st.caption(
            rf"Gl. B.5: $V_{{W,P,day}} = \min(x;\ y \cdot A_h / n_{{P,eq}})$ = "
            rf"min({daten.x_max_spez_volumen:.2f}; {flaechenbezogen:.2f}) = {eq.v_w_p_day:.2f} l/(Person·d)"
            + (" — die Obergrenze $x$ ist maßgebend." if eq.x_greift
               else " — der flächenbezogene Term ist maßgebend.")
        )
        st.caption(
            rf"Gl. 20: $V_{{W,day}} = V_{{W,P,day}} \cdot n_{{P,eq}}$ = "
            rf"{eq.v_w_p_day:.2f} · {eq.n_p_eq_gesamt:.2f} = **{eq.v_w_day:,.0f} l/d**"
        )

if ist_norm_zustand or ist_norm_soll:
    # Modus A und A2 rechnen identisch - dieselben Norm-Eingangsgrößen, dasselbe
    # Verfahren, dieselbe Wochenprüfung. Der Unterschied liegt allein darin, was
    # die Anlage darstellt: in A die real vorhandene, in A2 die vom Anwender
    # selbst dimensionierte. Nur so sind die beiden Zustände vergleichbar.
    if ist_norm_soll:
        # Rückmeldung für die Iteration von Hand: Wie viel Luft bleibt bis zum
        # Norm-Kriterium? Die Warnung bei Unterdimensionierung kommt zusätzlich
        # aus zeige_einzelergebnis().
        reserve = float(ergebnis_soll.ladezustand.min()) - ergebnis_soll.q_sto_min
        st.subheader("🎯 Norm-Soll-Zustand — eigene Dimensionierung")
        s1, s2, s3 = st.columns(3)
        s1.metric("Speichervolumen V_sto", f"{daten.v_sto:,.0f} l")
        s2.metric("Erzeugerleistung Φ_N", f"{daten.phi_n:.1f} kW")
        s3.metric("Reserve zum Norm-Kriterium", f"{reserve:+.1f} kWh",
                  help="SOC_min − Q_sto,min. Positiv = Auslegung hält, negativ = "
                       "unterdimensioniert. Je näher an 0, desto knapper dimensioniert.")
        st.caption(
            "V_sto und Φ_N links in der Sidebar verändern und das Ergebnis erneut ablesen — "
            "so lange, bis die Auslegung passt. Die reale Anlage aus Modus A bleibt unberührt; "
            "beide Zustände stehen anschließend im Kostenvergleich in Modus E nebeneinander."
        )

    fig, fig_ohne_titel, protokoll = zeige_einzelergebnis(
        zapf_soll, ergebnis_soll, tagesvolumen_liter(daten), daten.gewaehltes_profil,
        ist_monitoring=False, wochenpruefung_folgt=True,
        fall_schluessel=FALL_NORM_SOLL if ist_norm_soll else FALL_NORM)

    # ----------------------------------------------------------------------
    # Wochenprüfung: derselbe Normtag 7x hintereinander
    #
    # Das Norm-Lastprofil endet um Mitternacht, die entnahmearme Zeit beginnt
    # aber erst danach. Ein am Ende des Auslegungstages nicht voll geladener
    # Speicher ist deshalb nicht zwingend unterdimensioniert - er kann den
    # Ladezustand über die Folgetage aufholen. Geprüft wird das hier mit
    # demselben Verfahren (Abschnitt 6.4.3.3) über sieben aneinandergehängte
    # Normtage. Hinterlegt für Modus C bleibt der Auslegungstag.
    # ----------------------------------------------------------------------
    TAGE_WOCHE = 7
    st.divider()
    st.subheader("🗓️ Wochenprüfung — Normtag 7× wiederholt")

    zapf_woche = np.tile(zapf_soll[:MINUTEN_PRO_TAG], TAGE_WOCHE)
    ergebnis_woche = berechne_versorgungskennlinie(daten, zapf_woche)
    tage_woche = tagesauswertung(zapf_woche, ergebnis_woche)
    erster_tag, letzter_tag = tage_woche[0], tage_woche[-1]
    voll_geladen = ergebnis_woche.ladezustand_ende >= ergebnis_woche.q_sto_max * 0.95
    soc_min_woche = float(ergebnis_woche.ladezustand.min())
    # Maßgeblich ist der Trend des TÄGLICHEN Tiefstwerts: er zeigt, ob sich über die
    # Woche ein Defizit aufbaut. Der Ladezustand am Tagesende schwankt dagegen je
    # nachdem, ob um Mitternacht gerade ein Ladezyklus läuft, und wäre als
    # Vergleich Tag 1 gegen Tag 7 irreführend.
    trend_soc_min = letzter_tag.soc_min - erster_tag.soc_min
    stabiler_tageszyklus = abs(trend_soc_min) < 0.01 * ergebnis_woche.q_sto_max
    soc_ende_spanne = (min(t.soc_ende for t in tage_woche), max(t.soc_ende for t in tage_woche))

    st.caption(
        "Derselbe Normtag (Anhang B.1) siebenmal hintereinander, mit unverändertem "
        "Verfahren nach Abschnitt 6.4.3.3 durchgerechnet. Sinn der Prüfung: Der "
        "Auslegungstag endet um Mitternacht, die entnahmearme Zeit beginnt erst danach — "
        "ein am Tagesende nicht voll geladener Speicher kann über die Folgetage aufholen. "
        "Für den Vergleich in Modus C bleibt der Auslegungstag (24 h) maßgebend."
    )

    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Ladezustand Ende Tag 7", f"{ergebnis_woche.ladezustand_ende:.1f} kWh",
              f"{ergebnis_woche.ladezustand_ende - erster_tag.soc_ende:+.1f} kWh ggü. Tag 1")
    w2.metric("Tiefster SOC der Woche", f"{soc_min_woche:.1f} kWh",
              f"{trend_soc_min:+.1f} kWh Tag 1 → Tag {TAGE_WOCHE}")
    w3.metric("WP-Einschaltungen (7 d)", f"{len(ergebnis_woche.zyklen)}",
              f"{len(ergebnis_woche.zyklen) / TAGE_WOCHE:.1f} pro Tag")
    w4.metric("WP-Laufzeit (7 d)", f"{sum(z.dauer_min for z in ergebnis_woche.zyklen)} min",
              f"{sum(z.dauer_min for z in ergebnis_woche.zyklen) / TAGE_WOCHE:.0f} min pro Tag")

    if soc_min_woche < ergebnis_woche.q_sto_min:
        st.warning(
            f"⚠️ Auch über sieben Tage unterdimensioniert: der tiefste Ladezustand "
            f"{soc_min_woche:.1f} kWh bleibt unter Q_sto,min = {ergebnis_woche.q_sto_min:.1f} kWh."
        )
    elif voll_geladen:
        st.success(
            f"✅ Der Speicher erreicht am Ende der Woche wieder {ergebnis_woche.ladezustand_ende:.1f} von "
            f"{ergebnis_woche.q_sto_max:.1f} kWh (≥ 95 %). Das Defizit am Ende des einzelnen "
            "Auslegungstages wird über die entnahmearmen Zeiten der Folgetage ausgeglichen."
        )
    elif stabiler_tageszyklus:
        st.success(
            f"✅ Stabiler Tageszyklus: Der tiefste Ladezustand liegt an Tag {TAGE_WOCHE} bei "
            f"{letzter_tag.soc_min:.1f} kWh und damit praktisch unverändert gegenüber Tag 1 "
            f"({erster_tag.soc_min:.1f} kWh, Δ {trend_soc_min:+.1f} kWh). Über die Woche baut sich "
            "also kein Defizit auf — dass der Speicher am Ende des einzelnen Auslegungstages nicht "
            f"voll ist, ist damit unkritisch. Der Ladezustand zum Tageswechsel pendelt zwischen "
            f"{soc_ende_spanne[0]:.1f} und {soc_ende_spanne[1]:.1f} kWh, je nachdem ob um Mitternacht "
            "gerade ein Ladezyklus läuft."
        )
    elif trend_soc_min > 0:
        st.info(
            f"ℹ️ Der tiefste Ladezustand steigt über die Woche von {erster_tag.soc_min:.1f} auf "
            f"{letzter_tag.soc_min:.1f} kWh — die Anlage holt auf, hat den eingeschwungenen Zustand "
            "nach sieben Tagen aber noch nicht erreicht."
        )
    else:
        st.warning(
            f"⚠️ Der tiefste Ladezustand sinkt über die Woche von {erster_tag.soc_min:.1f} auf "
            f"{letzter_tag.soc_min:.1f} kWh — das Defizit summiert sich von Tag zu Tag auf, die "
            "entnahmearmen Zeiten reichen zur Regeneration nicht aus."
        )

    st.markdown("**Tagesweise Auswertung**")
    st.table({
        "Tag": [f"{t.tag}" for t in tage_woche],
        "Zapfvolumen [l]": [f"{t.zapfvolumen_l:,.0f}" for t in tage_woche],
        "SOC_min [kWh]": [f"{t.soc_min:.1f}" for t in tage_woche],
        "SOC Tagesende [kWh]": [f"{t.soc_ende:.1f}" for t in tage_woche],
        "Einschaltungen": [f"{t.zyklen}" for t in tage_woche],
        "Laufzeit [min]": [f"{t.laufzeit_min}" for t in tage_woche],
    })

    zeige_einzelergebnis(
        zapf_woche, ergebnis_woche, tagesvolumen_liter(daten) * TAGE_WOCHE,
        f"{daten.gewaehltes_profil} ({TAGE_WOCHE}× wiederholter Normtag)",
        ist_monitoring=False, key_prefix="ergebnis_woche", fall_hinterlegen=False,
        # Der Gleichgewichts-Hinweis ist hier bereits oben differenziert beantwortet
        # (stabiler Tageszyklus vs. anwachsendes Defizit) und würde dem widersprechen.
        gleichgewicht_hinweis=False,
    )

elif modus.startswith("B"):
    fig, fig_ohne_titel, protokoll = zeige_einzelergebnis(
        zapf_ist, ergebnis_ist, float(zapf_ist.sum()), monitoring_quelle_label, ist_monitoring=True)

elif modus.startswith("C"):  # Vergleich der beiden hinterlegten Fälle
    fall_norm, fall_mon = geholter_fall(FALL_NORM), geholter_fall(FALL_MONITORING)
    if fall_norm is None or fall_mon is None:
        fehlend = []
        if fall_norm is None:
            fehlend.append("**Modus A** rechnen (Normauslegung mit geschätzten Verlusten)")
        if fall_mon is None:
            fehlend.append("**Modus B** rechnen (Monitoring-Datei laden, ggf. gemessenen Verlustwert setzen)")
        st.info(
            "Modus C vergleicht die in Modus A und B gerechneten Fälle — jeden mit seinen "
            "eigenen Eingaben. Noch offen: " + " und ".join(fehlend) + ". "
            "Beide Fälle werden beim Rechnen automatisch hinterlegt und bleiben erhalten, "
            "solange die App läuft."
        )
        st.stop()

    zapf_soll, ergebnis_soll = fall_norm.zapfprofil, fall_norm.ergebnis
    zapf_ist, ergebnis_ist = fall_mon.zapfprofil, fall_mon.ergebnis
    dauer_tage_c = fall_mon.anzahl_tage
    normtag_wiederholt = False
    if fall_norm.anzahl_tage != dauer_tage_c:
        # Der Norm-Fall aus Modus A umfasst immer einen Normtag. Für den Vergleich
        # mit einer Monitoring-Woche wird er - wie bisher - als "typische Woche"
        # wiederholt und mit den Parametern des Norm-Falls neu durchgerechnet.
        zapf_soll = np.tile(fall_norm.zapfprofil[:MINUTEN_PRO_TAG], dauer_tage_c)
        ergebnis_soll = berechne_versorgungskennlinie(fall_norm.daten, zapf_soll)
        normtag_wiederholt = True

    v = vergleiche(zapf_soll, ergebnis_soll, zapf_ist, ergebnis_ist,
                   fall_norm.daten, fall_mon.daten)
    zeitraum_label_c = f"Volumen Soll (Norm x{dauer_tage_c})" if dauer_tage_c > 1 else "Tagesvolumen Soll (Norm)"

    st.caption(
        f"**Norm-Fall** gerechnet {fall_norm.zeitstempel} · {fall_norm.quelle_label}  \n"
        f"**Monitoring-Fall** gerechnet {fall_mon.zeitstempel} · {fall_mon.quelle_label}"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric(zeitraum_label_c, f"{v.vol_soll:,.0f} l")
    col2.metric("Volumen Ist (Monitoring)", f"{v.vol_ist:,.0f} l", f"{v.diff_vol_pct:+.1f} %")
    col3.metric("Q_sto,min (Anlage)", f"{v.q_sto_min:.1f} kWh")
    if normtag_wiederholt:
        st.caption(
            f"Wochenanalyse: Norm-Lastprofil wird als {dauer_tage_c}-fach wiederholter Normtag "
            "als Vergleichsbasis herangezogen (mit den Parametern des Norm-Falls neu gerechnet)."
        )

    st.subheader("Gegenüberstellung der Anlagen-Performance")
    st.table({
        "KPI": [
            "Gesamt-Energiebedarf [kWh]", "WP-Gesamtlaufzeit [min]",
            "WP-Einschaltzyklen", "Tiefster Ladezustand SOC_min [kWh]",
        ],
        "Norm (Soll)": [
            f"{v.energie_soll:.2f}", f"{v.laufzeit_soll_min}",
            f"{v.zyklen_soll}", f"{v.soc_min_soll:.2f}",
        ],
        "Monitoring (Ist)": [
            f"{v.energie_ist:.2f}", f"{v.laufzeit_ist_min}",
            f"{v.zyklen_ist}", f"{v.soc_min_ist:.2f}",
        ],
        "Abweichung": [
            f"{v.diff_energie_pct:+.1f} %", f"{v.laufzeit_ist_min - v.laufzeit_soll_min:+d}",
            f"{v.zyklen_ist - v.zyklen_soll:+d}", f"{v.soc_min_ist - v.soc_min_soll:+.2f}",
        ],
    })

    # --- Wärmeverluste beider Fälle gegenüberstellen ----------------------
    # Der Energiebedarf oben ist die Zapfenergie nach Gl. 1 und enthält die
    # Verluste nicht - die gehen minutenweise über den Ladezustand ein und
    # schlagen sich in Laufzeit, Zyklen und SOC_min nieder. Diese Tabelle macht
    # sichtbar, wie weit die Norm-Schätzung (Gl. 6/9) und der gemessene
    # Summenverlust auseinanderliegen.
    verlust_zeilen_c = verlustzeilen(v)
    if verlust_zeilen_c:
        st.subheader("Gegenüberstellung der Wärmeverluste")
        st.caption(
            "Der Gesamt-Energiebedarf oben ist die reine Zapfenergie (Gl. 1) und enthält diese "
            "Verluste nicht — sie werden in der Simulation minutenweise vom Ladezustand abgezogen "
            "(Gl. 6 Speicher, Gl. 9 Verteilung bzw. gemessener Summenwert)."
        )
        st.table({
            "Wärmeverlust": [z[0] for z in verlust_zeilen_c],
            "Norm (Soll)": [z[1] for z in verlust_zeilen_c],
            "Monitoring (Ist)": [z[2] for z in verlust_zeilen_c],
            "Abweichung": [z[3] for z in verlust_zeilen_c],
        })

    for w in v.warnungen:
        st.warning(f"⚠️ {w}")

    # --- Eingaben beider Fälle gegenüberstellen ---------------------------
    TITEL_NORM, TITEL_MON = "Norm-Fall (Modus A)", "Monitoring-Fall (Modus B)"
    parameter_abschnitte = vergleiche_parametersaetze(fall_norm.parameter, fall_mon.parameter)
    abweichende = unterschiede(parameter_abschnitte)

    st.subheader("Eingangs- und Anlagenparameter je Fall")
    nur_abweichende = st.checkbox(
        "Nur abweichende Parameter zeigen", value=False, key="c_nur_abweichende",
    )
    st.caption(
        f"{len(abweichende)} von {len(sichtbare_zeilen(parameter_abschnitte))} Parametern "
        "unterscheiden sich zwischen den beiden Fällen (▲ markiert)."
    )
    sichtbar = sichtbare_zeilen(parameter_abschnitte, nur_unterschiede=nur_abweichende)
    st.table({
        "Abschnitt": [titel for titel, _ in sichtbar],
        "Parameter": [z.name for _, z in sichtbar],
        TITEL_NORM: [z.links for _, z in sichtbar],
        TITEL_MON: [z.rechts for _, z in sichtbar],
        "": ["▲" if z.unterschiedlich else "" for _, z in sichtbar],
    })

    # Unterschiede beim Zapfprofil (Norm vs. Messung) und beim Verlustansatz
    # (Schätzung nach Gl. 6/9 vs. Messwert) sind der Zweck dieses Vergleichs.
    # Abweichende Anlagen- oder Temperaturwerte beschreiben dagegen zwei
    # verschiedene Anlagen und machen die Kennwerte nur bedingt vergleichbar.
    anlagenabweichungen = [
        z.name for titel in (ABSCHNITT_ANLAGE, ABSCHNITT_TEMPERATUREN)
        for z in parameter_abschnitte.get(titel, []) if z.unterschiedlich
    ]
    if anlagenabweichungen:
        st.warning(
            "⚠️ Die beiden Fälle wurden mit unterschiedlichen Anlagenparametern gerechnet: "
            + ", ".join(anlagenabweichungen) + ". Die Kennwerte vergleichen damit nicht mehr "
            "dieselbe Anlage unter zwei Lastprofilen. Betroffenen Fall in Modus A bzw. B mit "
            "den gleichen Anlagenwerten neu rechnen, falls das nicht beabsichtigt ist."
        )

    fig = plot_vergleich(zapf_soll, ergebnis_soll, zapf_ist, ergebnis_ist)
    st.pyplot(fig)
    fig_ohne_titel = plot_vergleich(zapf_soll, ergebnis_soll, zapf_ist, ergebnis_ist, titel=False)
    einzelplot_downloads(
        einzelfiguren_vergleich(zapf_soll, ergebnis_soll, zapf_ist, ergebnis_ist),
        PANEL_VERGLEICH, "vergleich",
    )

    protokoll = f"""VERGLEICH NORM (SOLL) VS. MONITORING (IST) — ÖNORM EN 12831-3
{'=' * 70}
{NORMWERTE_PROTOKOLLZEILE}
Verglichen werden die in Modus A und Modus B gerechneten Fälle, jeder mit dem
Parametersatz, mit dem er tatsächlich gerechnet wurde (siehe Gegenüberstellung
am Ende des Protokolls).

Norm-Fall (Modus A)           : gerechnet {fall_norm.zeitstempel}
  Datenquelle Zapfprofil      : {fall_norm.quelle_label}
Monitoring-Fall (Modus B)     : gerechnet {fall_mon.zeitstempel}
  Datenquelle Zapfprofil      : {fall_mon.quelle_label}
Auslegungszeitraum            : {dauer_tage_c} Tag{'e' if dauer_tage_c != 1 else ''}\
{chr(10) + '  (Norm-Lastprofil als ' + str(dauer_tage_c) + '-fach wiederholter Normtag angesetzt)' if normtag_wiederholt else ''}

KPI                            | Norm (Soll)   | Monitoring (Ist) | Abweichung
--------------------------------------------------------------------------------
Zapfvolumen [l]                | {v.vol_soll:>12.1f} | {v.vol_ist:>16.1f} | {v.diff_vol_pct:>+9.1f} %
Gesamt-Energiebedarf [kWh]     | {v.energie_soll:>12.2f} | {v.energie_ist:>16.2f} | {v.diff_energie_pct:>+9.1f} %
WP-Gesamtlaufzeit [min]        | {v.laufzeit_soll_min:>12} | {v.laufzeit_ist_min:>16} | {v.laufzeit_ist_min - v.laufzeit_soll_min:>+9}
WP-Einschaltzyklen             | {v.zyklen_soll:>12} | {v.zyklen_ist:>16} | {v.zyklen_ist - v.zyklen_soll:>+9}
Tiefster Ladezustand [kWh]     | {v.soc_min_soll:>12.2f} | {v.soc_min_ist:>16.2f} | {v.soc_min_ist - v.soc_min_soll:>+9.2f}

Der Gesamt-Energiebedarf ist die reine Zapfenergie nach Gl. 1; die Wärmeverluste
sind darin nicht enthalten, sondern werden in der Simulation minutenweise vom
Ladezustand abgezogen und wirken damit auf Laufzeit, Zyklen und SOC_min.
"""
    if verlust_zeilen_c:
        protokoll += (
            "\nWÄRMEVERLUSTE JE FALL\n"
            + verlusttabelle_text(v) + "\n"
        )
    if v.warnungen:
        protokoll += "\n" + "\n".join(v.warnungen) + "\n"
    if anlagenabweichungen:
        protokoll += (
            "\nHINWEIS: Die Fälle wurden mit unterschiedlichen Anlagenparametern gerechnet "
            f"({', '.join(anlagenabweichungen)}).\n"
        )
    protokoll += (
        "\n\nEINGANGS- UND ANLAGENPARAMETER JE FALL (wie in die Berechnung eingeflossen)\n"
        + "-" * 70 + "\n"
        + vergleichstabelle_text(parameter_abschnitte, TITEL_NORM, TITEL_MON)
    )
    st.text_area("Ergebnisprotokoll", protokoll, height=320)

elif modus.startswith("D"):  # Investitionsoptimierung
    zapfprofil_basis = zapf_soll if investitions_basis == "Norm-Lastprofil" else zapf_ist

    if wp_katalog is None or speicher_katalog is None:
        st.info("Bitte WP-Katalog und Speicher-Katalog (Excel) hochladen.")
        st.stop()
    if wp_katalog.empty or speicher_katalog.empty:
        st.warning("⚠️ Bitte mindestens einen WP- und einen Speicher-Hersteller in der Hersteller-Auswahl aktivieren.")
        st.stop()

    zeige_kostenregressionen(wp_katalog, speicher_katalog, key_prefix="d", speicher_katalog_ohne_montage=speicher_katalog_ohne_montage)
    st.divider()

    material = None if material_wahl == "Alle" else material_wahl
    try:
        kombinationen = optimiere(daten, zapfprofil_basis, wp_katalog, speicher_katalog, material=material)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    beste = guenstigste_zulaessige(kombinationen)
    anzahl_zulaessig = sum(1 for k in kombinationen if k.zulaessig)

    col1, col2, col3 = st.columns(3)
    col1.metric("Geprüfte Kombinationen", f"{len(kombinationen)}")
    col2.metric("Davon zulässig", f"{anzahl_zulaessig}")
    col3.metric("Günstigste Investkosten", f"{beste.gesamtkosten:,.0f} €" if beste else "—")

    if beste is None:
        st.warning(
            "⚠️ Keine Kombination aus den hochgeladenen Katalogen erfüllt das Norm-Kriterium "
            "(SOC_min ≥ Q_sto,min). Größere WP-Modelle oder Speicher hinzufügen."
        )
    else:
        st.success(
            f"Günstigste zulässige Kombination: **{beste.wp_hersteller} {beste.wp_produkt}** "
            f"({beste.wp_leistung_kw:.1f} kW, {beste.wp_kosten:,.0f} €) + "
            f"**{beste.speicher_hersteller} {beste.speicher_produkt}** "
            f"({beste.speicher_volumen_l:.0f} l, {beste.speicher_material}, {beste.speicher_kosten:,.0f} €) "
            f"= **{beste.gesamtkosten:,.0f} €** gesamt."
        )

    st.subheader("Top 10 zulässige Kombinationen (nach Investkosten)")
    top10 = [k for k in kombinationen if k.zulaessig][:10]
    if top10:
        st.table({
            "WP": [f"{k.wp_hersteller} {k.wp_produkt} ({k.wp_leistung_kw:.1f} kW)" for k in top10],
            "Speicher": [f"{k.speicher_hersteller} {k.speicher_produkt} ({k.speicher_volumen_l:.0f} l, {k.speicher_material})" for k in top10],
            "WP-Kosten [€]": [f"{k.wp_kosten:,.0f}" for k in top10],
            "Speicher-Kosten [€]": [f"{k.speicher_kosten:,.0f}" for k in top10],
            "Gesamtkosten [€]": [f"{k.gesamtkosten:,.0f}" for k in top10],
            "Zyklen": [f"{k.zyklen}" for k in top10],
        })

    fig = plot_investitionsoptimierung(kombinationen)
    st.pyplot(fig)
    fig_ohne_titel = plot_investitionsoptimierung(kombinationen, titel=False)
    _buf_d = io.BytesIO()
    fig_ohne_titel.savefig(_buf_d, format="pdf", bbox_inches="tight")
    st.download_button("📄 Diagramm ohne Titel als PDF exportieren", data=_buf_d.getvalue(),
                        file_name="investitionsoptimierung.pdf", mime="application/pdf", key="dl_d_ohne_titel")

    protokoll = f"""INVESTITIONSOPTIMIERUNG WP + SPEICHER — ÖNORM EN 12831-3
{'=' * 70}
{NORMWERTE_PROTOKOLLZEILE}
Lastprofil-Basis               : {investitions_basis}
Speichertyp                    : {daten.speicher_typ}
Speicher-Material (Filter)     : {material_wahl}
Geprüfte Kombinationen         : {len(kombinationen)}
Davon zulässig (Norm-Kriterium): {anzahl_zulaessig}
"""
    if beste is not None:
        protokoll += f"""
GÜNSTIGSTE ZULÄSSIGE KOMBINATION
--------------------------------------------------------------------------------
Wärmepumpe   : {beste.wp_hersteller} {beste.wp_produkt} — {beste.wp_leistung_kw:.1f} kW, {beste.wp_kosten:,.2f} €
Speicher     : {beste.speicher_hersteller} {beste.speicher_produkt} — {beste.speicher_volumen_l:.0f} l, {beste.speicher_material}, {beste.speicher_kosten:,.2f} €
Gesamtkosten : {beste.gesamtkosten:,.2f} €
SOC_min      : {beste.soc_min_kwh:.2f} kWh (Q_sto,min = {beste.q_sto_min_kwh:.2f} kWh)
WP-Zyklen    : {beste.zyklen} | Laufzeit: {beste.laufzeit_min} min
"""
    protokoll += "\n" + eingabeparameter_block()
    st.text_area("Ergebnisprotokoll", protokoll, height=320)

elif modus.startswith("E"):  # Modus E: Optimierung über Kostenfunktionen
    zapfprofil_basis = zapf_soll if investitions_basis == "Norm-Lastprofil" else zapf_ist

    if wp_katalog is None or speicher_katalog is None:
        st.info("Bitte WP-Katalog und Speicher-Katalog (Excel) hochladen.")
        st.stop()
    if wp_katalog.empty or speicher_katalog.empty:
        st.warning("⚠️ Bitte mindestens einen WP- und einen Speicher-Hersteller in der Hersteller-Auswahl aktivieren.")
        st.stop()

    zeige_kostenregressionen(wp_katalog, speicher_katalog, key_prefix="e", speicher_katalog_ohne_montage=speicher_katalog_ohne_montage)
    st.divider()

    material = None if material_wahl == "Alle" else material_wahl
    try:
        # WP: EIN gemeinsamer Potenzfit auf Listenpreis+IBN+Montage (core.kostenfunktion.
        # wp_kostenfunktion, Fit 3 - siehe Gesamtübersicht oben). Speicher: EIN Potenzfit auf die
        # Investkosten inkl. Rabatt und Montage-Prozentsatz (core.kostenfunktion.
        # speicher_kostenfunktion) - die Montage wirkt hier rein multiplikativ, eine getrennte
        # Montage-Kostenfunktion ist daher nicht nötig.
        wp_f = wp_kostenfunktion(wp_katalog, montagekosten=wp_montagekosten)
        sp_f = speicher_kostenfunktion(speicher_katalog, material=material)
    except KostenfunktionFehler as e:
        st.error(f"Fehler beim Ableiten der Kostenfunktion: {e}")
        st.stop()

    st.caption(
        f"Kostenfunktion WP (Listenpreis+IBN+Montage, gemeinsamer Fit): {wp_f.koeffizient_a:,.1f} € · "
        f"kW^{wp_f.exponent_b:.3f} (R² = {wp_f.r_quadrat:.3f}) "
        f"({wp_f.stuetzstellen} Katalogeinträge) · "
        f"Kostenfunktion Speicher (Listenpreis+Montage, gemeinsamer Fit): {sp_f.koeffizient_a:,.1f} € · "
        f"l^{sp_f.exponent_b:.3f} (R² = {sp_f.r_quadrat:.3f}) "
        f"({sp_f.stuetzstellen} Katalogeinträge)"
    )

    punkte = optimiere_raster(
        daten, zapfprofil_basis, wp_f, sp_f,
        v_sto_referenz=daten.v_sto, phi_n_referenz=phi_n,
        max_laufzeit_h=max_laufzeit_h, raster_schritte=raster_schritte,
    )

    beste = guenstigster_punkt(punkte)
    anzahl_zulaessig = sum(1 for p in punkte if p.zulaessig)

    if beste is not None:
        # Für den Kostenvergleich in Modus F hinterlegen - samt Kontext, damit
        # dort auffällt, wenn das Optimum unter anderen Randbedingungen entstand.
        st.session_state[FALL_KOSTENOPTIMUM] = GespeichertesKostenoptimum(
            v_sto=beste.v_sto, phi_n=beste.phi_n, kosten=beste.kosten,
            lastprofil_basis=investitions_basis, material=material_wahl,
            raster_schritte=raster_schritte,
            zeitstempel=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("Geprüfte Rasterpunkte", f"{len(punkte)}")
    col2.metric("Davon zulässig", f"{anzahl_zulaessig}")
    col3.metric("Günstigste Investkosten", f"{beste.kosten:,.0f} €" if beste else "—")

    if beste is None:
        st.warning(
            "⚠️ Keine Rasterkombination erfüllt gleichzeitig das Norm-Kriterium, die max. "
            "WP-Laufzeit und den 24h-Ladeausgleich. Referenzwerte für V_sto/Φ_N anpassen."
        )
    else:
        kl_leistung = kleinste_leistung(punkte)
        kl_volumen = kleinstes_volumen(punkte)
        st.success(
            f"**Günstigste Kombination:** {beste.v_sto:,.0f} l Speicher + {beste.phi_n:.1f} kW WP "
            f"= {beste.kosten:,.0f} € · "
            f"**Minimale WP-Leistung:** {kl_leistung.phi_n:.1f} kW (bei {kl_leistung.v_sto:,.0f} l) · "
            f"**Minimales Speichervolumen:** {kl_volumen.v_sto:,.0f} l (bei {kl_leistung.phi_n:.1f} kW WP)"
        )

    fig = plot_systemoptimierung(punkte)
    st.pyplot(fig)
    fig_ohne_titel = plot_systemoptimierung(punkte, titel=False)
    _buf_e = io.BytesIO()
    fig_ohne_titel.savefig(_buf_e, format="pdf", bbox_inches="tight")
    st.download_button("📄 Diagramm ohne Titel als PDF exportieren", data=_buf_e.getvalue(),
                        file_name="systemoptimierung.pdf", mime="application/pdf", key="dl_e_ohne_titel")

    # ----------------------------------------------------------------------
    # Was kosten die tatsächlich ausgelegten Anlagen?
    # Ausgangszustand ist der Norm-Zustand aus Modus A (die reale Anlage unter
    # Norm-Eingangsgrößen). Dagegen treten der selbst dimensionierte
    # Norm-Soll-Zustand aus Modus A2 und das Rasteroptimum dieses Modus an.
    # Der in Modus B gerechnete Monitoring-Fall bleibt bewusst außen vor: Er
    # beschreibt dieselbe Anlage wie Modus A unter einem anderen Zapfprofil und
    # hat damit dasselbe V_sto und Φ_N - seine Kostenzeile wäre eine exakte
    # Wiederholung des Ausgangszustands (Δ = 0), weil die Kostenfunktionen nur
    # von diesen beiden Größen abhängen.
    # ----------------------------------------------------------------------
    st.subheader("💰 Anlagenkosten aus den Kostenfunktionen")
    fall_norm_e = geholter_fall(FALL_NORM)
    fall_soll_e = geholter_fall(FALL_NORM_SOLL)
    anlagen = []
    if fall_norm_e is None:
        st.info(
            "Für den Kostenvergleich muss die normbasiert ausgelegte Anlage als Ausgangszustand "
            "vorliegen: bitte **Modus A** rechnen. Übernommen werden daraus nur V_sto und Φ_N — "
            "die Kostenfunktionen oben hängen von keiner weiteren Eingabe dieses Falls ab."
        )
    else:
        eintraege = [("Norm-Zustand (Modus A)", fall_norm_e.daten.v_sto, fall_norm_e.daten.phi_n)]
        if fall_soll_e is not None:
            eintraege.append(
                ("Norm-Soll-Zustand (Modus A2)", fall_soll_e.daten.v_sto, fall_soll_e.daten.phi_n)
            )
        if beste is not None:
            eintraege.append(("Kostenoptimum (Modus E)", beste.v_sto, beste.phi_n))
        anlagen = bewerte_anlagen(eintraege, wp_f, sp_f)

        if fall_soll_e is None:
            st.info(
                "Der selbst dimensionierte **Norm-Soll-Zustand** fehlt noch — dafür einmal "
                "**Modus A2** rechnen. Der Kostenvergleich läuft auch ohne, dann ohne diesen Balken."
            )

        st.caption(
            f"Bewertet mit genau den Kostenfunktionen dieses Modus (WP: Listenpreis+IBN+Montage, "
            f"Speicher: Listenpreis+Montage, Material-Filter: {material_wahl}). Ausgangszustand ist "
            f"der Norm-Zustand aus Modus A (gerechnet {fall_norm_e.zeitstempel}); Δ sind die "
            f"Mehr- bzw. Minderkosten gegenüber diesem Zustand."
            + (f" Norm-Soll-Zustand gerechnet {fall_soll_e.zeitstempel}."
               if fall_soll_e is not None else "")
        )
        st.table({
            "Anlage": [a.bezeichnung for a in anlagen],
            "V_sto [l]": [f"{a.v_sto:,.0f}" for a in anlagen],
            "Φ_N [kW]": [f"{a.phi_n:.1f}" for a in anlagen],
            "WP-Kosten [€]": [f"{a.wp_kosten:,.0f}" for a in anlagen],
            "Speicher-Kosten [€]": [f"{a.speicher_kosten:,.0f}" for a in anlagen],
            "Gesamtkosten [€]": [f"{a.gesamtkosten:,.0f}" for a in anlagen],
            "Δ zu Modus A [€]": ["—" if a.ist_ausgangszustand else f"{a.diff_abs:+,.0f}" for a in anlagen],
            "Δ zu Modus A [%]": ["—" if a.ist_ausgangszustand else f"{a.diff_pct:+.1f} %" for a in anlagen],
        })

        spalten = st.columns(len(anlagen))
        for spalte, a in zip(spalten, anlagen):
            spalte.metric(
                a.bezeichnung, f"{a.gesamtkosten:,.0f} €",
                delta=None if a.ist_ausgangszustand else f"{a.diff_abs:+,.0f} € ({a.diff_pct:+.1f} %)",
                delta_color="inverse",   # Minderkosten sind hier die gute Richtung
            )

        # Fußzeile des Diagramms: die tatsächlich verwendeten Kostenfunktionen und der
        # Geltungsbereich der Zahlen - damit die Abbildung ohne den umgebenden Text lesbar
        # bleibt, wenn sie als PDF in die Arbeit übernommen wird.
        fusszeile_kosten = (
            f"Kostenfunktionen (Potenzansatz, aus den Katalogen): "
            f"$\\hat{{C}}_\\mathrm{{I}}(\\Phi_N)$ = {wp_f.koeffizient_a:,.2f} · $\\Phi_N^{{{wp_f.exponent_b:.4f}}}$ "
            f"(R² = {wp_f.r_quadrat:.3f}, n = {wp_f.stuetzstellen})   ·   "
            f"$\\hat{{C}}_{{I,sto}}(V_{{sto}})$ = {sp_f.koeffizient_a:,.2f} · $V_{{sto}}^{{{sp_f.exponent_b:.4f}}}$ "
            f"(R² = {sp_f.r_quadrat:.3f}, n = {sp_f.stuetzstellen})\n"
            f"Speicher-Material: {material_wahl}  ·  Lastprofil-Basis des Rasters: {investitions_basis}  ·  "
            f"Raster {raster_schritte} × {raster_schritte}, {anzahl_zulaessig} von {len(punkte)} Punkten zulässig\n"
            "Reine Investitionskosten (keine Betriebs- oder Wartungskosten); "
            "Modus A und A2 sind bewertete Auslegungen, nicht das Kostenoptimum."
        )
        fig_kosten = plot_anlagenkosten_vergleich(anlagen, fusszeile=fusszeile_kosten)
        st.pyplot(fig_kosten)
        # Export mit geschlossenem Achsenrahmen: in der Arbeit steht die
        # Abbildung als abgegrenzter Block im Satzspiegel.
        _buf_kosten = io.BytesIO()
        plot_anlagenkosten_vergleich(
            anlagen, titel=False, fusszeile=fusszeile_kosten, vollrahmen=True,
        ).savefig(_buf_kosten, format="pdf", bbox_inches="tight")
        st.download_button(
            "📄 Diagramm ohne Titel als PDF exportieren", data=_buf_kosten.getvalue(),
            file_name="anlagenkosten_vergleich.pdf", mime="application/pdf", key="dl_e_kosten")

    protokoll = f"""SYSTEMOPTIMIERUNG ÜBER KOSTENFUNKTIONEN — ÖNORM EN 12831-3
{'=' * 70}
{NORMWERTE_PROTOKOLLZEILE}
Lastprofil-Basis                : {investitions_basis}
Speichertyp                     : {daten.speicher_typ}
Speicher-Material (Filter)      : {material_wahl}
Referenz V_sto / Φ_N            : {daten.v_sto:.0f} l / {phi_n:.1f} kW
Max. WP-Laufzeit                : {max_laufzeit_h:.0f} h/d
Rasterauflösung                 : {raster_schritte} x {raster_schritte}
Geprüfte Rasterpunkte           : {len(punkte)}
Davon zulässig                  : {anzahl_zulaessig}

KOSTENFUNKTIONEN (Potenzansatz K = a * x^b je Bestandteil, über die Kataloge, + Montage)
--------------------------------------------------------------------------------
WP Listenpreis+IBN+Montage (gemeinsamer Fit) : {wp_f.koeffizient_a:,.2f} € * Φ_N^{wp_f.exponent_b:.4f}   (R² = {wp_f.r_quadrat:.3f})
WP Montage (Pauschale, im Fit enthalten) : {wp_montagekosten:,.2f} €
Speicher Listenpreis+Montage (gemeinsamer Fit) : {sp_f.koeffizient_a:,.2f} € * V_sto^{sp_f.exponent_b:.4f}   (R² = {sp_f.r_quadrat:.3f})
Speicher Montage (% auf rabattierte Investkosten, im Fit enthalten) : {sp_montage_pct:.1f} %
"""
    if beste is not None:
        protokoll += f"""
GÜNSTIGSTE KOMBINATION
--------------------------------------------------------------------------------
V_sto        : {beste.v_sto:,.0f} l
Φ_N          : {beste.phi_n:.1f} kW
Gesamtkosten : {beste.kosten:,.2f} €
SOC_min      : {beste.soc_min_kwh:.2f} kWh (Q_sto,min = {beste.q_sto_min_kwh:.2f} kWh)
WP-Zyklen    : {beste.zyklen} | Laufzeit: {beste.laufzeit_min} min
"""
    protokoll += (
        "\nANLAGENKOSTEN AUS DEN KOSTENFUNKTIONEN "
        "(Ausgangszustand: Normauslegung Modus A, Δ = Mehr-/Minderkosten dazu)\n"
        + "-" * 80 + "\n"
    )
    if anlagen:
        protokoll += anlagenkosten_text(anlagen) + "\n"
        protokoll += f"Norm-Zustand (Ausgangszustand) gerechnet {fall_norm_e.zeitstempel}\n"
        protokoll += (
            f"Norm-Soll-Zustand (Modus A2) gerechnet {fall_soll_e.zeitstempel}\n"
            if fall_soll_e is not None
            else "HINWEIS: Kein in Modus A2 dimensionierter Norm-Soll-Zustand hinterlegt.\n"
        )
    else:
        protokoll += (
            "Kein in Modus A gerechneter Norm-Fall hinterlegt - ohne diesen Ausgangszustand\n"
            "ist kein Kostenvergleich der ausgelegten Anlagen möglich.\n"
        )
    protokoll += "\n" + eingabeparameter_block()
    st.text_area("Ergebnisprotokoll", protokoll, height=320)

else:  # Modus F: Techno-ökonomische Optimierung (immer gegen Monitoring-Messdaten)
    zapfprofil_basis = zapf_ist

    if wp_katalog is None or speicher_katalog is None:
        st.info("Bitte WP-Katalog und Speicher-Katalog (Excel) hochladen.")
        st.stop()
    if wp_katalog.empty or speicher_katalog.empty:
        st.warning("⚠️ Bitte mindestens einen WP- und einen Speicher-Hersteller in der Hersteller-Auswahl aktivieren.")
        st.stop()

    zeige_kostenregressionen(wp_katalog, speicher_katalog, key_prefix="f", speicher_katalog_ohne_montage=speicher_katalog_ohne_montage)
    st.divider()

    if zapf_woche is None:
        st.warning(
            "⚠️ Es ist nur der **Bemessungstag** geladen. Ohne **Bemessungswoche** lässt sich nicht "
            "prüfen, ob sich der Speicher im Dauerbetrieb wieder erholt — eine Kombination, die den "
            "Speicher am Bemessungstag leerfährt, gilt dann fälschlich als zulässig. Bitte links die "
            "Wochendatei hochladen."
        )

    st.caption(
        "Geprüft wird jede Kombination gegen **beide** Monitoring-Profile: den **Bemessungstag** "
        "(Spitzendeckung) und die **Bemessungswoche** (Dauerbetrieb). Zulässig ist nur, was in beiden "
        "besteht. Bedingungen: Norm-Kriterium SOC_min ≥ Q_sto,min (Abschnitt 6.4.3.3) in beiden "
        f"Profilen, Erzeugerlaufzeit ≤ **{max_laufzeit_h:.0f} h je Kalendertag** (Sperrzeiten) und — "
        "nur über die Woche auswertbar — **Erholung des Speichers**: er muss mindestens einmal je Tag "
        "wieder auf ≥ 95 % von Q_sto,max kommen, unabhängig davon, wann im Tagesverlauf das passiert."
    )
    st.caption(
        "Laufzeitgrenze und Erholung sind **Zusatzbedingungen der Auslegung, keine Norm-Kriterien** — "
        "die Norm prüft in 6.4.3.3 ausschließlich SOC_min ≥ Q_sto,min. Beim Speicherladesystem ist "
        "Q_sto,min = 0 (6.4.2.4.2), das Norm-Kriterium allein lässt also einen leergefahrenen Speicher zu."
    )

    material = None if material_wahl == "Alle" else material_wahl
    try:
        kombinationen = optimiere(
            daten, zapfprofil_basis, wp_katalog, speicher_katalog, material=material,
            zapfprofil_woche=zapf_woche, max_laufzeit_h=max_laufzeit_h,
        )
    except ValueError as e:
        st.error(str(e))
        st.stop()

    anzahl_zulaessig = sum(1 for k in kombinationen if k.zulaessig)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Geprüfte Kombinationen", f"{len(kombinationen)}")
    col2.metric("Davon zulässig", f"{anzahl_zulaessig}")
    col3.metric("Norm-Kriterium erfüllt", f"{sum(1 for k in kombinationen if k.tag.erfuellt_norm and (k.woche is None or k.woche.erfuellt_norm))}")
    col4.metric(f"Laufzeit ≤ {max_laufzeit_h:.0f} h/d", f"{sum(1 for k in kombinationen if k.tag.erfuellt_laufzeit and (k.woche is None or k.woche.erfuellt_laufzeit))}")

    if anzahl_zulaessig == 0:
        # Ohne Aufschlüsselung wäre nicht erkennbar, welche der drei Bedingungen
        # den Katalog leer filtert - und damit auch nicht, was zu ändern wäre.
        raus_norm = sum(1 for k in kombinationen if not (k.tag.erfuellt_norm and (k.woche is None or k.woche.erfuellt_norm)))
        raus_laufzeit = sum(1 for k in kombinationen if not (k.tag.erfuellt_laufzeit and (k.woche is None or k.woche.erfuellt_laufzeit)))
        raus_erholung = sum(1 for k in kombinationen if k.woche is not None and not k.woche.erfuellt_erholung)
        st.warning(
            "⚠️ Keine Kombination erfüllt alle Bedingungen. Ausgeschieden an:\n\n"
            f"- Norm-Kriterium (SOC_min < Q_sto,min): **{raus_norm}**\n"
            f"- Laufzeit über {max_laufzeit_h:.0f} h/d: **{raus_laufzeit}**\n"
            f"- Erholung des Speichers: **{raus_erholung}**\n\n"
            "(Mehrfachnennung möglich.) Größere WP-Modelle oder Speicher aufnehmen, oder die "
            "Laufzeitgrenze anheben."
        )
        st.stop()

    technisch = materialschonendste_zulaessige(kombinationen)
    oekonomisch = guenstigste_zulaessige(kombinationen)
    front = pareto_front(kombinationen)

    gewicht_kosten = st.slider(
        "Variante 3 — Gewichtung techno-ökonomischer Kompromiss: Kosten ↔ Schalthäufigkeit",
        min_value=0.0, max_value=1.0, value=0.5, step=0.05,
        help="0 = rein technische, 1 = rein ökonomische Gewichtung. Gesamtkosten und Schalthäufigkeit "
             "werden vorher je auf [0, 1] normiert (min-max über die zulässigen Kombinationen), damit "
             "die unterschiedlichen Größenordnungen (€ vs. Anzahl Zyklen) die Gewichtung nicht verzerren.",
    )
    kompromiss = kompromiss_zulaessige(kombinationen, gewicht_kosten=gewicht_kosten)

    def _variante_karte(spalte, titel_text, k) -> None:
        with spalte:
            st.markdown(f"**{titel_text}**")
            if k is None:
                st.info("Keine zulässige Kombination.")
                return
            st.metric("Gesamtkosten", f"{k.gesamtkosten:,.0f} €")
            st.metric("Schalthäufigkeit (Zyklen)", f"{k.zyklen}")
            st.caption(
                f"{k.wp_hersteller} {k.wp_produkt} ({k.wp_leistung_kw:.1f} kW) + "
                f"{k.speicher_hersteller} {k.speicher_produkt} "
                f"({k.speicher_volumen_l:.0f} l, {k.speicher_material})"
            )
            zeilen = [f"Tag: max. {k.tag.laufzeit_max_tag_min / 60:.1f} h/d · SOC_min {k.tag.soc_min_kwh:.1f} kWh"]
            if k.woche is not None:
                zeilen.append(
                    f"Woche: max. {k.woche.laufzeit_max_tag_min / 60:.1f} h/d · "
                    f"SOC_min {k.woche.soc_min_kwh:.1f} kWh · "
                    f"Vollladung spätestens alle {k.woche.erholung_max_abstand_min / 60:.1f} h"
                )
            st.caption("  \n".join(zeilen))

    col1, col2, col3 = st.columns(3)
    _variante_karte(col1, "🔧 V1 — Technische Optimierung", technisch)
    _variante_karte(col2, "💶 V2 — Ökonomische Optimierung", oekonomisch)
    _variante_karte(col3, "⚖️ V3 — Techno-ökonomische Optimierung", kompromiss)

    st.subheader("Zielkonflikt: Gesamtkosten vs. Schalthäufigkeit")
    st.caption(
        f"{len(front)} nicht-dominierte Kombinationen bilden die Pareto-Front (Linie): keine andere "
        "zulässige Kombination ist gleichzeitig günstiger UND materialschonender (weniger Zyklen)."
    )
    fig = plot_pareto_front(kombinationen, front, technisch, oekonomisch, kompromiss)
    st.pyplot(fig)
    fig_ohne_titel = plot_pareto_front(kombinationen, front, technisch, oekonomisch, kompromiss, titel=False)
    _buf_f = io.BytesIO()
    fig_ohne_titel.savefig(_buf_f, format="pdf", bbox_inches="tight")
    st.download_button("📄 Diagramm ohne Titel als PDF exportieren", data=_buf_f.getvalue(),
                        file_name="techno_oekonomische_optimierung.pdf", mime="application/pdf", key="dl_f_ohne_titel")

    st.subheader("Pareto-Front — alle nicht-dominierten Kombinationen")
    if front:
        st.table({
            "WP": [f"{k.wp_hersteller} {k.wp_produkt} ({k.wp_leistung_kw:.1f} kW)" for k in front],
            "Speicher": [f"{k.speicher_hersteller} {k.speicher_produkt} ({k.speicher_volumen_l:.0f} l, {k.speicher_material})" for k in front],
            "Gesamtkosten [€]": [f"{k.gesamtkosten:,.0f}" for k in front],
            "Zyklen": [f"{k.zyklen}" for k in front],
            "Laufzeit Tag [h/d]": [f"{k.tag.laufzeit_max_tag_min / 60:.1f}" for k in front],
            "Laufzeit Woche [h/d]": [
                "—" if k.woche is None else f"{k.woche.laufzeit_max_tag_min / 60:.1f}" for k in front
            ],
            "Erholung spät. [h]": [
                "—" if k.woche is None else f"{k.woche.erholung_max_abstand_min / 60:.1f}" for k in front
            ],
        })

    # ----------------------------------------------------------------------
    # Kosten je Optimierungsvariante
    #
    # Nebeneinander stehen drei verschiedene Arten von Ergebnis: die
    # Normauslegung aus Modus A (Handeingabe), das Rasteroptimum aus Modus E
    # (rechnerischer Punkt, kein Produkt) und die drei Varianten dieses Modus
    # (reale Katalogprodukte). Vergleichbar werden sie nur, wenn ALLE mit
    # denselben Kostenfunktionen bewertet werden - stünde ein Katalogpreis
    # neben einem Fitwert, enthielte die Differenz den Rest der Regression
    # statt eines Auslegungsunterschieds. Der tatsächliche Katalogpreis der
    # Varianten steht deshalb als eigene Spalte daneben.
    # ----------------------------------------------------------------------
    st.subheader("💰 Kosten je Optimierungsvariante")
    fall_norm_f = geholter_fall(FALL_NORM)
    optimum_e = st.session_state.get(FALL_KOSTENOPTIMUM)
    anlagen_f = []
    try:
        wp_f = wp_kostenfunktion(wp_katalog, montagekosten=wp_montagekosten)
        sp_f = speicher_kostenfunktion(speicher_katalog, material=material)
    except KostenfunktionFehler as e:
        st.warning(f"⚠️ Kostenfunktionen nicht ableitbar, der Kostenvergleich entfällt: {e}")
        wp_f = sp_f = None

    varianten_f = [
        ("V1 technisch (Modus F)", technisch),
        ("V2 ökonomisch (Modus F)", oekonomisch),
        ("V3 Kompromiss (Modus F)", kompromiss),
    ]

    if fall_norm_f is None:
        st.info(
            "Für den Kostenvergleich fehlt der Ausgangszustand: bitte **Modus A** rechnen. "
            "Übernommen werden daraus nur V_sto und Φ_N — die Kostenfunktionen hängen von keiner "
            "weiteren Eingabe dieses Falls ab."
        )
    elif wp_f is not None:
        eintraege_f = [("Norm-Zustand (Modus A)", fall_norm_f.daten.v_sto, fall_norm_f.daten.phi_n)]
        if optimum_e is not None:
            eintraege_f.append(("Kostenoptimum (Modus E)", optimum_e.v_sto, optimum_e.phi_n))
        for bezeichnung, k in varianten_f:
            if k is not None:
                eintraege_f.append((bezeichnung, k.speicher_volumen_l, k.wp_leistung_kw))
        anlagen_f = bewerte_anlagen(eintraege_f, wp_f, sp_f)

        if optimum_e is None:
            st.info(
                "Das Kostenoptimum aus **Modus E** ist noch nicht hinterlegt — dafür einmal Modus E "
                "rechnen. Der Vergleich läuft auch ohne, dann ohne diesen Balken."
            )
        elif optimum_e.material != material_wahl:
            st.warning(
                f"⚠️ Das hinterlegte Modus-E-Optimum wurde mit Speicher-Material "
                f"„{optimum_e.material}“ gerechnet, hier ist „{material_wahl}“ eingestellt. Damit "
                "beruht es auf einer anderen Kostenfunktion als der, mit der es hier bewertet wird."
            )

        st.caption(
            "Alle Anlagen mit **denselben** Kostenfunktionen bewertet (WP: Listenpreis+IBN+Montage, "
            f"Speicher: Listenpreis+Montage, Material-Filter: {material_wahl}), damit Handauslegung, "
            "Rasterpunkt und Katalogprodukte auf einer gemeinsamen Basis stehen. Ausgangszustand ist "
            "die Normauslegung aus Modus A; Δ sind die Mehr- bzw. Minderkosten dazu. Die Spalte "
            "**Katalogpreis** zeigt, was die drei Varianten als reale Produkte tatsächlich kosten — "
            "die Differenz zur Spalte *Gesamtkosten* ist der Rest der Regression, kein "
            "Auslegungsunterschied."
        )
        katalogpreis_f = {b: k.gesamtkosten for b, k in varianten_f if k is not None}
        zyklen_f = {b: k.zyklen for b, k in varianten_f if k is not None}
        st.table({
            "Anlage": [a.bezeichnung for a in anlagen_f],
            "V_sto [l]": [f"{a.v_sto:,.0f}" for a in anlagen_f],
            "Φ_N [kW]": [f"{a.phi_n:.1f}" for a in anlagen_f],
            "WP-Kosten [€]": [f"{a.wp_kosten:,.0f}" for a in anlagen_f],
            "Speicher-Kosten [€]": [f"{a.speicher_kosten:,.0f}" for a in anlagen_f],
            "Gesamtkosten [€]": [f"{a.gesamtkosten:,.0f}" for a in anlagen_f],
            "Δ zu Modus A [€]": ["—" if a.ist_ausgangszustand else f"{a.diff_abs:+,.0f}" for a in anlagen_f],
            "Δ zu Modus A [%]": ["—" if a.ist_ausgangszustand else f"{a.diff_pct:+.1f} %" for a in anlagen_f],
            "Katalogpreis [€]": [
                f"{katalogpreis_f[a.bezeichnung]:,.0f}" if a.bezeichnung in katalogpreis_f else "—"
                for a in anlagen_f
            ],
            "Zyklen (Tag)": [
                f"{zyklen_f[a.bezeichnung]}" if a.bezeichnung in zyklen_f else "—"
                for a in anlagen_f
            ],
        })

        fusszeile_kosten_f = (
            f"Kostenfunktionen (Potenzansatz, aus den Katalogen): "
            f"$\\hat{{C}}_\\mathrm{{I}}(\\Phi_N)$ = {wp_f.koeffizient_a:,.2f} · $\\Phi_N^{{{wp_f.exponent_b:.4f}}}$ "
            f"(R² = {wp_f.r_quadrat:.3f}, n = {wp_f.stuetzstellen})   ·   "
            f"$\\hat{{C}}_{{I,sto}}(V_{{sto}})$ = {sp_f.koeffizient_a:,.2f} · $V_{{sto}}^{{{sp_f.exponent_b:.4f}}}$ "
            f"(R² = {sp_f.r_quadrat:.3f}, n = {sp_f.stuetzstellen})\n"
            f"Speicher-Material: {material_wahl}  ·  geprüft gegen Bemessungstag"
            + (" und Bemessungswoche" if zapf_woche is not None else " (Bemessungswoche fehlt)")
            + f"  ·  Laufzeitgrenze {max_laufzeit_h:.0f} h/d  ·  Gewichtung V3: "
            f"{gewicht_kosten:.2f} Kosten / {1 - gewicht_kosten:.2f} Schalthäufigkeit\n"
            "Reine Investitionskosten (keine Betriebs- oder Wartungskosten); alle Anlagen mit "
            "denselben Kostenfunktionen bewertet, damit Katalogprodukte und Rasteroptimum "
            "vergleichbar sind."
        )
        TITEL_KOSTEN_F = "Investitionskosten je Optimierungsvariante (Kostenfunktionen Modus E)"
        st.pyplot(plot_anlagenkosten_vergleich(
            anlagen_f, fusszeile=fusszeile_kosten_f, titel_text=TITEL_KOSTEN_F))
        # Im Export bleibt die Modusangabe weg: in der Arbeit steht die Abbildung
        # ohne die Bedienoberfläche des Tools, der Zusammenhang gehört in die
        # Bildunterschrift. In der App ist der Hinweis dagegen die Orientierung,
        # aus welchem Modus ein Balken stammt. Der Achsenrahmen wird für den
        # Export rundum geschlossen.
        _buf_kosten_f = io.BytesIO()
        plot_anlagenkosten_vergleich(
            anlagen_f, titel=False, fusszeile=fusszeile_kosten_f, modus_hinweis=False,
            vollrahmen=True,
        ).savefig(_buf_kosten_f, format="pdf", bbox_inches="tight")
        st.download_button(
            "📄 Diagramm ohne Titel als PDF exportieren", data=_buf_kosten_f.getvalue(),
            file_name="kosten_optimierungsvarianten.pdf", mime="application/pdf", key="dl_f_kosten")

    def _lauf_protokoll(bezeichnung: str, lauf) -> str:
        if lauf is None:
            return f"  {bezeichnung:<16}: nicht geprüft (keine Datei geladen)\n"
        return (
            f"  {bezeichnung:<16}: SOC_min {lauf.soc_min_kwh:>7.2f} kWh (Q_sto,min = {lauf.q_sto_min_kwh:.2f}) | "
            f"Zyklen {lauf.zyklen:>3} | max. Laufzeit {lauf.laufzeit_max_tag_min / 60:>5.1f} h/d | "
            f"Vollladung spätestens alle {lauf.erholung_max_abstand_min / 60:>5.1f} h\n"
        )

    def _variante_protokoll(titel_text: str, k) -> str:
        if k is None:
            return f"{titel_text}\n  keine zulässige Kombination\n"
        return (
            f"{titel_text}\n"
            f"  Wärmepumpe   : {k.wp_hersteller} {k.wp_produkt} — {k.wp_leistung_kw:.1f} kW, {k.wp_kosten:,.2f} €\n"
            f"  Speicher     : {k.speicher_hersteller} {k.speicher_produkt} — {k.speicher_volumen_l:.0f} l, "
            f"{k.speicher_material}, {k.speicher_kosten:,.2f} €\n"
            f"  Gesamtkosten : {k.gesamtkosten:,.2f} €\n"
            + _lauf_protokoll("Bemessungstag", k.tag)
            + _lauf_protokoll("Bemessungswoche", k.woche)
        )

    raus_norm_p = sum(1 for k in kombinationen if not (k.tag.erfuellt_norm and (k.woche is None or k.woche.erfuellt_norm)))
    raus_laufzeit_p = sum(1 for k in kombinationen if not (k.tag.erfuellt_laufzeit and (k.woche is None or k.woche.erfuellt_laufzeit)))
    raus_erholung_p = sum(1 for k in kombinationen if k.woche is not None and not k.woche.erfuellt_erholung)

    protokoll = f"""TECHNO-ÖKONOMISCHE OPTIMIERUNG (MODUS F) — ÖNORM EN 12831-3
{'=' * 70}
{NORMWERTE_PROTOKOLLZEILE}
Datengrundlage Bemessungstag   : {monitoring_quelle_label}
Datengrundlage Bemessungswoche : {wochen_quelle_label or "— (nicht geladen, Erholung ungeprüft)"}
Speichertyp                    : {daten.speicher_typ}
Speicher-Material (Filter)     : {material_wahl}
Geprüfte Kombinationen         : {len(kombinationen)}
Davon zulässig (alle Bedingungen): {anzahl_zulaessig}
Pareto-Front (nicht dominiert) : {len(front)} Kombinationen
Gewichtung Kompromiss (V3)     : {gewicht_kosten:.2f} Kosten / {1 - gewicht_kosten:.2f} Schalthäufigkeit

ZULÄSSIGKEITSBEDINGUNGEN (Mehrfachnennung möglich)
--------------------------------------------------------------------------------
1) Norm-Kriterium SOC_min >= Q_sto,min (6.4.3.3), in BEIDEN Profilen
   ausgeschieden: {raus_norm_p}
2) Erzeugerlaufzeit <= {max_laufzeit_h:.0f} h je Kalendertag (Sperrzeiten) - Zusatzbedingung, keine Norm
   ausgeschieden: {raus_laufzeit_p}
3) Erholung: Speicher erreicht mind. 1x je Tag wieder >= 95 % von Q_sto,max
   (nur über die Bemessungswoche auswertbar) - Zusatzbedingung, keine Norm
   ausgeschieden: {raus_erholung_p}

Hinweis: Beim Speicherladesystem ist Q_sto,min = 0 (6.4.2.4.2). Das Norm-Kriterium
allein lässt damit einen leergefahrenen Speicher zu; erst Bedingung 3 schließt
Kombinationen aus, die sich im Dauerbetrieb nicht wieder erholen.

{_variante_protokoll("VARIANTE 1 — TECHNISCHE OPTIMIERUNG (min. Schalthäufigkeit)", technisch)}
{_variante_protokoll("VARIANTE 2 — ÖKONOMISCHE OPTIMIERUNG (min. Investkosten)", oekonomisch)}
{_variante_protokoll("VARIANTE 3 — TECHNO-ÖKONOMISCHE OPTIMIERUNG (gewichteter Kompromiss)", kompromiss)}
"""
    if anlagen_f:
        protokoll += (
            "\nKOSTEN JE OPTIMIERUNGSVARIANTE\n"
            "(alle Anlagen mit denselben Kostenfunktionen bewertet; Ausgangszustand:\n"
            " Normauslegung Modus A, Delta = Mehr-/Minderkosten dazu)\n"
            + "-" * 80 + "\n"
            + anlagenkosten_text(anlagen_f) + "\n"
        )
        if optimum_e is not None:
            protokoll += (
                f"Kostenoptimum aus Modus E gerechnet {optimum_e.zeitstempel} "
                f"(Basis {optimum_e.lastprofil_basis}, Material {optimum_e.material}, "
                f"Raster {optimum_e.raster_schritte} x {optimum_e.raster_schritte})\n"
            )
        else:
            protokoll += "HINWEIS: Kein in Modus E gerechnetes Kostenoptimum hinterlegt.\n"
        protokoll += (
            "Die Katalogpreise der drei Varianten stehen oben bei den Varianten; die Kostenspalten\n"
            "hier sind die Werte der Kostenfunktionen, damit alle Zeilen vergleichbar sind.\n"
        )
    protokoll += "\n" + eingabeparameter_block()
    st.text_area("Ergebnisprotokoll", protokoll, height=400)

pdf_buffer = io.BytesIO()
with PdfPages(pdf_buffer) as pdf:
    pdf.savefig(fig_ohne_titel, bbox_inches="tight")
    # Protokollseiten in ALLEN Modi quer: Die Tabellen (Eingangs- und
    # Anlagenparameter, Kostenvergleiche, Laufkennzahlen je Profil) sind breiter
    # als die rund 110 Zeichen des Hochformats und wurden dort rechts
    # abgeschnitten - am deutlichsten die Parametergegenüberstellung in Modus C
    # und die Kostentabellen in Modus E und F.
    pdf_textseiten(pdf, protokoll, querformat=True)
st.download_button(
    "📄 Als PDF exportieren",
    data=pdf_buffer.getvalue(),
    file_name="TWW_Auslegung.pdf",
    mime="application/pdf",
)
