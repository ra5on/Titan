# Titan · Debian NAS · Alpha

Titan wird als eigenes NAS-System auf **Debian 13** entwickelt, einschließlich Dateimanager, App Store, Docker-Netzen, virtuellen Maschinen, Freigaben, Diensten und Web-Terminal.

**Alpha: Das Debian-A/B-Testimage ist verfügbar. Noch nicht für produktive Daten verwenden.**

[**Titan 0.4.6-alpha.1 · IMG herunterladen**](https://github.com/ra5on/Titan/releases/download/v0.4.6-alpha.1/titan-0.4.6-alpha.1-amd64.img.xz) · [Prüfsummen und Testergebnisse](https://github.com/ra5on/Titan/releases/tag/v0.4.6-alpha.1) · [Proxmox-Anleitung](docs/TITAN-IMAGE.md)

**Aktuelles Systemupdate: [0.4.10-alpha.1](https://github.com/ra5on/Titan/releases/tag/v0.4.10-alpha.1).** Bestehende Installationen aktualisieren über den **Alpha-Kanal**; in älteren Oberflächen liegt die Auswahl unter **Einstellungen → Updates & Kanäle**, ab 0.4.8 unter **Updates & Rollback**. Kein erneuter Image-Import nötig. Neue Installationen starten mit dem oben verlinkten 0.4.6-IMG und aktualisieren anschließend.

Ein einzelnes komprimiertes IMG für eine neue x86-64-VM: UEFI/OVMF ohne Secure Boot, mindestens 4 GB RAM, 2 CPUs und 48 GiB Systemplatte. Nach dem Start `https://<NAS-IP>:5000` öffnen und den Administrator einrichten. Größere Systemplatten erweitern den Datenbereich.

## Oberfläche und Funktionen

- HTTPS auf Port **5000**, erste Administration direkt im Browser.
- Anpassbarer NAS-Desktop für Desktop und Mobilgeräte: Menü-Icons verschieben, Apps in Ordnern gruppieren und die Anordnung pro Benutzer speichern.
- LinuxServer.io als Standard-AppStore mit 73 gebündelten Vorlagen; weitere CasaOS- oder Titan-Stores hinzufügen, mehrere Stores aktivieren und filtern.
- Docker mit Installationsoptionen, eigenen Bridge-Netzen, festen IPs und Anmeldehinweisen.
- QEMU/KVM und libvirt mit sichtbaren Schnellaktionen, ISO-/Image-Auswahl, CPU-Zuordnung und integrierter Browserkonsole; ausgeschaltete VMs nachträglich auf BIOS/UEFI, Startreihenfolge, NAT, vorhandene Bridges oder macvtap einstellen. Gelöschte VM-Namen sind wieder verwendbar, vorhandene Laufwerke bleiben erhalten.
- SMB-Freigaben mit Lesen/Schreiben, Lesen oder keinem Zugriff pro Benutzer.
- Datei- und Ordnerverwaltung, Textbearbeitung unabhängig von Dateiendungen, Dienste und Web-Terminal.
- Gemessene CPU-/RAM-Werte und weitere Metriken, soweit die Hardware sie bereitstellt.

## Vollständige Systemupdates

Unter **Einstellungen → Updates & Rollback** signierte Debian-Systemversionen auf der zweiten Systempartition vorbereiten, den Neustart per Schaltfläche bestätigen und verfügbare Rückkehrstände über ein Dropdown auswählen. Zunächst den Kanal **Alpha** verwenden. Nach einem bestätigten Update steht der vorherige Systemstand zum Rollback bereit.

Boot, NAS-Laufzeit, Update, Neustart, Rollback, Rückfall nach einem fehlgeschlagenen Teststart und Erhalt von Benutzerkonten, Freigaberechten und Testdateien wurden in einer separaten QEMU-VM geprüft. Ein hängender Gast benötigt für den Rückfall einen Reset; persönliche Daten werden durch Rollback nicht zurückgesetzt. Die [Testgrenzen](docs/TITAN-IMAGE.md#prüfung-und-grenzen) bleiben für den Übergang zur Beta maßgeblich.

[Neuerungen 0.4.10](docs/RELEASE-0.4.10.md) · [AppStores und Importgrenzen](docs/APP-STORES.md) · [Debian-Stand](docs/DEBIAN-MIGRATION.md) · [Testimage/Proxmox](docs/TITAN-IMAGE.md) · [Lizenz](LICENSE) · [Entwicklung](docs/DEVELOPMENT.md)

## Lizenz

Der eigene Titan-Code darf für nichtkommerzielle Zwecke genutzt, verändert und kostenlos weitergegeben werden. Verkauf und andere kommerzielle Verwertung sind ohne gesonderte Erlaubnis ausgeschlossen. Das gilt auch für abgeleitete Versionen. Debian, Linux, Docker, Samba, noVNC und weitere Fremdkomponenten behalten ihre eigenen Lizenzen; unsere Beschränkungen ersetzen diese nicht.

Dies ist eine Source-available-Lizenz, keine OSI-Open-Source-Lizenz. [Details](docs/LICENSING.md)
