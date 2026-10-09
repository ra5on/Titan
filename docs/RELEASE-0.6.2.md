# Titan Weboberfläche 0.6.2

Eigenständiges Webupdate für die neu installierte Systembasis 0.6.1. Kein neues NAS-Installationsimage und kein Wechsel des Host-Agenten.

## Verbesserungen

- Desktopaufbau wartet nicht mehr auf Monitoring, Docker-Apps und VM-Erkennung. Gespeicherte Verknüpfungen bleiben erhalten; ausstehende Informationen werden nachgeladen.
- Langsame App- und VM-Abfragen werden nicht gleichzeitig mehrfach gestartet.
- Gemeinsame Statusabfragen mehrerer Fenster werden zusammengeführt, auch wenn eine Antwort länger als die Cachefrist dauert.
- Unveränderte JavaScript-, CSS-, Icon- und Schriftdateien werden vom Browser nach ETag-Prüfung wiederverwendet. Neue Inhalte werden sofort erkannt; HTML mit Sicherheitsnonce und API-Antworten bleiben ungecached.
- Der Dateimanager lädt seine Startinformationen parallel. Scheitert eine Ordnerabfrage, bleiben die Seitenleiste und die Auswahl anderer Freigaben bedienbar; Schreibaktionen im fehlerhaften Ordner sind gesperrt.
- Veralteter Alpha-Schriftzug auf dem Desktop entfernt.

## Prüfung und Grenzen

77 JavaScript-/UI-Testsuiten und 14 HTTP-Tests bestehen lokal. Neue Regressionstests prüfen den Desktopstart bei ausstehenden Docker-/VM-Abfragen, die Wiederherstellung der Dateiansicht nach einem fehlenden Ordner, langsame gemeinsame Abfragen sowie ETag/304 und die Cache-Ausnahme für HTML und API.

Die Browser-Demo wurde für Desktop, Dateimanager, AppStore und VM-Verwaltung in Hell/Dunkel geprüft; sie ersetzt keine Hardwareprüfung. Der gemeldete fehlende Ordner „Daten“ auf dem Benutzer-NAS konnte ohne dessen Speicherzustand nicht als konkrete Ursache reproduziert werden. Der Fehlerfall blockiert mit dieser Änderung nicht mehr den gesamten Dateimanager. Es werden keine fehlenden Datenordner automatisch angelegt und keine Speicherpfade umgeleitet.

Installation: **Systemsteuerung → Updates & Rollback → Weboberfläche → Jetzt prüfen → Aktualisieren**. Uploads und interaktive Konsolen vorher abschließen.
