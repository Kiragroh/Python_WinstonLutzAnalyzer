# Winston-Lutz Analyzer

Dieses Repository enthaelt die Open-Source-Variante des WLT-Tools. Der produktive
UKL-Stand wird als separate Portable-App betrieben; die wichtigsten Betriebs-,
Ausgabe- und Verlaufspfade sind hier mit dokumentiert, damit sie auch im Hub
direkt auffindbar sind.

## UKL Schnellzugriff

### Anleitung und Programmstand

Die aktuelle Daily-WLT-Anleitung liegt hier:

```text
\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Standalone\ETD-WLT-UKL_Portable\Anleitung_WLT_Daily.pdf
```

Der verteilte Portable-Ordner im Netzwerk liegt direkt daneben:

```text
\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Standalone\ETD-WLT-UKL_Portable
```

Lokaler UKL-Arbeitsstand und Portable-Ausgabe:

```text
C:\Users\grohmanmax\Seafile\Meine Bibliothek\Scripts\WLT-Analysis\ETD-WLT-UKL_Portable
```

Der bearbeitbare Python-Quellstand liegt im benachbarten Ordner:

```text
C:\Users\grohmanmax\Seafile\Meine Bibliothek\Scripts\WLT-Analysis\ETD-WLT-UKL
```

Die Portable-App wurde fuer diese Dokumentationsaktualisierung nicht neu gebaut.

### Aktueller UKL-Funktionsstand

- Standard WLT mit UKL-PDF, Shift des BB zum Strahlenisozentrum in mm, Tischpositionen in cm und Richtung `L-R` statt `A-B`.
- Geraetebezogener Translationsverlauf nach DICOM `ContentDate`/`ContentTime` fuer `L-R`, `T-G`, `B-D` und den 3D-Vektor.
- Multi-Ball Off-Iso mit RTIMAGE-/RTPLAN-Zuordnung, Einzelbild-Previews, MLC-Ansichten sowie CSV-/JSON-Ausgabe.
- Qualiformed-Verlauf je Geraet und Metrik mit Grenzwert, Metrikerlaeuterung, Statistik und direktem Sprung in die HTML-Auswertung.
- Globale Standardpfade und `keep`-Schalter im Settings-Reiter.
- Netzwerk-Ausgaben mit lokalem Fallback im sichtbaren Portable-Unterordner `output`.

### Zentrale Ausgaben

| Inhalt | Pfad |
|---|---|
| Standard-WLT Reports | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Output\WLT\Normal` |
| Multi-Ball-Ausgaben | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Output\WLT\Multi` |
| Gemeinsame Verlaufs-CSV | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Output\WLT\wlt_history.csv` |
| Translationsverlauf PNG | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Output\WLT\wlt_translation_history.png` |
| Qualiformed-Kurzverlauf PNG | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\11. Scripting\Output\WLT\qualiformed_wlt_history.png` |
| Qualiformed Daten, Excel und Plots | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\3. QS\QS-Geräte\WLPlus_Auswertung` |
| Qualiformed SQLite-Datenbank | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\3. QS\QS-Geräte\WLPlus_Auswertung\qualiformed_wlt_metrics.db` |
| Qualiformed Gesamt-HTML | `\\medizin.uni-leipzig.de\data\Archiv\STR\STR-Physik\3. QS\QS-Geräte\WLPlus_Auswertung\html\gesamt_wlt_iso_trends.html` |

### Aktuelle Verlaeufe

Die folgenden anonymisierten Snapshots wurden am 23.07.2026 aus den zentralen
Ausgaben uebernommen. Im klinischen Betrieb sind die oben genannten Netzwerkdateien
die jeweils aktuelle Quelle.

#### Translationsabweichungen Standard WLT

![Aktueller Standard-WLT Translationsverlauf](docs/current/wlt_translation_history.png)

#### Qualiformed WLT: X6.0 Isocenter diameter

![Aktueller Qualiformed-WLT Verlauf](docs/current/qualiformed_wlt_history.png)

## Open-Source Workflows

Die Open-Source-Variante bietet zwei Workflows:

1. **Standard WLT**
   - nutzt `pylinac.WinstonLutz`
   - analysiert einen Ordner mit WLT-DICOMs
   - schreibt optional TXT-Zusammenfassung und PDF-Report mit modernem Deckblatt, UKE-Legacy-Summary ohne Signatur und pylinac-Detailseiten
   - kann die Ergebnisdateien im Analyseordner oder in einem allgemeinen Output-Ordner ablegen
   - schreibt optional eine lokale Verlaufs-CSV

2. **Multi-Ball Off-Iso**
   - Python-Auswertung fuer Multi-Ball-/Multi-Target-Off-Iso-Tests
   - erwartet standardmaessig drei Subfelder/Kugeln pro RTIMAGE, kann optional automatisch zaehlen
   - kann optional ein RTPLAN-DICOM laden, um Bilder ueber Gantry/Kollimator/Tisch Beam-Namen zuzuordnen
   - schreibt CSV, JSON, Einzelbild-Previews, MLC-Muster aus dem RTPLAN und einen Uebersichtsgraphen

Die produktive Portable-App, zentrale Verlaufsdaten und klinischen Ausgaben sind
nicht Bestandteil dieses Repositories. Die oben dokumentierten UKL-Pfade dienen
als betriebliche Referenz; es werden keine DICOMs, Reports, CSV-Rohdaten oder
patientenbezogenen Daten eingecheckt.

## Installation

```powershell
cd WLT_v3.0_open
py -3.14 -m pip install -U pip
py -3.14 -m pip install -r requirements.txt
```

Start:

```powershell
.\start_open_gui.cmd
```

Der Starter nutzt das globale Python 3.14 des PCs. Er legt keine `.venv` an.

## Screenshots

Die Screenshots zeigen anonymisierte Beispiel-Auswertungen. Pfade, Linac-Namen und lokale Userdaten sind bewusst durch Platzhalter ersetzt.

> **Hinweis zum aktuellen GUI-Stand:** Die Abbildungen zeigen noch nicht die
> beiden neuen Reiter **Translationsverlauf** und **Qualiformed**.
> **Translationsverlauf** zeigt je Geraet und nach DICOM-Aufnahmedatum die
> Abweichungen in `L-R`, `T-G`, `B-D` sowie den 3D-Translationsvektor.
> **Qualiformed** bietet eine Geraete- und Metrikauswahl mit Grenzwert,
> Metrikerlaeuterung, Zeitraum, Statistik und Link zur interaktiven
> HTML-Auswertung. Die aktuellen Ergebnisplots dieser Reiter stehen oben im
> Abschnitt **Aktuelle Verlaeufe und Ausgaben**.

### Standard WLT nach Auswertung

![Standard WLT nach Auswertung](docs/screenshots/standard_wlt_after.png)

### Multi-Ball Off-Iso nach Auswertung

![Multi-Ball Off-Iso nach Auswertung](docs/screenshots/multi_ball_after.png)

### Multi-Ball MLC-Muster

![Multi-Ball MLC-Muster](docs/screenshots/multi_ball_mlc_after.png)

### Verlauf

![Verlauf](docs/screenshots/history_after.png)

## Lokale GUI-Settings

Die GUI merkt sich Pfade lokal in:

```text
output\gui_settings.json
```

Fuer jede Pfadzeile gibt es einen `keep`-Schalter:

- `keep` aus: Beim naechsten Start wird der zuletzt genutzte Pfad geladen.
- `keep` an: Der aktuelle Pfad bleibt fixiert und wird nicht durch spaetere Analysen ueberschrieben.
- Um einen fixierten Pfad zu aendern, neuen Pfad waehlen und `keep` aktiv lassen oder `keep` kurz aus/an schalten.

Die Settings-Datei ist bewusst lokal und wird nicht fuer eine Open-Source-Veroeffentlichung versioniert.

## Standard WLT Ablauf

1. Reiter **Standard WLT** oeffnen.
2. Analyseordner mit WLT-DICOMs waehlen.
3. Waehlen, ob Output im Analyseordner oder im allgemeinen Output-Ordner landet.
4. TXT und/oder PDF aktivieren.
5. **WLT auswerten** klicken.

Die App schreibt:

- `wlt_results_<timestamp>.txt`
- `wlt_report_<timestamp>.pdf`
- optional einen Eintrag in `output\wlt_history.csv`

Der PDF-Report enthaelt ein kompaktes WLT-Deckblatt mit pylinac-Version und Kennwerten; danach folgt der originale pylinac-Fachreport. Nach erfolgreicher Analyse oeffnet die GUI den PDF-Report automatisch.

Die Analyse ist bewusst generisch und nutzt die aktuelle pylinac-API. Spezialausgaben der privaten MG-Version sind hier nicht enthalten.

## Multi-Ball Off-Iso Ablauf

Der Workflow ist als generische Python-Auswertung fuer RTIMAGE-DICOMs mit mehreren getrennten Subfeldern aufgebaut:

1. Fuer jedes RTIMAGE werden die hellen Subfelder gesucht.
2. Je Subfeld wird der Innenbereich leicht erodiert, damit Feldkanten nicht stoeren.
3. Innerhalb jedes Subfelds wird die dunkle Kugelstruktur gesucht.
4. Feldzentrum und Kugelzentrum werden bestimmt.
5. Der Abstand wird vom Detektor auf Iso-Ebene skaliert:

```text
distance_iso_mm = distance_detector_mm * 1000 / RTImageSID
```

Die GUI schreibt:

- `multi_ball_wlt_<timestamp>.csv`
- `multi_ball_wlt_<timestamp>.json`
- `multi_ball_wlt_previews_<timestamp>\*.png`
- `multi_ball_mlc_<timestamp>\*.png`, wenn ein RTPLAN mit MLC-Daten geladen wurde
- `multi_ball_wlt_graph_<timestamp>.png`

Die Einzelbild-Previews zeigen gruene Feldkonturen, rote Kugelkonturen und die berechneten Abstaende. Der Graph fasst Maximal- und Mittelwerte je Bild zusammen. Die MLC-Ansicht ist ein PlanFile-Viewer fuer die gematchten Beams; sie zeigt Jaws, MLC-Baenke und die daraus entstehende Apertur, ist aber nicht Teil der numerischen Kugel-/Feldzentrumsauswertung.

### PlanFile und Zuordnung

Das RTPLAN kann ausgetauscht werden, solange es ein regulaeres RTPLAN-DICOM mit `BeamSequence` und `ControlPointSequence` ist. In dieser Open-Variante wird das PlanFile aber nur fuer die Beam-Zuordnung verwendet:

- Bildwinkel aus dem RTIMAGE: Gantry, Kollimator, Tisch
- Plan-Beams aus dem RTPLAN: Gantry, Kollimator, Tisch
- Zuordnung: kleinste zyklische Winkelsumme

Die Reihenfolge der Bilder ist damit nicht entscheidend. Gerade bei unterschiedlichen Tischwinkeln ist die Winkelsumme wichtig; sie wird in Terminal, CSV und Ergebnistext ausgegeben. Zusaetzlich werden Bildwinkel und gematchte Planwinkel nebeneinander ausgegeben, weil Beam-Namen nicht immer eindeutig zur DICOM-Winkelkonvention passen. Wenn der Match ausserhalb der Toleranz liegt, steht dort `nearest: ...` mit Warnhinweis.

Wenn der gematchte Beam MLC-Daten enthaelt, wird zusaetzlich ein MLC-Muster gerendert. In der GUI kann nach der Analyse ueber `MLC` zwischen den Plan-Aperturen pro Bild geblaettert werden.

### Anzahl Mets/Subfelder

`Mets/Bild = 3` ist der robuste Default fuer die vorhandenen Beispielbilder. Fuer andere Phantom-Setups kann `auto` verwendet werden. Auto sucht alle getrennten, ausreichend grossen hellen Feldinseln. Das ist flexibler, muss aber visuell ueber die Previews kontrolliert werden, weil Artefakte oder zusammenhaengende Feldformen die Zaehllogik beeinflussen koennen.

## Beispiel-Daten

Diese Open-Variante enthaelt bewusst keine klinischen Beispiel-DICOMs. Fuer Tests sollten anonymisierte oder synthetische RTIMAGE-/RTPLAN-Daten genutzt werden.

## CLI fuer Multi-Ball

```powershell
python multi_ball_wlt.py ".\path\to\rtimage_folder" `
  --plan ".\path\to\rtplan.dcm" `
  --fields 3 `
  --output ".\output"
```

Automatische Feldanzahl:

```powershell
python multi_ball_wlt.py ".\path\to\rtimage_folder" --fields auto --output ".\output"
```

## Grenzen

- Der Multi-Ball-Workflow ist aktuell fuer RTIMAGE-Daten mit getrennten Subfeldern gedacht.
- Es ist keine Live-Messung und keine automatische Planerzeugung.
- Das RTPLAN wird derzeit zur Beam-Zuordnung genutzt, nicht zur geometrischen Simulation der MLC- oder Jaw-Kontur.
- Die Toleranzbewertung ist bewusst nicht hart codiert; sie sollte lokal definiert werden.

## Lizenz

Im Ordner liegt eine MIT-Lizenzdatei als Startpunkt. Vor einer oeffentlichen Veroeffentlichung bitte pruefen, ob alle enthaltenen Daten, Logos und Textteile wirklich freigegeben werden duerfen.
