import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.bedarf import aequivalente_personen
from core.modell import Eingabedaten
from core.norm_daten import GEBAEUDETYP_WOHNUNG
from core.speicherverbund import SERIE, Speicherverbund
from core.protokoll import (
    ABSCHNITT_ANLAGE, ABSCHNITT_TEMPERATUREN, ABSCHNITT_VERLUSTE, ABSCHNITT_ZAPFPROFIL,
    PLATZHALTER, parametersatz, parametersatz_text, sichtbare_zeilen, unterschiede,
    vergleiche_parametersaetze, vergleichstabelle_text,
)


def norm_fall(**kwargs) -> Eingabedaten:
    """Normauslegung wie in Modus A: Verluste nach Gl. 6/9 geschätzt."""
    return Eingabedaten(q_sb_sto=3.48, q_dis_spec=7.0, l_dis=150.0, **kwargs)


def monitoring_fall(**kwargs) -> Eingabedaten:
    """Monitoring wie in Modus B: gemessener Summenverlust statt Gl. 6/9."""
    return Eingabedaten(q_sb_sto=0.0, q_dis_spec=0.0, l_dis=0.0,
                        verlust_gesamt_je_minute=0.19, **kwargs)


def test_norm_fall_zeigt_geschaetzte_verluste():
    p = parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Lastprofil [%]")
    verluste = p[ABSCHNITT_VERLUSTE]
    assert verluste["Verlustansatz"] == "Norm-Schätzung (Gl. 6/9)"
    assert verluste["Bereitschaftsverlust q_sb,sto"] == "3.48 kWh/24h"
    assert verluste["Spez. Leitungsverlust q'_dis"] == "7.00 W/m"
    assert verluste["Rohrleitungslänge l_dis"] == "150.0 m"
    assert verluste["Gesamtverlust q_V,ges (Messung)"] == PLATZHALTER


def test_monitoring_fall_zeigt_gemessenen_verlust():
    p = parametersatz(monitoring_fall(), quelle_label="Monitoring (288 Rohwerte)", ist_monitoring=True)
    verluste = p[ABSCHNITT_VERLUSTE]
    assert verluste["Verlustansatz"] == "Messwert (ersetzt Gl. 6/9)"
    assert verluste["Gesamtverlust q_V,ges (Messung)"] == "0.190 kWh/min"
    assert verluste["Bereitschaftsverlust q_sb,sto"] == PLATZHALTER


def test_beide_verlustansaetze_belegen_dieselben_schluessel():
    """Voraussetzung für eine zeilenweise ausgerichtete Gegenüberstellung."""
    norm = parametersatz(norm_fall())[ABSCHNITT_VERLUSTE]
    mon = parametersatz(monitoring_fall(), ist_monitoring=True)[ABSCHNITT_VERLUSTE]
    assert list(norm) == list(mon)


def test_monitoring_fall_laesst_tagesbedarf_leer():
    """Bei Messdaten fließen Gl. 20/21 bzw. Anhang B.2.2 nicht in die Rechnung ein."""
    p = parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring")
    zapf = p[ABSCHNITT_ZAPFPROFIL]
    assert zapf["Datenquelle Zapfprofil"] == "Monitoring"
    assert zapf["Berechnungsverfahren Tagesbedarf"].startswith(PLATZHALTER)
    assert zapf["Personenzahl n_P"] == PLATZHALTER
    assert zapf["Lastprofil (Anhang B.1)"] == PLATZHALTER


def test_verfahren_c_parameter_landen_im_protokoll():
    daten = norm_fall(tagesbedarf_methode="C", wohnflaeche=70.0, anzahl_wohneinheiten=20,
                      wohnungstyp=GEBAEUDETYP_WOHNUNG)
    zapf = parametersatz(daten, methode_label="Verfahren C")[ABSCHNITT_ZAPFPROFIL]
    assert zapf["Bewohnbare Fläche A_h je Einheit"] == "70.0 m²"
    assert zapf["Anzahl Wohneinheiten"] == "20"
    # Der Zahlenwert hängt von den anwenderseitig eingetragenen Koeffizienten ab
    # (core/norm_daten.py), deshalb gegen die Berechnung geprüft statt fest.
    assert zapf["n_P,eq gesamt"] == f"{aequivalente_personen(daten).n_p_eq_gesamt:.3f}"
    assert "maßgebend: x (Obergrenze)" in zapf["Spez. Bedarf V_W,P,day (Gl. B.5)"]
    # Das nicht verwendete Verfahren A/B bleibt leer, damit die Gegenüberstellung passt
    assert zapf["Personenzahl n_P"] == PLATZHALTER


def test_monitoring_zeilen_werden_uebernommen():
    p = parametersatz(
        monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring",
        monitoring_zeilen={"Monitoring-Datei": "zapf.xlsx", "Analysezeitraum": "Ein Tag (24 h)"},
    )
    assert p[ABSCHNITT_ZAPFPROFIL]["Monitoring-Datei"] == "zapf.xlsx"
    assert p[ABSCHNITT_ZAPFPROFIL]["Auflösung Messdaten"] == PLATZHALTER


def test_einzelprotokoll_laesst_platzhalter_weg():
    text = parametersatz_text(parametersatz(norm_fall(), methode_label="Verfahren A"))
    assert "Bereitschaftsverlust q_sb,sto" in text
    assert "Gesamtverlust q_V,ges" not in text
    assert "Gebäudetyp (Anhang B.2.2)" not in text


def test_einzelprotokoll_kann_platzhalter_zeigen():
    text = parametersatz_text(parametersatz(norm_fall()), platzhalter_zeigen=True)
    assert "Gesamtverlust q_V,ges" in text


def test_vergleich_markiert_nur_echte_unterschiede():
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Norm"),
        parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring"),
    )
    namen = {z.name for z in unterschiede(abschnitte)}
    # Der Verlustansatz ist genau der Unterschied, um den es in Modus C geht
    assert {"Verlustansatz", "Bereitschaftsverlust q_sb,sto",
            "Gesamtverlust q_V,ges (Messung)"} <= namen
    # Gleich gebliebene Anlagenwerte dürfen nicht als Unterschied auftauchen
    assert "Bruttovolumen Speicher V_sto" not in namen
    assert "Zapftemperatur ϑ_draw" not in namen


def test_vergleich_erkennt_abweichende_anlagenparameter():
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(v_sto=3000.0)),
        parametersatz(monitoring_fall(v_sto=2000.0), ist_monitoring=True),
    )
    anlage = {z.name for z in abschnitte[ABSCHNITT_ANLAGE] if z.unterschiedlich}
    assert anlage == {"Bruttovolumen Speicher V_sto"}
    assert not [z for z in abschnitte[ABSCHNITT_TEMPERATUREN] if z.unterschiedlich]


def test_anlagenbericht_zeigt_fuehlerhoehe_und_einbauhoehe_ueber_boden():
    # h_sensor ist der Abstand von der Speicheroberkante (Gl. 5/10); der Fühler sitzt
    # bei h_sensor = 1,4 m und h_sto = 2,4 m also 1,0 m über dem Speicherboden.
    p = parametersatz(norm_fall(h_sto=2.4, h_sensor=1.4))
    anlage = p[ABSCHNITT_ANLAGE]
    assert anlage["Gesamthöhe Speicher h_sto"] == "2.40 m"
    assert anlage["Fühlerhöhe h_sensor (ab Oberkante)"] == "1.40 m"
    assert anlage["Einbauhöhe Fühler über Boden"] == "1.00 m"

    # Mittig sitzender Fühler: beide Angaben fallen zusammen.
    mittig = parametersatz(norm_fall(h_sto=2.4, h_sensor=1.2))[ABSCHNITT_ANLAGE]
    assert mittig["Fühlerhöhe h_sensor (ab Oberkante)"] == mittig["Einbauhöhe Fühler über Boden"] == "1.20 m"


def test_anlagenbericht_weist_speicherverbund_aus():
    # 2 x 1500 l in Serie, Fühler 0,6 m unter dem Deckel des zapfseitigen Speichers
    verbund = Speicherverbund(anzahl=2, v_je_speicher=1500.0, h_je_speicher=2.0,
                              h_sensor_je_speicher=0.6, q_sb_je_speicher=2.19, schaltung=SERIE)
    daten = Eingabedaten(v_sto=verbund.v_sto, h_sto=verbund.h_sto,
                         h_sensor=verbund.h_sensor, q_sb_sto=verbund.q_sb_sto)
    anlage = parametersatz(daten, verbund=verbund)[ABSCHNITT_ANLAGE]

    assert anlage["Speicheranordnung"] == "2 x 1500 l, " + SERIE
    assert anlage["Je Speicher (V / h / q_sb,sto)"] == "1500.0 l / 2.00 m / 2.19 kWh/24h"
    assert anlage["Bruttovolumen Speicher V_sto"] == "3000.0 l (Summe)"
    # Gerechnet wird mit der Stapelhöhe - das steht auch so im Bericht ...
    assert anlage["Gesamthöhe Speicher h_sto"] == "4.00 m (rechnerische Stapelhöhe)"
    # ... die Einbauhöhe bleibt aber die real messbare im jeweiligen Speicher
    # (nicht h_sto - h_sensor = 3,40 m, die Speicher stehen ja nebeneinander).
    assert anlage["Einbauhöhe Fühler über Boden"] == "1.40 m (in diesem Speicher)"


def test_anlagenbericht_ohne_verbund_bleibt_unveraendert():
    """Ein einzelner Speicher (oder gar keine Verbundangabe) darf die bisherigen
    Zeilen nicht verändern; die Verbundzeilen tragen dann den Platzhalter."""
    ohne = parametersatz(norm_fall(h_sto=2.4, h_sensor=1.4))[ABSCHNITT_ANLAGE]
    einzeln = parametersatz(
        norm_fall(h_sto=2.4, h_sensor=1.4),
        verbund=Speicherverbund(anzahl=1, h_je_speicher=2.4, h_sensor_je_speicher=1.4),
    )[ABSCHNITT_ANLAGE]
    assert ohne == einzeln
    assert ohne["Speicheranordnung"] == PLATZHALTER
    assert ohne["Gesamthöhe Speicher h_sto"] == "2.40 m"
    assert ohne["Einbauhöhe Fühler über Boden"] == "1.00 m"


def test_einbauhoehe_ist_differenz_zur_speicherhoehe():
    assert norm_fall(h_sto=2.4, h_sensor=1.4).h_sensor_ueber_boden == pytest.approx(1.0)
    # Fühler ganz oben (h_sensor = 0, Q_sto,ON = Q_sto,max) sitzt auf Höhe h_sto.
    assert norm_fall(h_sto=2.4, h_sensor=0.0).h_sensor_ueber_boden == pytest.approx(2.4)


def test_vergleich_fuellt_fehlende_schluessel_auf():
    abschnitte = vergleiche_parametersaetze(
        {"Nur links": {"a": "1", "b": "2"}},
        {"Nur rechts": {"c": "3"}},
    )
    assert abschnitte["Nur links"][0] == abschnitte["Nur links"][0]
    assert [z.rechts for z in abschnitte["Nur links"]] == [PLATZHALTER, PLATZHALTER]
    assert [z.links for z in abschnitte["Nur rechts"]] == [PLATZHALTER]


def test_vergleichstabelle_markiert_abweichungen_mit_stern():
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Norm"),
        parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring"),
    )
    text = vergleichstabelle_text(abschnitte, "Norm-Fall (Modus A)", "Monitoring-Fall (Modus B)")
    verlustzeile = next(z for z in text.split("\n") if z.startswith("Verlustansatz"))
    assert verlustzeile.rstrip().endswith("*")
    zapftemperatur = next(z for z in text.split("\n") if z.startswith("Zapftemperatur"))
    assert not zapftemperatur.rstrip().endswith("*")
    assert f"[{ABSCHNITT_VERLUSTE}]" in text


def test_vergleichstabelle_nur_unterschiede():
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Norm"),
        parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring"),
    )
    text = vergleichstabelle_text(abschnitte, "Norm", "Monitoring", nur_unterschiede=True)
    assert "Verlustansatz" in text
    assert "Zapftemperatur" not in text
    # Ein Abschnitt ohne Abweichung erscheint gar nicht
    assert f"[{ABSCHNITT_TEMPERATUREN}]" not in text


def test_beidseitig_leere_zeilen_entfallen():
    """Nutzt keiner der Fälle Verfahren C, tragen dessen Zeilen keine Information."""
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Norm"),
        parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring"),
    )
    namen = {z.name for _, z in sichtbare_zeilen(abschnitte)}
    assert "n_P,eq gesamt" not in namen
    assert "Personenzahl n_P" in namen          # nur im Norm-Fall belegt -> bleibt
    assert "Zapftemperatur ϑ_draw" in namen     # beidseitig gleich -> bleibt
    assert "n_P,eq gesamt" not in vergleichstabelle_text(abschnitte, "Norm", "Monitoring")


def test_beidseitig_leere_zeile_bleibt_bei_verfahren_c():
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(tagesbedarf_methode="C"), methode_label="Verfahren C"),
        parametersatz(monitoring_fall(), ist_monitoring=True),
    )
    assert "n_P,eq gesamt" in {z.name for _, z in sichtbare_zeilen(abschnitte)}


def test_abweichende_zeile_bleibt_trotz_platzhaltern_sichtbar():
    """Zwei verschiedene Platzhaltertexte sind ein echter Unterschied und dürfen
    nicht als 'beidseitig leer' verschwinden - sonst passt die Anzahl der
    gemeldeten Unterschiede nicht zur angezeigten Tabelle."""
    from core.protokoll import ParameterZeile
    abschnitte = {"A": [
        ParameterZeile("gleich leer", PLATZHALTER, PLATZHALTER),
        ParameterZeile("leer vs. Hinweis", PLATZHALTER, f"{PLATZHALTER} (aus Messdaten)"),
    ]}
    namen = {z.name for _, z in sichtbare_zeilen(abschnitte)}
    assert namen == {"leer vs. Hinweis"}
    assert len(unterschiede(abschnitte)) == len(sichtbare_zeilen(abschnitte, nur_unterschiede=True))


def test_vergleichstabelle_bleibt_spaltentreu():
    """Alle Datenzeilen einer Tabelle müssen dieselbe Spaltenstruktur haben."""
    abschnitte = vergleiche_parametersaetze(
        parametersatz(norm_fall(), methode_label="Verfahren A", quelle_label="Norm"),
        parametersatz(monitoring_fall(), ist_monitoring=True, quelle_label="Monitoring"),
    )
    zeilen = [z for z in vergleichstabelle_text(abschnitte, "Norm", "Monitoring").split("\n")
              if "|" in z]
    trennpositionen = {tuple(i for i, c in enumerate(z) if c == "|") for z in zeilen}
    assert len(trennpositionen) == 1, "Spalten der Vergleichstabelle sind nicht ausgerichtet"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
