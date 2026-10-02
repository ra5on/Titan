# Titan · Debian NAS · Alpha

Titan wird als eigenes NAS-System auf **Debian 13** entwickelt. Dies ist der neue Entwicklungsstand des bisherigen RaNAS-Projekts, einschließlich Dateimanager, App Store, Docker-Netzen, virtuellen Maschinen, Freigaben, Diensten und Web-Terminal.

**Alpha: Der Debian-Unterbau wird gerade auf vollständige Systemupdates mit Rollback umgebaut. Ein Titan-Installationsimage wird erst nach erfolgreichen Boot- und Update-Tests veröffentlicht. Noch nicht für produktive Daten verwenden.**

## Oberfläche und Funktionen

- HTTPS auf Port **5000**, erste Administration direkt im Browser.
- Anpassbarer NAS-Desktop für Desktop und Mobilgeräte.
- Docker/App Store mit Installationsoptionen, eigenen Bridge-Netzen, festen IPs und Anmeldehinweisen.
- QEMU/KVM und libvirt mit ISO-/Image-Auswahl, CPU-Zuordnung und Browserkonsole.
- SMB-Freigaben mit Lesen/Schreiben, Lesen oder keinem Zugriff pro Benutzer.
- Datei- und Ordnerverwaltung, Textbearbeitung unabhängig von Dateiendungen, Dienste und Web-Terminal.
- Gemessene CPU-/RAM-Werte und weitere Metriken, soweit die Hardware sie bereitstellt.

## Vollständige Systemupdates

Ziel ist **Einstellungen → Updates & Rollback**: signierte Debian-Systemversionen auf einer zweiten Systempartition vorbereiten, Neustart bestätigen und verfügbare Rückkehrstände über ein Dropdown auswählen. Diese Funktion ist im Aufbau und wird erst nach echten Update-, Neustart- und Rückfalltests als verfügbar ausgewiesen.

[Debian-Stand](docs/DEBIAN-MIGRATION.md) · [Testimage/Proxmox](docs/DEBIAN-PREVIEW.md) · [Lizenz](LICENSE) · [Entwicklung](docs/DEVELOPMENT.md)

## Lizenz

Der eigene Titan-Code darf für nichtkommerzielle Zwecke genutzt, verändert und kostenlos weitergegeben werden. Verkauf und andere kommerzielle Verwertung sind ohne gesonderte Erlaubnis ausgeschlossen. Das gilt auch für abgeleitete Versionen. Debian, Linux, Docker, Samba, noVNC und weitere Fremdkomponenten behalten ihre eigenen Lizenzen; unsere Beschränkungen ersetzen diese nicht.

Dies ist eine Source-available-Lizenz, keine OSI-Open-Source-Lizenz. [Details](docs/LICENSING.md)
