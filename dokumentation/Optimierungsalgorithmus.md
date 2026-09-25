# Bericht: Algorithmus der Optimierung im TWW-Dimensionierungstool

Dieser Bericht dokumentiert nachvollziehbar, welche Berechnungen im Hintergrund
des Tools bei der Investitions- und Systemoptimierung (Modus D, E, F)
ablaufen: Eingangsparameter, Berechnungsablauf, verwendete Formeln,
Randbedingungen und – auf ausdrücklichen Wunsch – die Herkunft der
Pareto-Methodik in Modus F. Alle Verweise (Datei:Zeile) beziehen sich auf den
Stand des Projekts zum Zeitpunkt der Erstellung dieses Berichts.

---

## 1. Überblick über das Berechnungsprinzip

Allen drei Optimierungsmodi liegt **dieselbe Simulation** zugrunde – der
minutenweise Algorithmus zur Bestimmung der Energieversorgungskennlinie nach
ÖNORM EN 12831-3, Abschnitt 6.4.3.3 (Bild 14), implementiert in
[`core/versorgung.py::berechne_versorgungskennlinie()`](../core/versorgung.py).
Die Optimierung selbst besteht darin, diese Simulation **wiederholt mit
unterschiedlichen Anlagenparametern** (Speichervolumen, Erzeugerleistung,
Bereitschaftsverlust) laufen zu lassen und die Ergebnisse nach einem
Zielkriterium zu bewerten und auszuwählen:

| Modus | Was wird durchprobiert? | Zielfunktion(en) |
|---|---|---|
| D – Investitionsoptimierung | reale Katalogprodukte (WP × Speicher, Kreuzprodukt) | minimale Investkosten |
| E – Systemoptimierung über Kostenfunktionen | kontinuierliches Raster aus $V_{sto}$ und $\Phi_N$ | minimale Investkosten (aus Kostenfunktionen) |
| F – Techno-ökonomische Optimierung | reale Katalogprodukte (wie D), immer gegen Monitoring-Messdaten | drei Varianten: technisch, ökonomisch, techno-ökonomisch |

Die eigentliche „Intelligenz" der Optimierung liegt **nicht** in einem
Gradienten- oder Suchverfahren, sondern in einer **vollständigen Enumeration**
(Modus D/F: alle Katalogkombinationen; Modus E: alle Rasterpunkte) mit
anschließender Filterung/Sortierung nach dem Zulässigkeitskriterium und der
Zielgröße. Das ist bei den vorliegenden Problemgrößen (einige tausend
Kombinationen bzw. Rasterpunkte) rechnerisch unproblematisch und hat den
Vorteil, dass **keine Näherungen durch ein Suchverfahren** entstehen – das
Ergebnis ist immer das exakte Optimum innerhalb des geprüften Raums.

---

## 2. Eingangsparameter

### 2.1 Anlagenparameter (`core/modell.py::Eingabedaten`)

Für alle drei Modi identisch als Basis gesetzt, nur $V_{sto}$, $\Phi_N$ und
$q_{sb,sto}$ werden von der Optimierung je Kombination/Rasterpunkt
überschrieben:

| Parameter | Symbol | Bedeutung | Quelle |
|---|---|---|---|
| `speicher_typ` | – | Speicherladesystem / gemischtes Speichersystem | manuelle Eingabe |
| `h_sto`, `h_sensor` | $h_{sto}$, $h_{sensor}$ | Speicherhöhe, Fühlerhöhe | manuelle Eingabe |
| `f_l` | $f_l$ | Ladungsfaktor | manuelle Eingabe |
| `t_lag_hg` | $t_{lag,HG}$ | Anlaufverzögerung Erzeuger | manuelle Eingabe |
| `theta_ch_hg` | $\vartheta_{ch,HG}$ | Ladetemperatur Erzeuger (nur gemischte Systeme) | manuelle Eingabe |
| `q_dis_spec`, `l_dis` | $q'_{dis}$, $l_{dis}$ | spez. Leitungsverlust, Rohrlänge | manuelle Eingabe |
| `cw`, `theta_draw`, `theta_c`, `theta_sto_max`, `theta_a` | – | physikalische Konstanten/Temperaturen | manuelle Eingabe |
| `verlust_gesamt_je_minute` | $q_{V,ges}$ | optionaler Messwert-Override für Speicher-/Verteilverlust | optional, Monitoring |

### 2.2 Katalogparameter je Produkt (`core/katalog.py`)

**Wärmepumpe** (`lade_wp_katalog`): Hersteller, Produkt, Leistung $\Phi_N$
[kW] (wahlweise Betriebspunkt B0/W35 oder B0/W55), Höhe/Breite/Länge [mm],
Listenpreis, Inbetriebnahmekosten, optional Transportkosten →
`investkosten = listenpreis + ibn_kosten + transport_kosten` (nach
Rabattanwendung, `core/rabatt.py`).

**Speicher** (`lade_speicher_katalog`): Hersteller, Produkt, Nennvolumen
$V_{sto}$ [l], Material, Höhe/Länge/Breite/Durchmesser [mm],
Nettokosten → `investkosten`, sowie **Warmhalteverlust** $S$ [W]
(EU‑812/2013‑Wert), umgerechnet in den Bereitschaftsverlust

$$q_{sb,sto} = S \cdot 0{,}024 \qquad \text{[kWh/24h] (Gl. 7 der Norm)}$$

Dieser produktspezifische Wert ersetzt seit der letzten Überarbeitung den
zuvor global manuell eingegebenen $q_{sb,sto}$ – jede Speichergröße trägt
also ihren eigenen, realen Bereitschaftsverlust in die Simulation ein.

### 2.3 Zapfprofil

- **Modus D** (wahlweise) und **Modus E**: Norm-Lastprofil (`core/bedarf.py`,
  Gl. 19–21) **oder** Monitoring-Messdaten, umschaltbar.
- **Modus F**: **ausschließlich** Monitoring-Messdaten (`core/monitoring.py`)
  – bewusst kein Umschalter, weil alle drei Zielvarianten explizit „mit den
  Monitoringdaten funktionierend" sein sollen (siehe Abschnitt 5).

### 2.4 Filter vor der Optimierung (Sidebar)

- **Rabattgruppen**: herstellerspezifischer Prozentsatz auf Listenpreis
  (WP) bzw. Nettokosten (Speicher), vor der Optimierung angewendet.
- **Hersteller-Auswahl**: Checkboxen je Hersteller, schließt einzelne
  Hersteller komplett aus dem geprüften Katalog aus.
- **Material-Filter** (Speicher): „Alle" / „Edelstahl" / „Stahl emailliert".

Alle drei Filter wirken **vor** der Optimierung auf `wp_katalog` /
`speicher_katalog` – die Optimierung selbst „sieht" nur noch den bereits
gefilterten, rabattierten Katalog.

---

## 3. Berechnungsablauf je Kombination (Kernalgorithmus)

Für **jede** zu prüfende Kombination (Katalogpaar in D/F, Rasterpunkt in E)
läuft exakt derselbe Ablauf, implementiert in
[`berechne_versorgungskennlinie()`](../core/versorgung.py#L98):

```
Eingabe:  Eingabedaten (mit v_sto, phi_n, q_sb_sto der aktuellen Kombination)
          + Zapfprofil [l/min] (Länge = Betrachtungszeitraum in Minuten)

1. Referenzgrößen berechnen (einmalig, vor der Zeitschleife):
     Q_sto,max  – Gl. 4   (maximale Speicherkapazität)
     Q_sto,ON   – Gl. 10  (Einschaltpunkt)
     Q_sto,min  – Gl. 5   (nur gemischte Systeme, sonst 0)
     q_V,ges    – Gl. 6 + Gl. 9 (oder Messwert-Override)

2. Speicher startet voll geladen: Q_sto(0) = Q_sto,max

3. Minutenschleife (t = 0 … n-1):
     a) Bedarfsabzug: Q_bedarf(t) aus Zapfprofil, Dichte ρ_W (Gl. B.1), c_w
     b) Ist Erzeuger aus UND Q_sto(t-1) ≤ Q_sto,ON  → Erzeuger einschalten
     c) Ist Erzeuger an UND Anlaufzeit t_lag,HG abgelaufen:
          Speicherladesystem      → Φ_eff = Φ_N                (Gl. 13)
          gemischtes System       → Φ_eff = Φ_N · f(ϑ_Sto,m(t)) (Gl. 14)
          Q_eff(t) = Φ_eff / 60                                 (Gl. 17)
     d) Bilanz: Q_sto(t) = Q_sto(t-1) + Q_eff(t) − Q_bedarf(t) − q_V,ges
     e) Ist Erzeuger an UND Q_sto(t) ≥ Q_sto,max → Kappen auf Q_sto,max,
        Erzeuger ausschalten, Zyklus abschließen (Zähler +1)

4. Ausgabe: SOC-Verlauf Q_sto(t), Anzahl abgeschlossener Zyklen,
            Gesamtlaufzeit, Endladezustand, SOC_min = min(Q_sto(t))
```

Dies ist derselbe Algorithmus, der bereits für die Einzelauslegung (Modus
A–C) verwendet wird – die Optimierung unterscheidet sich nur dadurch, dass
er **automatisiert für sehr viele Parameterkombinationen** ausgeführt und das
Ergebnis strukturiert verglichen wird.

### 3.1 Zulässigkeitskriterium (Norm-Kriterium)

Jede Kombination wird nach dem Durchlauf als **zulässig** markiert, wenn

$$SOC_{min} \;\geq\; Q_{sto,min}$$

gilt (`soc_min >= ergebnis.q_sto_min`,
[`core/investition.py:75`](../core/investition.py#L75)). Das ist exakt das
Sicherheitskriterium aus Abschnitt 6.4.3.3 der Norm – keine tool-eigene
Zusatzbedingung. Unzulässige Kombinationen bleiben im Ergebnis sichtbar
(z. B. in den Diagrammen grau/x markiert), fließen aber nie in die
Optimums-Auswahl ein.

### 3.2 Modus-spezifische Zusatzschritte

**Modus D** ([`core/investition.py::optimiere()`](../core/investition.py#L48)):
für jedes Paar (WP-Zeile, Speicher-Zeile) aus dem Kreuzprodukt der beiden
Kataloge wird obiger Ablauf einmal ausgeführt; `phi_n`, `v_sto`, `q_sb_sto`
werden je Paar per `dataclasses.replace()` in die Eingabedaten eingesetzt.
Ergebnisliste wird nach `(nicht zulässig, Gesamtkosten)` sortiert – zulässige
und darunter günstigste Kombinationen stehen vorne.

**Modus E** ([`core/systemoptimierung.py::optimiere_raster()`](../core/systemoptimierung.py#L38)):
statt realer Produkte wird ein **kontinuierliches Raster** aus $V_{sto}$ und
$\Phi_N$ im Bereich 30–200 % zweier Referenzwerte abgefahren
(`raster_schritte × raster_schritte` Punkte). Der Bereitschaftsverlust wird
dabei mit der Speichergröße mitskaliert:

$$q_{sb,sto}(V) = q_{sb,ref} \cdot \left(\frac{V}{V_{ref}}\right)^{2/3}$$

(Näherung über die Speicheroberfläche). Zusätzliche Zulässigkeitsbedingungen:
Laufzeit $\leq$ `max_laufzeit_h` und 24-h-Ladeausgleich (Endladezustand
$\geq 95\,\%$ von $Q_{sto,max}$). Die Kosten je Rasterpunkt stammen nicht aus
realen Katalogpreisen, sondern aus den **degressiven Kostenfunktionen**
(Abschnitt 4.4).

**Modus F** ([`core/investition.py::optimiere()`](../core/investition.py#L48),
identische Funktion wie Modus D): einziger Unterschied zu D ist, dass
`zapfprofil_basis` immer das Monitoring-Ist-Profil ist, und dass aus der
resultierenden Kombinationsliste **drei** statt einer Kennzahl ausgewählt
werden (Abschnitt 4.5–4.6).

---

## 4. Verwendete Formeln (Zusammenfassung)

| Gl. | Bezeichnung | Formel | Code |
|---|---|---|---|
| B.1 | Dichte Wasser | $\rho_W(\vartheta) = \dfrac{1000 - 0{,}005\,(\vartheta-4)^2}{1000}$ | `dichte_wasser()` |
| 4 | Max. Speicherkapazität | $Q_{sto,max} = \dfrac{V_{sto}\,\rho_W\,c_w\,(\vartheta_{sto,max}-\vartheta_c)\,f_l}{3600}$ | `q_sto_max()` |
| 5 | Min. Speicherkapazität | $Q_{sto,min} = \dfrac{V_{sto}\,\rho_W\,c_w\,(1-\frac{h_{sensor}}{2h_{sto}})(\vartheta_{draw}-\vartheta_c)f_l}{3600}$ | `q_sto_min()` |
| 6 | Speicher-Bereitschaftsverlust | $Q_{W,sto,t} = \dfrac{q_{sb,sto}\,(\vartheta_{sto,max}-\vartheta_a)}{45\cdot 1440}$ | `verlust_speicher_je_minute()` |
| 7 | $q_{sb,sto}$ aus Warmhalteverlust | $q_{sb,sto} = S \cdot 0{,}024$ | `core/katalog.py` |
| 9 | Verteilverlust | $Q_{W,dis,t} = \dfrac{q'_{dis}\cdot l_{dis}}{60000}$ | `verlust_verteilung_je_minute()` |
| 10 | Einschaltpunkt | $Q_{sto,ON} = Q_{sto,max}\left(1-\dfrac{h_{sensor}}{h_{sto}}\right)$ | `q_sto_on()` |
| 13 | Eff. Leistung, Speicherladesystem | $\Phi_{eff} = \Phi_N$ | `berechne_versorgungskennlinie()` |
| 14 | Eff. Leistung, gemischtes System | $\Phi_{eff} = \Phi_N \cdot \max\!\left(0,\,1-\dfrac{\vartheta_{Sto,m}-\vartheta_c}{\vartheta_{ch,HG}-\vartheta_c}\right)$ | „ |
| 17 | Effektive Energie/Minute | $Q_{eff} = \Phi_{eff}/60$ | „ |
| – | SOC-Rekursion | $Q_{sto}(t) = Q_{sto}(t-1)+Q_{eff}(t)-Q_{bedarf}(t)-q_{V,ges}$ | „ |
| – | Zulässigkeit | $SOC_{min}\geq Q_{sto,min}$ | `optimiere()` |
| – | Degressive Kostenfunktion (Modus E) | $K(x) = a\cdot x^{b}$, log-log-Regression | `core/kostenfunktion.py` |
| – | Bereitschaftsverlust-Skalierung (Modus E) | $q_{sb,sto}(V)=q_{sb,ref}(V/V_{ref})^{2/3}$ | `core/systemoptimierung.py` |
| – | Pareto-Dominanz (Modus F) | siehe Abschnitt 5 | `pareto_front()` |
| – | Gewichtete Summe (Modus F) | siehe Abschnitt 5 | `kompromiss_zulaessige()` |

### 4.4 Degressive Kostenfunktion (Modus E)

$$K(x) = a \cdot x^{b}$$

ermittelt per log-log-linearer Regression ($\ln K = \ln a + b\ln x$) aus den
Katalogdaten (`core/kostenfunktion.py::_potenzfit()`). $b<1$ bildet
Skaleneffekte (sinkende spezifische Kosten mit steigender Baugröße) ab; an
den realen Katalogen ergibt sich empirisch $b \approx 0{,}60$ für WP und
Speicher – nahe der „6/10-Regel" der klassischen Kostenschätzung im
Anlagenbau.

### 4.5 Variante 1 – Technische Optimierung (Modus F)

$$\text{Ziel: } \min_{k \in \mathcal{K}_{zul}} \; \text{Zyklen}(k)$$

über die Menge $\mathcal{K}_{zul}$ der zulässigen Kombinationen; bei
Gleichstand entscheidet die Investitionssumme
(`materialschonendste_zulaessige()`,
[`core/investition.py:101`](../core/investition.py#L101)).

### 4.6 Variante 2 – Ökonomische Optimierung (Modus F)

$$\text{Ziel: } \min_{k \in \mathcal{K}_{zul}} \; \text{Gesamtkosten}(k)$$

(`guenstigste_zulaessige()`,
[`core/investition.py:94`](../core/investition.py#L94) – identisch zur
Zielfunktion aus Modus D).

---

## 5. Variante 3 – Techno-ökonomische Optimierung und das Pareto-Prinzip

### 5.1 Warum nicht einfach eine gewichtete Summe direkt berechnen?

Kosten [€] und Schalthäufigkeit [Zyklen] sind zwei **gleichzeitig zu
minimierende, aber gegenläufige** Zielgrößen (ein sparsameres Gerät kostet in
der Regel mehr oder erfordert einen größeren Speicher). Eine Kombination,
die gleichzeitig **strikt** am günstigsten und am schalthäufigkeitsärmsten
ist, existiert im Allgemeinen nicht – das ist ein echter Zielkonflikt
(*trade-off*), kein Rechenfehler. Eine einzelne „beste Zahl" ohne weitere
Begründung würde diesen Zielkonflikt verschleiern. Deshalb wird zweistufig
vorgegangen:

### 5.2 Schritt 1 – Pareto-Front (Dominanzkriterium)

Eine zulässige Kombination $k$ heißt **dominiert**, wenn eine andere
zulässige Kombination $a$ existiert mit

$$a_{Kosten} \leq k_{Kosten} \;\land\; a_{Zyklen} \leq k_{Zyklen}
\;\land\; \left(a_{Kosten} < k_{Kosten} \;\lor\; a_{Zyklen} < k_{Zyklen}\right)$$

d. h. $a$ ist in **keiner** Zielgröße schlechter und in **mindestens einer**
strikt besser. Die **Pareto-Front** ist die Menge der *nicht* dominierten
Kombinationen (`pareto_front()`,
[`core/investition.py:112`](../core/investition.py#L112)) – jede Kombination
auf dieser Front ist in dem Sinne „optimal", dass keine andere zulässige
Kombination sie in beiden Zielgrößen gleichzeitig schlägt. Visualisiert wird
sie als Streudiagramm Kosten-vs-Zyklen mit hervorgehobener Stufenlinie
(`plot_pareto_front()`, `core/visualisierung.py`).

### 5.3 Schritt 2 – Gewichtete Summe (Skalarisierung)

Die Pareto-Front liefert eine **Menge** möglicher Kompromisse, aber noch
keinen einzelnen Punkt. Um einen auszuwählen, werden beide Zielgrößen zuerst
min-max-normiert (damit € und Anzahl Zyklen vergleichbar werden):

$$\tilde{K}(k) = \frac{K(k) - K_{min}}{K_{max}-K_{min}}, \qquad
\tilde{Z}(k) = \frac{Z(k) - Z_{min}}{Z_{max}-Z_{min}}$$

und anschließend der gewichtete Score

$$\text{Score}(k) = w \cdot \tilde{K}(k) + (1-w)\cdot \tilde{Z}(k), \qquad w\in[0,1]$$

minimiert (`kompromiss_zulaessige()`,
[`core/investition.py:133`](../core/investition.py#L133)). $w$ ist im Tool
per Schieberegler einstellbar (Default $w=0{,}5$); $w=1$ entspricht Variante
2 (rein ökonomisch), $w=0$ Variante 1 (rein technisch). Das gewählte
Ergebnis ist damit transparent als **bewusst getroffene Gewichtungsentscheidung**
gekennzeichnet, nicht als eine „objektiv beste" Lösung.

### 5.4 Herkunft dieser Methodik

Die beiden Bausteine – **Pareto-Dominanz zur Bestimmung der nicht-dominierten
Menge** und **gewichtete Summe (Weighted-Sum-Methode) als
Skalarisierungsverfahren zur Auswahl eines Punktes von dieser Front** – sind
etablierte Standardverfahren der Mehrzieloptimierung (*Multi-Objective
Optimization*, MOO). Die konkrete Anwendung auf den Zielkonflikt
Investitionskosten gegen Schalthäufigkeit von TWW-Anlagenkombinationen ist die
eigenständige Umsetzung im Rahmen dieser Arbeit.

Die methodische Einordnung folgt [1]:

- **Dominanzkriterium** (Abschnitt 5.2): [1], S. 371–372
- **A-priori-Skalarisierung** über die Kostenfunktion in Modus E
  (Abschnitt 4.4): [1], S. 373–376
- **Gewichtete Summe** über Min-Max-normierte Ziele (Abschnitt 5.3):
  [1], S. 372–375
- **Lexikographische Reihung** – bei Gleichstand in der Schalthäufigkeit
  entscheidet der Preis (Variante 1): [1], S. 375–376
- **Beschränkung der gewichteten Summe auf die konvexe Hülle der Front**, und
  damit der Grund, warum das Werkzeug stets die vollständige Front als Tabelle
  und Diagramm ausgibt statt nur den gewichteten Punkt: [1], S. 373–375

Dass der Kompromiss erst ausgewählt wird, *nachdem* der Zielkonflikt sichtbar
gemacht wurde, entspricht dem Vorgehen der Pareto-Navigation für die Auslegung
der Energieversorgung von Gebäuden [2].

**Literatur**

[1] R. Marler und J. Arora, „Survey of multi-objective optimization methods for
engineering", *Structural and Multidisciplinary Optimization*, Jg. 26, Nr. 6,
S. 369–395, Apr. 2004. DOI: [10.1007/s00158-003-0368-6](https://doi.org/10.1007/s00158-003-0368-6)

[2] E. Halser, E. Finhold, N. Leithäuser, P. Süss und K.-H. Küfer, „Pareto
navigation for multicriteria building energy supply design", *Applied Energy*,
Jg. 371, S. 123651, Okt. 2024. DOI: [10.1016/j.apenergy.2024.123651](https://doi.org/10.1016/j.apenergy.2024.123651)

---

## 6. Randbedingungen im Überblick

| Randbedingung | Gilt in | Quelle |
|---|---|---|
| $SOC_{min}\geq Q_{sto,min}$ (Norm-Kriterium) | D, E, F | Abschn. 6.4.3.3 der Norm |
| Laufzeit $\leq$ max. WP-Laufzeit/Tag | E | Nutzervorgabe |
| 24-h-Ladeausgleich ($Q_{sto,Ende}\geq 0{,}95\,Q_{sto,max}$) | E | konzeptionell festgelegt |
| Katalogzeile vollständig (Pflichtspalten) | D, E, F | `core/katalog.py` |
| Speichermodell entspricht Material-Filter | D, E, F (optional) | Nutzervorgabe |
| Hersteller in Hersteller-Auswahl aktiviert | D, E, F | Nutzervorgabe |
| Datengrundlage = Monitoring-Messdaten (kein Umschalter) | F | konzeptionell festgelegt |

---

## 7. Kurzfassung des Ablaufs (für die Arbeit)

1. Kataloge einlesen, validieren, filtern (Hersteller, Material, Rabatte).
2. Für jede zu prüfende Kombination/jeden Rasterpunkt: Anlagenparameter
   setzen, minutenweise Norm-Simulation (Bild 14) durchführen.
3. Zulässigkeit prüfen ($SOC_{min}\geq Q_{sto,min}$, ggf. weitere
   Nebenbedingungen in Modus E).
4. Unter den zulässigen Kombinationen die Zielgröße(n) auswerten:
   - D: minimale Kosten
   - E: minimale Kosten (aus Kostenfunktionen), zusätzliche Randbedingungen
   - F: minimale Zyklen (V1) / minimale Kosten (V2) / Pareto-Front +
     gewichteter Kompromiss (V3)
5. Ergebnis, Diagramm und Protokoll (inkl. PDF-Export) ausgeben.
