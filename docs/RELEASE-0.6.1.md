# Titan 0.6.1

Diese Version ist die neue Installationsbasis. Bitte neu installieren; eine direkte Migration älterer Titan-Installationen ist für diesen Architekturwechsel nicht freigegeben. Die dreiteilige Versionsnummer bezeichnet den Softwarestand, keine Produktionsfreigabe.

## Weboberfläche im Container

Das Installationsimage enthält den vollständigen Webcontainer. Beim ersten Start wird er lokal geladen; ein Registry-Zugang ist dafür nicht notwendig. Caddy und der privilegierte Titan-Agent bleiben auf dem Host. Der Webprozess läuft mit der bestehenden Titan-Benutzerkennung, schreibgeschütztem Container-Dateisystem, ohne Linux-Capabilities und ohne Docker-Socket. Konfiguration und Datenbank liegen weiterhin persistent unter `/var/lib/titan`.

Unter **Systemsteuerung → Updates & Rollback → Weboberfläche** lassen sich signierte Webupdates getrennt vom Betriebssystem prüfen und installieren. Der Host lädt das signierte Containerarchiv aus der GitHub-Veröffentlichung und prüft Größe, SHA-256, Image-ID, Version und Protokoll. Eine fehlgeschlagene Gesundheitsprüfung startet das vorherige Webimage. Laufende Apps und VMs werden nicht neu gestartet; Webkonsole und Browser müssen sich nach dem Wechsel neu verbinden.

Ein Webrollback setzt keine Nutzdaten zurück. Innerhalb des Datenvertrags 1 müssen alle Webversionen dieselbe Datenbank lesen können. Inkompatible Datenänderungen benötigen einen neuen Vertrag und dürfen nicht als gewöhnliches Webupdate erscheinen.

## Korrekturen

- Passwortprüfung mit genau einer scrypt-Berechnung und höherem Arbeitsfaktor.
- Sicherung und Wiederherstellung erkennen das neue Passwortformat.
- Jellyfin erhält nur Lesezugriff auf den Medienordner.
- Kurze Statusabfragen werden zwischen Desktop-Fenstern zusammengefasst.
- Der Titan-Webcontainer lässt sich nicht versehentlich über die allgemeinen Containeraktionen stoppen oder löschen.

## Prüfumfang

Die Veröffentlichung wird durch automatisierte Quell-, Container- und QEMU-Systemprüfungen abgesichert. Die Containerprüfung allein verwendet einen simulierten Host-Agenten; die Installationsimage-Prüfung startet den tatsächlichen Agenten. Reale NAS-Hardware, längerer Dauerbetrieb und vollständige Browserdarstellung bleiben eigenständige Abnahmepunkte.
