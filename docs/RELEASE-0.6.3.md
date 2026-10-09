# Titan Weboberfläche 0.6.3

Eigenständiges Webupdate für die Systembasis 0.6.1, einschließlich der WebUI-Verbesserungen aus 0.6.2.

## Datei-Uploads

- Browser übertragen gewöhnliche Dateien direkt binär statt als Base64 in JSON. Das vermeidet die rund 33 Prozent zusätzliche HTTP-Nutzlast und die große Zeichenkettenkonvertierung im Browser.
- Blöcke wachsen von 1 auf 4 MiB, innerhalb der bereits vorhandenen Grenze des Host-Agenten. Große Dateien benötigen damit ein Viertel der Blockanfragen und Workerstarts.
- Fortschritt zeigt die durchschnittliche bestätigte Übertragungsrate in MB/s und die geschätzte Restzeit.
- ISO-Uploads behalten aus Kompatibilitätsgründen ihre 1-MiB-Blöcke und das vorhandene Protokoll. FileReader übernimmt dort die Base64-Konvertierung; Abbrechen bleibt möglich.
- Rechteprüfung, CSRF-/Origin-Prüfung, private temporäre Dateien, Offsetprüfung, Abbruch und atomarer Abschluss bleiben erhalten. Ein Dateiabschluss benötigt weiterhin eine separate bestätigte Anfrage.

## Messung und Grenzen

Lokaler Vergleich mit dem echten unprivilegierten Datei-Worker, privaten temporären Dateien, Synchronisation und Prüfsummen: 32 MiB benötigten mit 1-MiB-Blöcken 8,096 Sekunden, mit 4-MiB-Blöcken 2,477 Sekunden (3,95 gegenüber 12,92 MiB/s). Dies misst den Worker auf dem Entwicklungsrechner, nicht das Benutzer-NAS und nicht dessen Netzwerk. Es ist kein Nachweis für eine Auslastung von 2,5-Gbit-Ethernet.

Nur Browser–WebUI ist jetzt binär. Die WebUI nutzt intern weiterhin das kompatible Base64-Agentenprotokoll. Der Host startet weiterhin einen berechtigten Datei-Worker pro Block und synchronisiert Daten und Journal; diese verbleibenden Kosten verschwinden durch das Webupdate nicht. Ein dauerhaft streamender Host-Upload benötigt eine gesonderte Änderung mit Sicherheits- und Wiederanlauftests.

## Prüfung

- 78 JavaScript-Suiten bestehen, einschließlich Blockgrenzen, binärer Metadaten, Zielbindung bei Navigation, Abbruch, leerer Dateien, verspäteter Antworten und Abschlussbestätigung.
- 41 HTTP-/Upload-Tests bestehen, einschließlich bytegenauer binärer Übertragung eines 4-MiB-Blocks mit Unicode-Dateiname sowie CSRF, Origin, Metadaten und Größenbegrenzung.
- Browserprüfung der lokalen Demo: 16-MiB-Datei über den neuen binären Weg vollständig hochgeladen; SHA-256 von Quelle und gespeicherter Datei identisch. Die Demo ersetzt keinen Test des Host-Agenten auf dem NAS.

Installation nach Veröffentlichung: **Systemsteuerung → Updates & Rollback → Weboberfläche → Jetzt prüfen → Aktualisieren**. Laufende Uploads vorher abschließen. Kein neues NAS-Installationsimage erforderlich.
