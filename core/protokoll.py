"""Parameterprotokoll für die Ergebnisberichte.

Wandelt einen Eingabedatensatz in geordnete Abschnitte "Parametername ->
formatierter Wert" um und stellt zwei solche Parametersätze gegenüber. Damit
ist im Vergleichsmodus C nachvollziehbar, mit welchen Eingaben je Fall
gerechnet wurde - der Norm-Fall etwa mit geschätzten Verlusten nach Gl. 6/9,
der Monitoring-Fall mit einem gemessenen Summenverlust.

Beide Parametersätze verwenden immer denselben Schlüsselsatz; nicht zutreffende
Größen tragen den Platzhalter, damit die Gegenüberstellung zeilenweise
ausgerichtet bleibt. Reine Formatierlogik ohne UI-Bezug.
"""

from dataclasses import dataclass

from core.bedarf import aequivalente_personen
from core.modell import Eingabedaten
from core.speicherverbund import SERIE, Speicherverbund

PLATZHALTER = "—"
NAMENSBREITE = 35

ABSCHNITT_ZAPFPROFIL = "Zapfprofil & Tagesbedarf"
ABSCHNITT_ANLAGE = "Anlage (Speicher & Erzeuger)"
ABSCHNITT_VERLUSTE = "Verluste & Netz"
ABSCHNITT_TEMPERATUREN = "Temperaturen & Konstanten"

_KEYS_VERFAHREN_AB = [
    "Personenzahl n_P",
    "Spez. Bedarf pro Person V_W,P,day",
    "Anzahl Einheiten f",
    "Spez. Bedarf pro Einheit V_W,f,day",
]
_KEYS_VERFAHREN_C = [
    "Gebäudetyp (Anhang B.2.2)",
    "Bewohnbare Fläche A_h je Einheit",
    "Anzahl Wohneinheiten",
    "Vorgabewerte Gl. B.5",
    "n_P,eq,max je Einheit (Gl. B.1/B.3)",
    "n_P,eq je Einheit (Gl. B.2/B.4)",
    "n_P,eq gesamt",
    "Spez. Bedarf V_W,P,day (Gl. B.5)",
]
_KEYS_MONITORING = [
    "Monitoring-Datei",
    "Analysezeitraum",
    "Auflösung Messdaten",
]


@dataclass(frozen=True)
class ParameterZeile:
    """Eine Zeile der Gegenüberstellung zweier Parametersätze."""

    name: str
    links: str
    rechts: str

    @property
    def unterschiedlich(self) -> bool:
        return self.links != self.rechts

    @property
    def beidseitig_leer(self) -> bool:
        """Größe, die in keinem der beiden Fälle in die Rechnung eingeflossen ist
        (z. B. die Anhang-B.2.2-Werte, wenn keiner der Fälle Verfahren C nutzt)."""
        return self.links.startswith(PLATZHALTER) and self.rechts.startswith(PLATZHALTER)


def _tagesbedarf_werte(daten: Eingabedaten) -> dict[str, str]:
    """Belegt immer alle Tagesbedarfs-Schlüssel; das jeweils nicht verwendete
    Verfahren bleibt auf dem Platzhalter (Gl. 20/21 vs. Anhang B.2.2)."""
    werte = {k: PLATZHALTER for k in _KEYS_VERFAHREN_AB + _KEYS_VERFAHREN_C}

    if daten.tagesbedarf_methode == "C":
        eq = aequivalente_personen(daten)
        massgebend = "x (Obergrenze)" if eq.x_greift else "y * A_h / n_P,eq"
        werte.update({
            "Gebäudetyp (Anhang B.2.2)": daten.wohnungstyp,
            "Bewohnbare Fläche A_h je Einheit": f"{daten.wohnflaeche:.1f} m²",
            "Anzahl Wohneinheiten": f"{daten.anzahl_wohneinheiten}",
            "Vorgabewerte Gl. B.5": (
                f"x = {daten.x_max_spez_volumen:.2f} l/(P*d), "
                f"y = {daten.y_spez_volumen:.2f} l/(m²*d)"
            ),
            "n_P,eq,max je Einheit (Gl. B.1/B.3)": f"{eq.n_p_eq_max:.3f}",
            "n_P,eq je Einheit (Gl. B.2/B.4)": f"{eq.n_p_eq:.3f}",
            "n_P,eq gesamt": f"{eq.n_p_eq_gesamt:.3f}",
            "Spez. Bedarf V_W,P,day (Gl. B.5)": (
                f"{eq.v_w_p_day:.2f} l/(Person*d) [maßgebend: {massgebend}]"
            ),
        })
    else:
        werte.update({
            "Personenzahl n_P": f"{daten.n_personen}",
            "Spez. Bedarf pro Person V_W,P,day": f"{daten.v_pro_person:.1f} l",
            "Anzahl Einheiten f": f"{daten.n_einheiten}",
            "Spez. Bedarf pro Einheit V_W,f,day": f"{daten.v_pro_einheit:.1f} l",
        })
    return werte


def _verlust_werte(daten: Eingabedaten) -> dict[str, str]:
    """Norm-Schätzung (Gl. 6/9) und gemessener Summenverlust belegen dieselben
    Schlüssel, damit in der Gegenüberstellung sichtbar wird, welcher der beiden
    Ansätze je Fall gegriffen hat."""
    if daten.verlust_gesamt_je_minute is not None:
        return {
            "Verlustansatz": "Messwert (ersetzt Gl. 6/9)",
            "Bereitschaftsverlust q_sb,sto": PLATZHALTER,
            "Spez. Leitungsverlust q'_dis": PLATZHALTER,
            "Rohrleitungslänge l_dis": PLATZHALTER,
            "Gesamtverlust q_V,ges (Messung)": f"{daten.verlust_gesamt_je_minute:.3f} kWh/min",
        }
    return {
        "Verlustansatz": "Norm-Schätzung (Gl. 6/9)",
        "Bereitschaftsverlust q_sb,sto": f"{daten.q_sb_sto:.2f} kWh/24h",
        "Spez. Leitungsverlust q'_dis": f"{daten.q_dis_spec:.2f} W/m",
        "Rohrleitungslänge l_dis": f"{daten.l_dis:.1f} m",
        "Gesamtverlust q_V,ges (Messung)": PLATZHALTER,
    }


def _anlagen_werte(daten: Eingabedaten, verbund: Speicherverbund | None) -> dict[str, str]:
    """Anlagenabschnitt; bei einem Speicherverbund zusätzlich die Angaben je
    Einzelspeicher.

    V_sto, h_sto und h_sensor sind im Verbundfall die Größen des gedachten
    Gesamtspeichers, mit denen tatsächlich gerechnet wurde - deshalb ist der
    Bezug jeweils dazugeschrieben. Die Einbauhöhe des Fühlers bleibt dagegen
    die real messbare Höhe über dem Boden des Speichers, in dem er sitzt (die
    Speicher stehen nebeneinander, nicht aufeinander).
    """
    ist_verbund = verbund is not None and verbund.ist_verbund
    stapel = ist_verbund and verbund.schaltung == SERIE

    werte = {
        "Speichertyp": daten.speicher_typ,
        "Speicheranordnung": verbund.kurzbeschreibung if ist_verbund else PLATZHALTER,
        "Je Speicher (V / h / q_sb,sto)": (
            f"{verbund.v_je_speicher:.1f} l / {verbund.h_je_speicher:.2f} m / "
            f"{verbund.q_sb_je_speicher:.2f} kWh/24h" if ist_verbund else PLATZHALTER
        ),
        "Fühler sitzt im": verbund.fuehler_position if stapel else PLATZHALTER,
        "Bruttovolumen Speicher V_sto": (
            f"{daten.v_sto:.1f} l" + (" (Summe)" if ist_verbund else "")
        ),
        "Gesamthöhe Speicher h_sto": (
            f"{daten.h_sto:.2f} m" + (" (rechnerische Stapelhöhe)" if stapel else "")
        ),
        "Fühlerhöhe h_sensor (ab Oberkante)": (
            f"{daten.h_sensor:.2f} m" + (" (ab Oberkante des Verbunds)" if stapel else "")
        ),
        "Einbauhöhe Fühler über Boden": (
            f"{verbund.einbauhoehe_fuehler:.2f} m (in diesem Speicher)" if ist_verbund
            else f"{daten.h_sensor_ueber_boden:.2f} m"
        ),
        "Ladungsfaktor f_l": f"{daten.f_l:.2f}",
        "Nennleistung Erzeuger Φ_N": f"{daten.phi_n:.2f} kW",
        "Zeitverzögerung t_lag,HG": f"{daten.t_lag_hg:.1f} min",
    }
    return werte


def parametersatz(
    daten: Eingabedaten,
    *,
    methode_label: str = "",
    quelle_label: str = "",
    ist_monitoring: bool = False,
    monitoring_zeilen: dict[str, str] | None = None,
    verbund: Speicherverbund | None = None,
) -> dict[str, dict[str, str]]:
    """Vollständiger Parametersatz eines Berechnungsfalls, nach Abschnitten.

    ist_monitoring=True kennzeichnet einen Fall, dessen Zapfprofil aus
    Messdaten stammt - die Tagesbedarfs-Parameter nach Gl. 20/21 bzw. Anhang
    B.2.2 sind dort nicht in die Berechnung eingeflossen und bleiben leer.

    `verbund` dokumentiert zusätzlich, aus wie vielen Einzelspeichern die in
    `daten` stehenden Normgrößen entstanden sind (core/speicherverbund.py).
    """
    zapfprofil: dict[str, str] = {"Datenquelle Zapfprofil": quelle_label or PLATZHALTER}

    if ist_monitoring:
        zapfprofil["Berechnungsverfahren Tagesbedarf"] = f"{PLATZHALTER} (Zapfprofil aus Messdaten)"
        zapfprofil.update({k: PLATZHALTER for k in _KEYS_VERFAHREN_AB + _KEYS_VERFAHREN_C})
        zapfprofil["Lastprofil (Anhang B.1)"] = PLATZHALTER
    else:
        zapfprofil["Berechnungsverfahren Tagesbedarf"] = methode_label or PLATZHALTER
        zapfprofil.update(_tagesbedarf_werte(daten))
        zapfprofil["Lastprofil (Anhang B.1)"] = daten.gewaehltes_profil

    zapfprofil.update({k: PLATZHALTER for k in _KEYS_MONITORING})
    zapfprofil.update(monitoring_zeilen or {})

    return {
        ABSCHNITT_ZAPFPROFIL: zapfprofil,
        # h_sensor ist der Abstand von der Speicheroberkante (so geht er in Gl. 5/10
        # ein). Damit aus dem Bericht nicht fälschlich eine Einbauhöhe über dem Boden
        # gelesen wird, steht die tatsächliche Einbauhöhe als eigene Zeile daneben.
        ABSCHNITT_ANLAGE: _anlagen_werte(daten, verbund),
        ABSCHNITT_VERLUSTE: _verlust_werte(daten),
        ABSCHNITT_TEMPERATUREN: {
            "Zapftemperatur ϑ_draw": f"{daten.theta_draw:.1f} °C",
            "Kaltwassertemperatur ϑ_c": f"{daten.theta_c:.1f} °C",
            "Max. Speichertemperatur ϑ_sto,max": f"{daten.theta_sto_max:.1f} °C",
            "Umgebungstemperatur ϑ_a": f"{daten.theta_a:.1f} °C",
            "Spez. Wärmekapazität c_w": f"{daten.cw:.3f} kJ/kgK",
        },
    }


def parametersatz_text(
    abschnitte: dict[str, dict[str, str]], *, platzhalter_zeigen: bool = False,
) -> str:
    """Parametersatz eines einzelnen Falls als Textblock.

    Nicht zutreffende Größen werden standardmäßig weggelassen; in der
    Gegenüberstellung zweier Fälle bleiben sie dagegen stehen (dort trägt die
    Platzhalter-Zeile die Information, dass der andere Fall dort rechnet).
    """
    teile = []
    for titel, werte in abschnitte.items():
        zeilen = [
            f"{name.ljust(NAMENSBREITE)}: {wert}"
            for name, wert in werte.items()
            if platzhalter_zeigen or not wert.startswith(PLATZHALTER)
        ]
        if zeilen:
            teile.append(titel + "\n" + "\n".join(zeilen))
    return "\n\n".join(teile)


def vergleiche_parametersaetze(
    links: dict[str, dict[str, str]], rechts: dict[str, dict[str, str]],
) -> dict[str, list[ParameterZeile]]:
    """Stellt zwei Parametersätze abschnittsweise gegenüber.

    Schlüssel, die nur in einem der beiden Sätze vorkommen, werden auf der
    anderen Seite mit dem Platzhalter aufgefüllt, damit auch unterschiedlich
    aufgebaute Fälle vollständig gegenübergestellt werden.
    """
    ergebnis: dict[str, list[ParameterZeile]] = {}
    for titel in list(links) + [t for t in rechts if t not in links]:
        werte_l, werte_r = links.get(titel, {}), rechts.get(titel, {})
        namen = list(werte_l) + [n for n in werte_r if n not in werte_l]
        ergebnis[titel] = [
            ParameterZeile(n, werte_l.get(n, PLATZHALTER), werte_r.get(n, PLATZHALTER))
            for n in namen
        ]
    return ergebnis


def unterschiede(abschnitte: dict[str, list[ParameterZeile]]) -> list[ParameterZeile]:
    """Alle Zeilen, die sich zwischen den beiden Fällen unterscheiden."""
    return [z for zeilen in abschnitte.values() for z in zeilen if z.unterschiedlich]


def sichtbare_zeilen(
    abschnitte: dict[str, list[ParameterZeile]], *, nur_unterschiede: bool = False,
) -> list[tuple[str, ParameterZeile]]:
    """Zeilen für die Anzeige.

    Größen, die in keinem der beiden Fälle in die Rechnung eingeflossen sind und
    dort denselben Platzhalter tragen, entfallen immer - sie sagen nichts aus.
    Eine abweichende Zeile bleibt dagegen in jedem Fall sichtbar, damit die
    Anzahl der Unterschiede zur angezeigten Tabelle passt.
    """
    return [
        (titel, z) for titel, zeilen in abschnitte.items() for z in zeilen
        if z.unterschiedlich or (not nur_unterschiede and not z.beidseitig_leer)
    ]


def vergleichstabelle_text(
    abschnitte: dict[str, list[ParameterZeile]],
    titel_links: str,
    titel_rechts: str,
    *,
    nur_unterschiede: bool = False,
) -> str:
    """Gegenüberstellung als Textblock; abweichende Zeilen sind mit * markiert."""
    zeilen_alle = [z for _, z in sichtbare_zeilen(abschnitte, nur_unterschiede=nur_unterschiede)]
    if not zeilen_alle:
        return ""

    breite_name = max([NAMENSBREITE] + [len(z.name) for z in zeilen_alle])
    breite_l = max([len(titel_links)] + [len(z.links) for z in zeilen_alle])
    breite_r = max([len(titel_rechts)] + [len(z.rechts) for z in zeilen_alle])

    kopf = (
        f"{'Parameter'.ljust(breite_name)} | {titel_links.ljust(breite_l)} | "
        f"{titel_rechts.ljust(breite_r)} |"
    )
    trenner = "-" * len(kopf)
    ausgabe = [kopf, trenner]

    for titel, zeilen in abschnitte.items():
        sichtbar = [z for t, z in sichtbare_zeilen({titel: zeilen}, nur_unterschiede=nur_unterschiede)]
        if not sichtbar:
            continue
        ausgabe.append(f"[{titel}]")
        for z in sichtbar:
            marke = "*" if z.unterschiedlich else " "
            ausgabe.append(
                f"{z.name.ljust(breite_name)} | {z.links.ljust(breite_l)} | "
                f"{z.rechts.ljust(breite_r)} | {marke}"
            )
    ausgabe.append(trenner)
    ausgabe.append("* = Wert unterscheidet sich zwischen den beiden Fällen")
    return "\n".join(ausgabe)
