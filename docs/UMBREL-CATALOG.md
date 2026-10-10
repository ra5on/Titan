# Umbrel-Katalog in Titan

Der Nutzer hat am 10. Oktober 2026 die Integration des offiziellen
`getumbrel/umbrel-apps`-Katalogs mit eigener Titan-Oberfläche beauftragt.
Systemupdates bleiben auf Titans signiertem GitHub-Kanal. Der UmbrelOS-Code
und seine Oberfläche sind keine Implementierungsbasis dieses Adapters.

## Implementierung und Herkunft

`titan/umbrel_catalog.py` liest eine auf einen Git-Commit festgelegte Ausgabe
als Daten. Der Bericht nennt Commit und Archiv-SHA256. Alle Manifeste werden
gezählt; fehlende Abhängigkeiten und Zyklen führen vor Installationsänderungen
zum Fehler. Metadaten, Compose und erforderliche Begleitdateien bleiben als
Anforderungen sichtbar. Benötigte Dateien werden anhand ihrer Prüfsumme in
private App-Verzeichnisse übernommen. Hooks und Exporte werden nicht ausgeführt.

YAML-Merge-Anker werden mit Begrenzungen für Größe, Verschachtelung und
Graphauswertung verarbeitet. Doppelte Schlüssel, rekursive Aliase, unsichere
Archivpfade und verknüpfte Paketdateien werden abgelehnt. Private persistente
Daten werden in Titans App-Speicher abgebildet. Der Zugangsschutz des Originals
wird nicht still entfernt: Pakete mit Proxy-Anmeldung benötigen zunächst einen
eigenen kompatiblen Zugangsdienst.

Der Katalog und die einzelnen Anwendungen sind externe Drittquellen; diese
Integration erteilt keine neuen Rechte an Paketdateien, Images oder Artwork.
Titan bündelt in dieser Änderung keine Katalogdateien und keine Umbrel-Icons.
Quelle: https://github.com/getumbrel/umbrel-apps

## Prüfstand vom 10. Oktober 2026

Referenz: `aa3c4e9fba032796d15ec09dc1a217aa6566ce8f`.
Alle 393 Pakete werden erfasst. 14 lassen sich bereits in Titans vorhandenes
Compose-Modell übersetzen. Das ist keine Laufzeitfreigabe und keine vollständige
Katalogunterstützung. Die übrigen Pakete bleiben ausdrücklich gesperrt:

| Erste fehlende Voraussetzung pro Paket | Anzahl |
| --- | ---: |
| Lebenszyklusschritte/Exporte | 138 |
| Anmeldung vor der App | 133 |
| Andere installierte Apps | 46 |
| Besondere App-Proxy-Konfiguration | 25 |
| Laufzeitvariablen | 23 |
| Verwaltete Zugangsdaten | 2 |
| Zusätzliche Speicherzuordnungen | 6 |
| Compose-Kommandos, HTTPS oder Einstiegspfad | 6 |

Ein Paket kann mehrere Anforderungen haben; die Tabelle zählt jeweils den
ersten Hinderungsgrund. Die Entwicklungsoberfläche bietet die übersetzbaren Pakete nach ausdrücklich
gestartetem Katalogabruf an. Nicht übersetzbare Pakete zeigen ihren Hinderungsgrund.
Dies ist noch keine Stable-Freigabe. Katalogabrufe ändern installierte Rezepte nicht.
Ein Appupdate übernimmt neue Images erst nach kalter Sicherung; Änderungen an
Speicherzuordnung oder Einrichtung verlangen eine geprüfte Migration und bleiben gesperrt.

Reproduzierbarer Bericht:

```sh
python3 scripts/audit-umbrel-catalog.py \
  --revision aa3c4e9fba032796d15ec09dc1a217aa6566ce8f \
  --output umbrel-coverage.json
```

`--require-complete` lässt die Prüfung bei unübersetzten Paketen fehlschlagen.
Zusätzlich bleiben echte Laufzeitnachweise nötig. Der separate GitHub-Workflow
`Umbrel catalog compatibility` prüft Memos und Uptime Kuma auf isolierten Runnern:
Compose-Installation, erreichbare Oberfläche, angelegte Anwendungsdatenbank,
Stoppen, Entfernen und erneutes Erstellen bei erhaltenen Daten. Ein zusätzlicher Lauf prüft Memos über Titans echten HTTP-Installer und die
Paketverwaltung. Appversionswechsel und Anmeldung in der Anwendung benötigen
weiterhin zusätzliche Laufzeitnachweise.
Ein grüner Lauf allein gibt deshalb weder den Store noch das neue Systemimage frei.

## Nächste Integrationsschritte

1. Eigener App-Zugang mit Titan-Anmeldung einschließlich WebSockets und HTTPS.
2. Paketdateien, persistente Laufzeitvariablen und benötigte Einrichtungen ohne
   Übernahme von UmbrelOS-Implementierungscode unterstützen.
3. Appübergreifende Abhängigkeiten mit stabilen Dienstadressen und geteilten,
   privaten Zugangsdaten verwalten; Deinstallation benutzter Abhängigkeiten sperren.
4. Katalog, Installer, Aktualisierung und Datenverwaltung in die eigene Oberfläche
   einbinden. Installierte Rezepte bleiben bis zum ausdrücklich gestarteten Update
   unverändert; Datenbankmigrationen benötigen einen gesicherten Rückweg.
5. Vollständige Katalog- und Laufzeitabnahme am veröffentlichten Image.

Die ersten beiden Compose-Laufzeittests bestanden auf GitHub:
https://github.com/ra5on/Titan/actions/runs/38038517761
Die Host-/HTTP-Erweiterung und nachfolgende Änderungen sind davon getrennt zu prüfen.

Auch der echte Host-/HTTP-Lauf für Memos bestand:
https://github.com/ra5on/Titan/actions/runs/38039178969
Geprüft wurden Installation, Start/Stop/Neustart einzelner Container und des Pakets,
Dateizugriff während der Installation und Deinstallation bei erhaltenen Daten.
Die gesamte Python-Suite vor den Appupdate-Ergänzungen bestand lokal mit
2.004 Tests (12 übersprungen); die anschließenden Katalog-/Updateprüfungen
werden zusätzlich separat und in CI ausgeführt.

Die Store-Suche und die Kategorien erfassen jetzt beide Quellen gemeinsam.
Installierte Umbrel-Pakete erscheinen dabei einmal. Der Katalog wird beim ersten
Öffnen durch einen Administrator automatisch geladen; bei einem Fehler bleibt
eine manuelle Wiederholung möglich. Gleichzeitige Abrufe werden zusammenhängend
gesperrt, ohne den zuletzt verwendbaren Katalog zu ersetzen. Diese Bedienverbesserung
ändert die oben ausgewiesene Kompatibilitätsgrenze nicht.

Paketdateien werden vor dem Schreiben vollständig auf Größe, Pfad und SHA256
geprüft. Neue Dateien werden atomar ohne Überschreiben veröffentlicht; vorhandene
Konfiguration bleibt bei Wiederinstallation unverändert. Links und Verzeichnisse
an einem Dateiziel werden abgelehnt. Doneticks öffentlicher JWT-Vorgabeschlüssel
wird bei der ersten Installation durch einen zufälligen privaten Schlüssel ersetzt.
Der Donetick-Lauf prüft diesen Pfad zusätzlich in Compose und im HTTP-Installer;
der erste Lauf dieser Erweiterung ist noch abzuwarten.
