"""Eingabedatenmodell für die TWW-Normauslegung nach ÖNORM EN 12831-3.

Die Feldnamen folgen den Symbolen aus Abschnitt 4.1 der Norm. Die
Standardwerte sind Startwerte der Oberfläche und stammen aus dem in der
Masterthesis untersuchten Gebäude; sie sind sämtlich zur Laufzeit
überschreibbar.
"""

from dataclasses import dataclass, field

from core.norm_daten import (
    GEBAEUDETYP_EFH,
    GEBAEUDETYP_WOHNUNG,
    STANDARD_PROFIL,
    X_MAX_SPEZ_VOLUMEN,
    Y_SPEZ_VOLUMEN,
)


@dataclass
class Eingabedaten:
    # --- 2. Tagesbedarf (Gl. 20 / Gl. 21 / Anhang B.2.2) ---
    tagesbedarf_methode: str = "A"
    # "A" = nach Personenzahl (Gl. 20), "B" = nach Einheiten (Gl. 21),
    # "C" = über die äquivalente Personenanzahl n_P,eq (Anhang B.2.2, Gl. B.1-B.5)
    n_personen: int = 268
    v_pro_person: float = 40.0       # V_W,P,day [l/(Person*d)]
    n_einheiten: int = 1
    v_pro_einheit: float = 70.0      # V_W,f,day [l/(Einheit*d)]
    # Vorbelegt mit dem in core/norm_daten.py festgelegten Standardprofil
    # (Anhang B.1), damit das Modell unabhängig davon nutzbar ist, welche
    # Profile der Anwender in core/norm_werte_lokal.py eingetragen hat.
    gewaehltes_profil: str = field(default_factory=lambda: STANDARD_PROFIL)

    # --- 2b. Verfahren C: äquivalente Personenanzahl (Anhang B.2.2) ---
    wohnungstyp: str = GEBAEUDETYP_WOHNUNG   # Gl. B.3/B.4 bzw. B.1/B.2
    wohnflaeche: float = 70.0                # bewohnbare Fläche A_h je Wohneinheit [m²]
    anzahl_wohneinheiten: int = 1            # gleichartige Einheiten am selben TWW-Strang [-]
    x_max_spez_volumen: float = X_MAX_SPEZ_VOLUMEN  # x in Gl. B.5 [l/(Person*d)]
    y_spez_volumen: float = Y_SPEZ_VOLUMEN          # y in Gl. B.5 [l/(m²*d)]

    # --- 3. Anlagenparameter Speicher & Erzeuger ---
    speicher_typ: str = "Speicherladesystem"  # oder "Gemischtes Speichersystem"
    v_sto: float = 3000.0     # Speichervolumen [l]
    h_sto: float = 2.0        # Gesamthöhe Speicher [m]
    h_sensor: float = 0.6     # Fühlerhöhe [m], gemessen ab Speicheroberkante nach unten
    # (siehe Gl. 5/10: h_sensor = 0 -> Fühler ganz oben, Q_sto,ON = Q_sto,max;
    #  h_sensor = h_sto -> Fühler ganz unten, Q_sto,ON = 0)
    f_l: float = 1.0          # Ladungsfaktor [-]
    phi_n: float = 70.5       # Nennleistung Erzeuger [kW]
    t_lag_hg: float = 4.0     # Zeitverzögerung Wärmeerzeuger [min]
    theta_ch_hg: float | None = None  # Ladetemperatur Wärmeerzeuger [°C]; None -> theta_sto_max + 5 (Annahme)

    # --- 4. Verlust- und Netzparameter ---
    q_sb_sto: float = 3.48    # Bereitschaftsverlust Speicher [kWh/24h]
    q_dis_spec: float = 7.0   # spez. Leitungsverlust [W/m]
    l_dis: float = 150.0      # Rohrleitungslänge [m]
    verlust_gesamt_je_minute: float | None = None
    # gemessener Summenverlust Speicher+Verteilung [kWh/min]; überschreibt bei
    # Angabe (!= None) die Norm-Schätzung aus q_sb_sto/q_dis_spec (Gl. 6/9)

    # --- 5. Physikalische Konstanten / Temperaturen ---
    cw: float = 4.18          # spez. Wärmekapazität Wasser [kJ/kgK]
    theta_draw: float = 60.0  # Zapftemperatur [°C]
    theta_c: float = 10.0     # Kaltwassertemperatur [°C]
    theta_sto_max: float = 63.0  # max. Speichertemperatur [°C]
    theta_a: float = 15.0     # Umgebungstemperatur Aufstellraum [°C]

    def ist_gemischtes_system(self) -> bool:
        return self.speicher_typ == "Gemischtes Speichersystem"

    @property
    def h_sensor_ueber_boden(self) -> float:
        """Tatsächliche Einbauhöhe des Temperaturfühlers über dem Speicherboden [m].

        h_sensor geht in Gl. 5/10 als Abstand von der Speicheroberkante ein,
        nicht als Höhe über dem Boden: h_sensor = 1,4 m bei h_sto = 2,4 m
        bedeutet einen Fühler 1,0 m über dem Boden. Für die Bauausführung (und
        damit für den Anlagenbericht) ist diese Einbauhöhe die anschaulichere
        Angabe; gerechnet wird unverändert mit h_sensor.
        """
        return self.h_sto - self.h_sensor

    def validieren(self) -> list[str]:
        """Einfache Plausibilitätsprüfung, gibt Liste von Fehlermeldungen zurück."""
        fehler = []
        if self.theta_c >= self.theta_draw:
            fehler.append("Kaltwassertemperatur muss kleiner als Zapftemperatur sein.")
        if self.theta_draw > self.theta_sto_max:
            fehler.append("Zapftemperatur ist höher als max. Speichertemperatur (Nacherhitzung erforderlich).")
        if self.h_sensor >= self.h_sto:
            fehler.append("Fühlerhöhe muss kleiner als Speicher-Gesamthöhe sein.")
        if self.v_sto <= 0 or self.phi_n <= 0:
            fehler.append("Speichervolumen und Erzeugerleistung müssen größer als 0 sein.")
        if self.tagesbedarf_methode == "C":
            if self.wohnungstyp not in (GEBAEUDETYP_WOHNUNG, GEBAEUDETYP_EFH):
                fehler.append(f"Unbekannter Gebäudetyp für Verfahren C: '{self.wohnungstyp}'.")
            if self.wohnflaeche <= 0:
                fehler.append("Die bewohnbare Fläche A_h muss größer als 0 m² sein.")
            if self.anzahl_wohneinheiten < 1:
                fehler.append("Es muss mindestens eine Wohneinheit berücksichtigt werden.")
        return fehler
