import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from core.modell import Eingabedaten
from core.bedarf import (
    aequivalente_personen, n_p_eq, n_p_eq_max, tagesvolumen_liter, zapfprofil_minutenwerte,
)
from core.norm_daten import (
    GEBAEUDETYP_EFH, GEBAEUDETYP_KOEFFIZIENTEN, GEBAEUDETYP_WOHNUNG,
    N_P_EQ_BEZUGSWERT, N_P_EQ_DAEMPFUNG, N_P_EQ_STEIGUNG,
)
from core.versorgung import (
    berechne_versorgungskennlinie, q_sto_max, q_sto_on, q_sto_min,
    tagesauswertung, Einschaltzyklus, verlust_gesamt_je_minute,
    verlust_speicher_je_minute, verlust_verteilung_je_minute, MINUTEN_PRO_TAG,
    erholungsanalyse,
)
from core.vergleich import vergleiche, verlustbilanz
from core.investition import optimiere, bewerte_lauf
from core.projekt import (
    Datei as ProjektDatei, ProjektFehler, als_json as projekt_als_json,
    lade as projekt_laden, sammle_parameter, SLOT_WP_KATALOG, SLOT_BEMESSUNGSTAG,
)


def test_gl20_tagesvolumen():
    d = Eingabedaten(tagesbedarf_methode="A", n_personen=268, v_pro_person=40.0)
    assert tagesvolumen_liter(d) == 268 * 40.0


# Die Koeffizienten des Verfahrens C sind nicht Teil des Programms, sondern
# werden vom Anwender aus seinem Normexemplar eingetragen (core/norm_daten.py,
# siehe core/norm_werte_vorlage.py). Die folgenden Tests prüfen deshalb den
# Rechenweg gegen den jeweils geladenen Parametersatz, nicht gegen feste Zahlen.
# Sie laufen dadurch sowohl mit der mitgelieferten Vorlage als auch mit
# eingetragenen Normwerten.


@pytest.mark.parametrize("typ", [GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH])
def test_gl_b1_b3_n_p_eq_max_hat_drei_zweige(typ):
    flaeche_min, flaeche_bezug, flaechenfaktor = GEBAEUDETYP_KOEFFIZIENTEN[typ]

    # unterhalb der unteren Intervallgrenze -> konstant 1
    assert n_p_eq_max(flaeche_min / 2, typ) == 1.0

    # dazwischen -> linear abfallend zur oberen Grenze hin
    mitte = (flaeche_min + flaeche_bezug) / 2
    erwartet = N_P_EQ_BEZUGSWERT - N_P_EQ_STEIGUNG * (flaeche_bezug - mitte)
    assert abs(n_p_eq_max(mitte, typ) - erwartet) < 1e-12

    # oberhalb der oberen Grenze -> rein flächenproportional
    gross = flaeche_bezug * 1.5
    assert abs(n_p_eq_max(gross, typ) - flaechenfaktor * gross) < 1e-12


@pytest.mark.parametrize("typ", [GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH])
def test_n_p_eq_max_ist_an_den_stuetzstellen_stetig(typ):
    """Die Zweige müssen an beiden Intervallgrenzen denselben Wert liefern.

    Trifft das zu, sind die in der Norm offen gelassenen Intervallgrenzen ohne
    Einfluss. Schlägt der Test fehl, ist der eingetragene Parametersatz in sich
    nicht schlüssig - dann sind die Werte in core/norm_werte_lokal.py zu prüfen.
    """
    flaeche_min, flaeche_bezug, flaechenfaktor = GEBAEUDETYP_KOEFFIZIENTEN[typ]
    assert abs(n_p_eq_max(flaeche_min, typ) - 1.0) < 1e-12
    assert abs(n_p_eq_max(flaeche_bezug, typ) - N_P_EQ_BEZUGSWERT) < 1e-12
    assert abs(flaechenfaktor * flaeche_bezug - N_P_EQ_BEZUGSWERT) < 1e-12


def test_gl_b2_b4_daempfung_oberhalb_des_bezugswerts():
    flaeche_min, flaeche_bezug, _ = GEBAEUDETYP_KOEFFIZIENTEN[GEBAEUDETYP_WOHNUNG]

    # unterhalb des Bezugswerts bleibt n_P,eq unverändert
    mitte = (flaeche_min + flaeche_bezug) / 2
    assert abs(n_p_eq(mitte, GEBAEUDETYP_WOHNUNG) - n_p_eq_max(mitte, GEBAEUDETYP_WOHNUNG)) < 1e-12

    # oberhalb wird der überschießende Anteil gedämpft
    gross = flaeche_bezug * 1.5
    maximum = n_p_eq_max(gross, GEBAEUDETYP_WOHNUNG)
    assert maximum > N_P_EQ_BEZUGSWERT
    erwartet = N_P_EQ_BEZUGSWERT + N_P_EQ_DAEMPFUNG * (maximum - N_P_EQ_BEZUGSWERT)
    assert abs(n_p_eq(gross, GEBAEUDETYP_WOHNUNG) - erwartet) < 1e-12


def test_verfahren_c_gl_b5_obergrenze_x_greift():
    """Bei großer Fläche je Person wird x maßgebend (erster Term von Gl. B.5)."""
    _, flaeche_bezug, _ = GEBAEUDETYP_KOEFFIZIENTEN[GEBAEUDETYP_WOHNUNG]
    d = Eingabedaten(
        tagesbedarf_methode="C", wohnungstyp=GEBAEUDETYP_WOHNUNG,
        wohnflaeche=flaeche_bezug * 1.5,
    )
    eq = aequivalente_personen(d)

    assert abs(eq.n_p_eq - n_p_eq(d.wohnflaeche, GEBAEUDETYP_WOHNUNG)) < 1e-12
    # y * A_h / n_P,eq deutlich über x -> x begrenzt
    assert d.y_spez_volumen * d.wohnflaeche / eq.n_p_eq > d.x_max_spez_volumen
    assert eq.x_greift
    assert abs(eq.v_w_p_day - d.x_max_spez_volumen) < 1e-12
    assert abs(eq.v_w_day - d.x_max_spez_volumen * eq.n_p_eq) < 1e-9
    assert abs(tagesvolumen_liter(d) - eq.v_w_day) < 1e-12


def test_verfahren_c_gl_b5_flaechenterm_greift_bei_kleiner_wohnung():
    """Bei kleiner Fläche ist der flächenbezogene Term von Gl. B.5 maßgebend."""
    flaeche_min, _, _ = GEBAEUDETYP_KOEFFIZIENTEN[GEBAEUDETYP_WOHNUNG]
    d = Eingabedaten(
        tagesbedarf_methode="C", wohnungstyp=GEBAEUDETYP_WOHNUNG, wohnflaeche=flaeche_min / 2,
    )
    eq = aequivalente_personen(d)

    assert abs(eq.n_p_eq - 1.0) < 1e-12
    flaechenbezogen = d.y_spez_volumen * d.wohnflaeche / eq.n_p_eq
    assert flaechenbezogen < d.x_max_spez_volumen
    assert not eq.x_greift
    assert abs(eq.v_w_p_day - flaechenbezogen) < 1e-12
    assert abs(eq.v_w_day - flaechenbezogen) < 1e-12


def test_verfahren_c_skaliert_linear_mit_der_anzahl_wohneinheiten():
    eine = Eingabedaten(tagesbedarf_methode="C", wohnflaeche=70.0, anzahl_wohneinheiten=1)
    zwanzig = Eingabedaten(tagesbedarf_methode="C", wohnflaeche=70.0, anzahl_wohneinheiten=20)
    assert abs(tagesvolumen_liter(zwanzig) - 20 * tagesvolumen_liter(eine)) < 1e-9
    je_einheit = aequivalente_personen(eine).n_p_eq
    assert abs(aequivalente_personen(zwanzig).n_p_eq_gesamt - 20 * je_einheit) < 1e-9


def test_verfahren_c_zapfprofil_summe_ergibt_tagesvolumen():
    d = Eingabedaten(tagesbedarf_methode="C", wohnflaeche=70.0, anzahl_wohneinheiten=20)
    profil = zapfprofil_minutenwerte(d)
    assert len(profil) == 1440
    assert abs(profil.sum() - tagesvolumen_liter(d)) < 1e-6


def test_verfahren_c_validierung_meldet_unzulaessige_flaeche():
    d = Eingabedaten(tagesbedarf_methode="C", wohnflaeche=0.0)
    assert any("A_h" in f for f in d.validieren())


def test_zapfprofil_summe_ergibt_tagesvolumen():
    d = Eingabedaten()
    profil = zapfprofil_minutenwerte(d)
    assert len(profil) == 1440
    assert abs(profil.sum() - tagesvolumen_liter(d)) < 1e-6


def test_speicherladesystem_q_sto_min_ist_null():
    d = Eingabedaten(speicher_typ="Speicherladesystem")
    assert q_sto_min(d) == 0.0


def test_gemischtes_system_q_sto_min_positiv():
    d = Eingabedaten(speicher_typ="Gemischtes Speichersystem")
    assert q_sto_min(d) > 0.0


def test_simulation_deckt_bedarf_bei_ausreichender_dimensionierung():
    d = Eingabedaten()  # Standardwerte des Eingabemodells
    profil = zapfprofil_minutenwerte(d)
    ergebnis = berechne_versorgungskennlinie(d, profil)

    assert len(ergebnis.ladezustand) == 1440
    print(f"Q_sto,max = {ergebnis.q_sto_max:.2f} kWh")
    print(f"Q_sto,ON  = {ergebnis.q_sto_on:.2f} kWh")
    print(f"Q_sto,min = {ergebnis.q_sto_min:.2f} kWh")
    print(f"min(SOC)  = {ergebnis.ladezustand.min():.2f} kWh")
    print(f"Zyklen    = {len(ergebnis.zyklen)}")
    print(f"Gesamtlaufzeit = {sum(z.dauer_min for z in ergebnis.zyklen)} min")
    print(f"Endladezustand = {ergebnis.ladezustand_ende:.2f} kWh (Start war {ergebnis.q_sto_max:.2f} kWh)")

    # Norm-Kriterium (6.4.3.3): Anlage deckt den Bedarf nur, wenn SOC nie unter Q_sto,min fällt
    assert ergebnis.ladezustand.min() >= ergebnis.q_sto_min - 1e-6, (
        "Anlage ist nach Norm-Kriterium unterdimensioniert (SOC < Q_sto,min)"
    )


def test_tagesauswertung_zerlegt_die_woche_in_sieben_tage():
    """Wochenprüfung in Modus A: derselbe Normtag 7x hintereinander."""
    d = Eingabedaten()
    woche = np.tile(zapfprofil_minutenwerte(d), 7)
    ergebnis = berechne_versorgungskennlinie(d, woche)
    tage = tagesauswertung(woche, ergebnis)

    assert [t.tag for t in tage] == [1, 2, 3, 4, 5, 6, 7]
    # Jeder Tag trägt dasselbe Zapfvolumen, die Summe ergibt den Wochenbedarf
    for t in tage:
        assert t.zapfvolumen_l == pytest.approx(tagesvolumen_liter(d))
    assert sum(t.zapfvolumen_l for t in tage) == pytest.approx(float(woche.sum()))

    # Laufzeiten und Zyklen der Tage summieren sich zum Gesamtlauf
    assert sum(t.laufzeit_min for t in tage) == sum(z.dauer_min for z in ergebnis.zyklen)
    assert sum(t.zyklen for t in tage) == len(ergebnis.zyklen)

    # Der letzte Tageswert ist der Endladezustand des Gesamtlaufs
    assert tage[-1].soc_ende == pytest.approx(ergebnis.ladezustand_ende)
    assert min(t.soc_min for t in tage) == pytest.approx(float(ergebnis.ladezustand.min()))


def test_tagesauswertung_teilt_einen_zyklus_ueber_mitternacht_auf():
    """Ein über Mitternacht laufender Zyklus zählt beim Starttag, seine Laufzeit
    wird aber minutengenau auf beide Tage verteilt."""
    d = Eingabedaten()
    woche = np.tile(zapfprofil_minutenwerte(d), 2)
    ergebnis = berechne_versorgungskennlinie(d, woche)
    # Zyklus künstlich über die Tagesgrenze legen (1380 -> 1500)
    ergebnis.zyklen = [Einschaltzyklus(1380, 1500)]
    tag1, tag2 = tagesauswertung(woche, ergebnis)

    assert (tag1.zyklen, tag2.zyklen) == (1, 0)
    assert (tag1.laufzeit_min, tag2.laufzeit_min) == (60, 60)


def test_tagesauswertung_eines_einzelnen_tages():
    d = Eingabedaten()
    profil = zapfprofil_minutenwerte(d)
    tage = tagesauswertung(profil, berechne_versorgungskennlinie(d, profil))
    assert len(tage) == 1 and tage[0].tag == 1


def _zwei_faelle(daten_soll, daten_ist):
    """Zwei gerechnete Fälle über denselben Auslegungstag, für den Vergleich."""
    profil = zapfprofil_minutenwerte(daten_soll)
    erg_soll = berechne_versorgungskennlinie(daten_soll, profil)
    erg_ist = berechne_versorgungskennlinie(daten_ist, profil)
    return profil, erg_soll, erg_ist


def test_verlustbilanz_norm_teilt_in_gl6_und_gl9_auf():
    d = Eingabedaten(q_sb_sto=3.48, q_dis_spec=7.0, l_dis=150.0)
    b = verlustbilanz(d, MINUTEN_PRO_TAG)

    assert not b.ist_messwert
    assert b.speicher_kwh_tag == pytest.approx(verlust_speicher_je_minute(d) * MINUTEN_PRO_TAG)
    assert b.verteilung_kwh_tag == pytest.approx(verlust_verteilung_je_minute(d) * MINUTEN_PRO_TAG)
    # Gl. 6 + Gl. 9 ergeben zusammen genau den Wert, der in der Simulation abgezogen wird
    assert b.speicher_kwh_tag + b.verteilung_kwh_tag == pytest.approx(b.gesamt_kwh_tag)
    assert b.gesamt_kwh_tag == pytest.approx(verlust_gesamt_je_minute(d) * MINUTEN_PRO_TAG)


def test_verlustbilanz_messwert_laesst_einzelposten_offen():
    d = Eingabedaten(verlust_gesamt_je_minute=0.05)
    b = verlustbilanz(d, MINUTEN_PRO_TAG)

    assert b.ist_messwert
    assert b.speicher_kwh_tag is None and b.verteilung_kwh_tag is None
    assert b.gesamt_kwh_tag == pytest.approx(0.05 * MINUTEN_PRO_TAG)


def test_verlustbilanz_skaliert_mit_dem_auslegungszeitraum():
    d = Eingabedaten(verlust_gesamt_je_minute=0.02)
    tag = verlustbilanz(d, MINUTEN_PRO_TAG)
    woche = verlustbilanz(d, 7 * MINUTEN_PRO_TAG)

    assert woche.gesamt_kwh_tag == pytest.approx(tag.gesamt_kwh_tag)
    assert woche.gesamt_kwh_zeitraum == pytest.approx(7 * tag.gesamt_kwh_zeitraum)


def test_vergleich_weist_verlustabweichung_aus():
    soll = Eingabedaten()
    ist = Eingabedaten(verlust_gesamt_je_minute=verlust_gesamt_je_minute(soll) * 2.0)
    profil, erg_soll, erg_ist = _zwei_faelle(soll, ist)

    v = vergleiche(profil, erg_soll, profil, erg_ist, soll, ist)

    assert v.diff_verlust_pct == pytest.approx(100.0)
    assert v.verlust_ist.gesamt_kwh_tag == pytest.approx(2 * v.verlust_soll.gesamt_kwh_tag)


def test_vergleich_ohne_parametersaetze_laesst_verlustfelder_leer():
    d = Eingabedaten()
    profil, erg_soll, erg_ist = _zwei_faelle(d, d)

    v = vergleiche(profil, erg_soll, profil, erg_ist)

    assert v.verlust_soll is None and v.verlust_ist is None and v.diff_verlust_pct is None


def test_energiebedarf_ist_zapfenergie_und_bleibt_von_verlusten_unberuehrt():
    """Absicherung der Kennzahl: 'Gesamt-Energiebedarf' ist die Zapfenergie nach
    Gl. 1. Zwei Fälle mit identischem Zapfprofil, aber stark unterschiedlichem
    Verlustansatz müssen dort denselben Wert zeigen - der Verlustunterschied
    schlägt sich stattdessen in Laufzeit und SOC_min nieder."""
    soll = Eingabedaten()
    ist = Eingabedaten(verlust_gesamt_je_minute=verlust_gesamt_je_minute(soll) * 2.5)
    profil, erg_soll, erg_ist = _zwei_faelle(soll, ist)

    v = vergleiche(profil, erg_soll, profil, erg_ist, soll, ist)

    assert v.diff_energie_pct == pytest.approx(0.0)
    assert v.diff_verlust_pct == pytest.approx(150.0)
    # Der Mehrverlust muss vom Erzeuger nachgeladen werden - die Laufzeit steigt.
    assert v.laufzeit_ist_min > v.laufzeit_soll_min
    # SOC_min verschiebt sich ebenfalls, aber nicht zwingend nach unten: höhere
    # Verluste erreichen den Einschaltpunkt früher, der Tiefpunkt liegt dann an
    # einer anderen Stelle im Zyklus. Geprüft wird deshalb nur, dass der
    # Verlustunterschied den Ladezustandsverlauf überhaupt erreicht.
    assert v.soc_min_ist != pytest.approx(v.soc_min_soll)


def _wp_katalog(*leistungen_kw):
    import pandas as pd
    return pd.DataFrame([
        {"hersteller": "H", "produkt": f"WP{p:.0f}", "leistung_kw": p,
         "investkosten": 1000.0 * p, "platzbedarf_m3": 1.0}
        for p in leistungen_kw
    ])


def _speicher_katalog(*volumina_l):
    import pandas as pd
    return pd.DataFrame([
        {"hersteller": "S", "produkt": f"SP{v:.0f}", "volumen_l": v, "material": "Edelstahl",
         "investkosten": 2.0 * v, "q_sb_sto": 0.05 * (v / 100) ** (2 / 3)}
        for v in volumina_l
    ])


def _woche(daten, faktor=1.0):
    """Sieben aneinandergehängte Normtage als Bemessungswoche."""
    return np.tile(zapfprofil_minutenwerte(daten)[:MINUTEN_PRO_TAG], 7) * faktor


def test_erholung_erkennt_durchlaufenden_erzeuger():
    """Eine deutlich unterdimensionierte WP lädt den Speicher nie wieder voll -
    über eine Woche muss das als fehlende Erholung auffallen, obwohl das
    Norm-Kriterium beim Speicherladesystem (Q_sto,min = 0) noch hält."""
    d = Eingabedaten(v_sto=500.0, phi_n=16.0)
    ergebnis = berechne_versorgungskennlinie(d, _woche(d))
    erholung = erholungsanalyse(ergebnis)

    assert not erholung.ist_erholt
    assert erholung.max_abstand_min > MINUTEN_PRO_TAG


def test_erholung_bei_ausreichender_dimensionierung():
    d = Eingabedaten(v_sto=3000.0, phi_n=70.5)
    erholung = erholungsanalyse(berechne_versorgungskennlinie(d, _woche(d)))

    assert erholung.ist_erholt
    assert erholung.anzahl_vollladungen >= 7


def test_laufzeitgrenze_gilt_je_kalendertag_nicht_je_zeitraum():
    """Über eine Woche summiert sich die Laufzeit weit über 18 h - geprüft
    werden darf nur der längste EINZELNE Tag, sonst fällt jede Woche durch."""
    d = Eingabedaten(v_sto=3000.0, phi_n=70.5)
    lauf = bewerte_lauf(d, _woche(d), max_laufzeit_h=18.0)

    assert lauf.tage == 7
    assert lauf.laufzeit_min > 18 * 60          # Summe über die Woche
    assert lauf.laufzeit_max_tag_min <= 18 * 60  # längster Einzeltag
    assert lauf.erfuellt_laufzeit


def test_laufzeitgrenze_schliesst_dauerlaeufer_aus():
    d = Eingabedaten(v_sto=500.0, phi_n=16.0)
    lauf = bewerte_lauf(d, zapfprofil_minutenwerte(d), max_laufzeit_h=18.0)

    assert lauf.laufzeit_max_tag_min > 18 * 60
    assert not lauf.erfuellt_laufzeit
    assert not lauf.zulaessig


def test_erholung_geht_nur_auf_anforderung_in_die_zulaessigkeit_ein():
    """Über einen einzelnen Tag kann der Abstand zwischen zwei Vollladungen
    24 h nicht überschreiten - die Bedingung wäre dort wirkungslos und darf
    die Zulässigkeit nicht scheinbar bestätigen."""
    d = Eingabedaten(v_sto=500.0, phi_n=16.0)
    tag = zapfprofil_minutenwerte(d)

    ohne = bewerte_lauf(d, tag, max_laufzeit_h=24.0, erholung_pruefen=False)
    mit = bewerte_lauf(d, tag, max_laufzeit_h=24.0, erholung_pruefen=True)

    assert ohne.erholung_max_abstand_min <= MINUTEN_PRO_TAG
    assert ohne.zulaessig == mit.zulaessig


def test_optimiere_ohne_woche_bleibt_beim_norm_kriterium():
    """Modus D ruft dieselbe Funktion ohne Bemessungswoche auf - dort darf sich
    an der bisherigen Bewertung nichts ändern."""
    d = Eingabedaten()
    tag = zapfprofil_minutenwerte(d)
    komb = optimiere(d, tag, _wp_katalog(16.0, 70.5), _speicher_katalog(500.0, 3000.0))

    assert all(k.woche is None for k in komb)
    for k in komb:
        assert k.zulaessig == (k.soc_min_kwh >= k.q_sto_min_kwh)


def test_optimiere_mit_woche_verwirft_was_nur_am_tag_besteht():
    """Kernpunkt der Erweiterung: eine Kombination, die den Bemessungstag noch
    schafft, aber im Dauerbetrieb der Woche nicht mehr hochkommt, darf nicht
    mehr als zulässig gelten."""
    d = Eingabedaten()
    tag = zapfprofil_minutenwerte(d)
    komb = optimiere(
        d, tag, _wp_katalog(16.0, 70.5), _speicher_katalog(500.0, 3000.0),
        zapfprofil_woche=_woche(d), max_laufzeit_h=18.0,
    )
    nach_produkt = {(k.wp_produkt, k.speicher_produkt): k for k in komb}

    klein = nach_produkt[("WP16", "SP500")]
    gross = nach_produkt[("WP70", "SP3000")]

    assert gross.zulaessig
    assert not klein.zulaessig
    assert klein.scheitert_an()          # nennt den Grund im Klartext
    assert all(k.woche is not None for k in komb)


def test_scheitert_an_nennt_die_verletzte_bedingung():
    d = Eingabedaten()
    komb = optimiere(
        d, zapfprofil_minutenwerte(d), _wp_katalog(16.0), _speicher_katalog(500.0),
        zapfprofil_woche=_woche(d), max_laufzeit_h=18.0,
    )
    gruende = " | ".join(komb[0].scheitert_an())

    assert "Laufzeit" in gruende or "Vollladung" in gruende


def test_projekt_sammelt_nur_eingaben_keine_ergebnisse():
    zustand = {
        "eg_n_personen": 268,
        "eg_theta_draw": 45.0,
        "eg_verlust_aus_messung": True,
        "rabatt_wp_Viessmann": 42.0,
        "wp_aktiv_Viessmann": True,
        "_halt_eg_n_personen": 268,          # Schattenschlüssel: nicht sichern
        "fall_norm": object(),               # Rechenergebnis: nicht sichern
        "_monitoring_daten": {"a": 1},       # Zwischenstand: nicht sichern
        "irgendwas": "fremd",                # fremder Schlüssel: nicht sichern
    }
    parameter = sammle_parameter(zustand)

    assert set(parameter) == {
        "eg_n_personen", "eg_theta_draw", "eg_verlust_aus_messung",
        "rabatt_wp_Viessmann", "wp_aktiv_Viessmann",
    }


def test_projekt_rundreise_erhaelt_parameter_und_dateien():
    parameter = {"eg_n_personen": 268, "eg_theta_draw": 45.0, "eg_modus": "B: Reales Monitoring (Messdaten)"}
    dateien = {
        SLOT_WP_KATALOG: ProjektDatei(name="wp.xlsx", inhalt=b"PK\x03\x04binaerinhalt"),
        SLOT_BEMESSUNGSTAG: ProjektDatei(name="tag.xlsx", inhalt=bytes(range(256))),
    }

    zurueck = projekt_laden(projekt_als_json(parameter, dateien))

    assert zurueck.parameter == parameter
    assert zurueck.anzahl_dateien == 2
    assert zurueck.dateien[SLOT_WP_KATALOG].name == "wp.xlsx"
    # Byte-für-Byte identisch: die Datei muss beim Laden durch denselben
    # Excel-Leser gehen wie beim Hochladen.
    assert zurueck.dateien[SLOT_BEMESSUNGSTAG].inhalt == bytes(range(256))


def test_projekt_ohne_dateien_bleibt_gueltig():
    zurueck = projekt_laden(projekt_als_json({"eg_v_sto": 3000.0}))

    assert zurueck.parameter == {"eg_v_sto": 3000.0}
    assert zurueck.anzahl_dateien == 0


def test_projekt_weist_fremde_datei_ab():
    with pytest.raises(ProjektFehler, match="nicht aus diesem Tool"):
        projekt_laden(b'{"foo": 1}')

    with pytest.raises(ProjektFehler, match="kein lesbares JSON"):
        projekt_laden(b"keine json-datei")


def test_projekt_weist_zu_neue_formatversion_ab():
    import json as _json
    inhalt = _json.loads(projekt_als_json({"eg_v_sto": 3000.0}))
    inhalt["version"] = 999
    with pytest.raises(ProjektFehler, match="Format-Version"):
        projekt_laden(_json.dumps(inhalt).encode("utf-8"))


def test_projekt_verwirft_fremde_schluessel_beim_laden():
    """Eine manipulierte oder veraltete Datei darf keine beliebigen Werte in
    den Widget-Zustand schreiben."""
    import json as _json
    inhalt = _json.loads(projekt_als_json({"eg_v_sto": 3000.0}))
    inhalt["parameter"]["boeser_schluessel"] = "x"
    inhalt["parameter"]["eg_objekt"] = {"kein": "skalar"}

    zurueck = projekt_laden(_json.dumps(inhalt).encode("utf-8"))

    assert zurueck.parameter == {"eg_v_sto": 3000.0}


def test_projekt_meldet_beschaedigte_datei():
    import json as _json
    inhalt = _json.loads(projekt_als_json({}, {SLOT_WP_KATALOG: ProjektDatei("wp.xlsx", b"abc")}))
    inhalt["dateien"][SLOT_WP_KATALOG]["inhalt_b64"] = "kein!!base64!!"
    with pytest.raises(ProjektFehler, match="beschädigt"):
        projekt_laden(_json.dumps(inhalt).encode("utf-8"))


if __name__ == "__main__":
    test_gl20_tagesvolumen()
    test_zapfprofil_summe_ergibt_tagesvolumen()
    test_speicherladesystem_q_sto_min_ist_null()
    test_gemischtes_system_q_sto_min_positiv()
    test_simulation_deckt_bedarf_bei_ausreichender_dimensionierung()
    print("\nAlle Tests erfolgreich.")
