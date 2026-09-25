# Beispieldaten

## `demo_zapfprofil.csv`

Ein **frei erfundenes** Lastprofil eines Wohngebäudes mit Morgen- und
Abendspitze. Es dient allein dazu, das Tool ohne Normzugang startklar zu
machen, und ist **kein normatives Lastprofil**. Ergebnisse, die darauf beruhen,
sind nicht normkonform.

## Format für eigene Lastprofile

Das Tool liest CSV-Dateien mit den 24 Stundenanteilen des Tagesbedarfs in
Prozent, beginnend bei 00:00. Zwei Schreibweisen werden erkannt:

**Mit Stundenspalte** (wie in `demo_zapfprofil.csv`):

```
stunde;anteil_prozent
0;1.5
1;0.8
...
23;2.1
```

**Nur die Werte**, eine Zahl je Zeile oder alle in einer Zeile:

```
1.5
0.8
...
```

Semikolon und Komma sind als Trennzeichen zulässig, ebenso das Dezimalkomma.
Eine Kopfzeile darf vorhanden sein, muss aber nicht. Die Anteile müssen sich
nicht exakt auf 100 summieren - das Tool normiert die Reihe ohnehin auf das
berechnete Tagesvolumen.

Geladene Profile gelten nur für die laufende Sitzung. Wer seine Profile
dauerhaft hinterlegen möchte, trägt sie in `core/norm_werte_lokal.py` ein
(Anleitung im Kopf von `core/norm_werte_vorlage.py`).
