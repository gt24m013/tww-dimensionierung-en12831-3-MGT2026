"""Mehrere gleich große Speicher als ein Rechenspeicher (Speicherverbund).

Die Norm rechnet mit EINEM Speicher: V_sto, h_sto und h_sensor beschreiben ein
einzelnes Gefäß. Real wird ein großes Volumen aber meist aus mehreren kleineren
Speichern aufgebaut (z. B. 2 x 1500 l statt 1 x 3000 l). Dieses Modul rechnet
eine solche Anordnung in genau die Größen um, mit denen core/versorgung.py
arbeitet.

Möglich ist das, weil die Geometrie nur als Verhältnis h_sensor/h_sto in die
Rechnung eingeht (Gl. 10, bei gemischten Systemen zusätzlich Gl. 5) und das
Volumen nur als Summe (Gl. 4):

* Serie (hintereinander durchströmt): Kaltwasser tritt unten in den ersten
  Speicher ein, gezapft wird oben aus dem letzten. Die Schichtung durchläuft
  die Gefäße nacheinander, der Verbund verhält sich deshalb wie EIN Speicher
  der Höhe n * h. h_sensor zählt ab der Oberkante des zapfseitigen Speichers
  durch den Stapel nach unten - ein Fühler im ersten (kalten) Speicher liegt
  also um (n - 1) * h tiefer als derselbe Fühler im letzten Speicher.
* Parallel (gleichzeitig durchströmt, z. B. Tichelmann): alle Speicher werden
  zugleich entladen und entschichten synchron. Der Verbund verhält sich wie EIN
  Speicher der Einzelhöhe h mit dem n-fachen Volumen; die Fühlerposition im
  Verbund entspricht der im Einzelspeicher.

Der Bereitschaftsverlust ist in beiden Fällen die Summe der Einzelverluste - n
kleine Speicher verlieren wegen des ungünstigeren Oberflächen-Volumen-
Verhältnisses mehr als ein einzelner Speicher gleichen Gesamtvolumens.

Nicht abgebildet ist die Durchmischung am Übertritt zwischen zwei Speichern;
die Serienschaltung wird - wie die Norm den Einzelspeicher - als ideal
geschichtet angenommen.
"""

from dataclasses import dataclass

SERIE = "Serie (hintereinander durchströmt)"
PARALLEL = "Parallel (gleichzeitig durchströmt)"
FUEHLER_ZAPFSEITIG = "zapfseitigen (letzten) Speicher"
FUEHLER_ERSTER = "ersten (kalten) Speicher"

SCHALTUNGEN = (SERIE, PARALLEL)
FUEHLER_POSITIONEN = (FUEHLER_ZAPFSEITIG, FUEHLER_ERSTER)


class SpeicherverbundFehler(ValueError):
    pass


@dataclass(frozen=True)
class Speicherverbund:
    """Anordnung aus `anzahl` baugleichen Speichern.

    Die Eingabewerte beziehen sich auf EINEN Speicher; die abgeleiteten
    Eigenschaften liefern die Größen für Eingabedaten/core.versorgung. Mit
    anzahl = 1 sind Ein- und Ausgabewerte identisch, die Rechnung bleibt also
    exakt die bisherige.
    """

    anzahl: int = 1
    v_je_speicher: float = 3000.0        # Bruttovolumen eines Speichers [l]
    h_je_speicher: float = 2.0           # Gesamthöhe eines Speichers [m]
    h_sensor_je_speicher: float = 0.6    # Fühlertiefe ab Oberkante DIESES Speichers [m]
    q_sb_je_speicher: float = 3.48       # Bereitschaftsverlust eines Speichers [kWh/24h]
    schaltung: str = SERIE
    fuehler_position: str = FUEHLER_ZAPFSEITIG

    def __post_init__(self):
        if self.anzahl < 1:
            raise SpeicherverbundFehler("Es muss mindestens ein Speicher vorhanden sein.")
        if self.schaltung not in SCHALTUNGEN:
            raise SpeicherverbundFehler(f"Unbekannte Schaltung '{self.schaltung}'.")
        if self.fuehler_position not in FUEHLER_POSITIONEN:
            raise SpeicherverbundFehler(f"Unbekannte Fühlerposition '{self.fuehler_position}'.")

    @property
    def ist_verbund(self) -> bool:
        return self.anzahl > 1

    @property
    def v_sto(self) -> float:
        """Gesamtvolumen [l] - Gl. 4 kennt nur die Summe."""
        return self.anzahl * self.v_je_speicher

    @property
    def h_sto(self) -> float:
        """Rechnerische Höhe [m]: Stapelhöhe bei Serie, Einzelhöhe bei Parallel."""
        if self.schaltung == SERIE:
            return self.anzahl * self.h_je_speicher
        return self.h_je_speicher

    @property
    def h_sensor(self) -> float:
        """Fühlertiefe ab der zapfseitigen Oberkante des Verbunds [m]."""
        if self.schaltung == SERIE and self.fuehler_position == FUEHLER_ERSTER:
            return (self.anzahl - 1) * self.h_je_speicher + self.h_sensor_je_speicher
        return self.h_sensor_je_speicher

    @property
    def q_sb_sto(self) -> float:
        """Bereitschaftsverlust des Verbunds [kWh/24h] = Summe der Einzelverluste."""
        return self.anzahl * self.q_sb_je_speicher

    @property
    def einbauhoehe_fuehler(self) -> float:
        """Einbauhöhe des Fühlers über dem Boden DES Speichers, in dem er sitzt [m].

        Anders als h_sto - h_sensor (Höhe über dem Boden des gedachten
        Gesamtspeichers) ist das die real messbare Einbauhöhe - die Speicher
        stehen ja nebeneinander, nicht aufeinander.
        """
        return self.h_je_speicher - self.h_sensor_je_speicher

    @property
    def kurzbeschreibung(self) -> str:
        if not self.ist_verbund:
            return f"1 x {self.v_je_speicher:.0f} l"
        return f"{self.anzahl} x {self.v_je_speicher:.0f} l, {self.schaltung}"
