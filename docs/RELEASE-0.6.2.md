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

Die Browser-Demo wurde für Desktop, Dateimanager, AppStore VM-Verwaltung, Docker und Einstellungen in Hell/Dunkel geprüft; sie ersetzt keine Hardwareprüfung. Der gemeldete fehlende Ordner „Daten“ auf dem Benutzer-NAS konnte ohne dessen Speicherzustand nicht als konkrete Ursache reproduziert werden. Der Fehlerfall blockiert mit dieser Änderung nicht mehr den gesamten Dateimanager. Es werden keine fehlenden Datenordner automatisch angelegt und keine Speicherpfade umgeleitet.

Installation: **Systemsteuerung → Updates & Rollback → Weboberfläche → Jetzt prüfen → Aktualisieren**. Uploads und interaktive Konsolen vorher abschließen.

## Veröffentlichungsnachweis

- [Webrelease web-v0.6.2](https://github.com/ra5on/Titan/releases/tag/web-v0.6.2), gebaut aus `1c8381fbf4d5603ced3dd0999447b625d81aa771` im erfolgreichen [Containerworkflow](https://github.com/ra5on/Titan/actions/runs/37967673853).
- Echter Containerstart, persistente Daten und Rückfall bei fehlgeschlagener Gesundheitsprüfung bestanden.
- Das heruntergeladene Manifest wurde mit dem vertrauenswürdigen Repository-Schlüssel verifiziert. GitHub-Assetgrößen und -Digests stimmen für Webcontainer und Debian-Quellarchiv mit dem signierten Manifest überein; kein vollständiger erneuter Download der großen Archive.
- Der echte lesende Updater erkennt 0.6.2 als verfügbares signiertes Update; für diese Prüfung war lediglich die lokale installierte Auswahl auf 0.6.1 gesetzt.
- GHCR-Pull ist ohne Benutzeranmeldung möglich (anonymer Registry-Token).
- Registry-Digest: `sha256:abcff1d2418b95074420534243ca74020548927b945d8fa314c864ea940a91c3`.
- Webarchiv: 76.090.116 Bytes, SHA-256 `1b628eec80b3e478f69da419472acbbe84c5ce0baa44f8dfc8d6c5f6ff39cf12`.
- [Debian-Integration](https://github.com/ra5on/Titan/actions/runs/37967674632) und [App-Laufzeitprüfungen](https://github.com/ra5on/Titan/actions/runs/37967675173) bestanden.

Die Browserprüfung bei 390 Pixel Breite zeigte keinen horizontalen Überlauf. Die tatsächliche Ladezeit auf dem Benutzer-NAS und dessen Speicherzustand bleiben gesondert zu prüfen.

Die vollständige [CI nach Korrektur der HTTP-Testfixture](https://github.com/ra5on/Titan/actions/runs/37968936645) bestand ebenfalls. Die Fixture-Korrektur verändert das veröffentlichte Laufzeitverhalten nicht.
