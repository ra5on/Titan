# Titan

**Dein NAS. Deine Dateien. Deine Anwendungen.**

Titan ist eine eigenständige NAS-Oberfläche auf Debian mit persönlichem Desktop, Dateimanager, Freigaben, virtuellen Maschinen und Docker-Verwaltung.

**Version: 0.5.5-alpha.1 · Alpha.** Zunächst mit Testdaten verwenden.

[**Image herunterladen · AMD64 (.img.xz)**](https://github.com/ra5on/Titan/releases/download/v0.5.5-alpha.1/titan-0.5.5-alpha.1-amd64.img.xz) · [Release, Checksummen und Prüfberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.5-alpha.1)

Für den VM-Test: **UEFI/OVMF**, **Secure Boot aus**, **8 GiB RAM** und mindestens **64 GiB Festplatte**. Die `.img.xz` entpacken; das enthaltene Image ist 48 GiB groß. Die virtuelle Festplatte vor dem ersten Start auf die gewünschte Größe erweitern. Danach Titan unter `https://NAS-IP` öffnen.

Neuinstallationen verwenden **HTTPS auf Port 443** mit automatischer Weiterleitung von **HTTP auf Port 80**. Unter **Systemsteuerung → Allgemein → Webzugriff** sind Modus und Ports einstellbar. Eine neue Adresse innerhalb von **120 Sekunden** bestätigen; sonst wird die bisherige Einstellung wiederhergestellt. Bestehende Installationen behalten bei einem Update ihre bisherige Adresse, bis du sie dort änderst.

![Titan Desktop · Demoansicht](docs/images/titan-desktop-bigbear.jpg)

## Docker mit BigBear

Der AppStore lädt den BigBear-Katalog automatisch im Hintergrund und speichert ihn lokal. Ladezustand und zusätzliche Anforderungen einzelner Vorlagen sind sichtbar. Vor der Installation wählst du Speicherbereich, Ports, Zugangsdaten und gegebenenfalls Netzwerk sowie Geräte aus. Datenbanken und Zusatzdienste werden als zusammengehöriger Stack eingerichtet.

Administratoren können im Dateimanager und Terminal einen zeitlich begrenzten **Root-Modus** aktivieren. Dafür werden das aktuelle Passwort und bei aktivierter Zwei-Faktor-Anmeldung ein Sicherheitscode erneut geprüft. Die Freigabe gilt nur für diese Anmeldung; Betriebssystembereiche werden nicht automatisch beschreibbar gemacht.

- Anwendungen und einzelne Dienste starten, stoppen und neu starten.
- Status, Abhängigkeiten, Protokolle und Einstellungen an einem Ort ansehen.
- Installierte Vorlagen dauerhaft speichern; ein Katalog-Refresh verändert keine laufenden Stacks.
- Beim Deinstallieren Konfiguration, Datenbanken und Nutzdaten erhalten.
- Nicht unterstützte Vorlagen mit konkretem Grund anzeigen.

BigBear-Vorlagen werden bei Bedarf vom Herausgeber abgerufen und nicht mit Titan ausgeliefert. Die Importprüfung ersetzt keine Betriebsprüfung jeder einzelnen Anwendung. Nutzungsbedingungen der Vorlagen, Bilder und Anwendungen gelten unabhängig von Titan.

![Docker-Verwaltung](docs/images/docker-stacks.jpg)

## Weitere Funktionen

Im Benutzermenü lassen sich Desktop-Transparenz und das Verhalten beim Klick auf freien Desktop pro Konto einstellen. Die Seitenleisten von Systemsteuerung, Speicher, Docker und VM-Verwaltung können per Trennlinie schmaler oder breiter gezogen werden. [Bedienung und Platznutzung](docs/UI-DESIGN.md).

**Fernzugriff:** Unter **Systemsteuerung → Allgemein** eine öffentliche HTTPS-Adresse und den Cloudflared-Connector einrichten. Titan zeigt das passende Tunnelziel für Host- oder Bridge-Netz und prüft lokale sowie öffentliche Erreichbarkeit. Die Tunnelroute wird weiterhin in Cloudflare eingerichtet. Das Verwaltungspasswort von Cloudflared Web ist bei neuen Installationen optional. [Einrichtung und Diagnose](docs/REMOTE-ACCESS.md)

**VMs und App-Sicherungen:** Kompakte VM-Kacheln zeigen echte CPU- und RSS-Messwerte; ein Klick öffnet die Details. Der zentrale Sicherungsassistent kann App-Konfiguration, Datenbanken und Zugangsdaten sowie ausdrücklich ausgewählte Nutzdaten auf einem getrennten Ziel sichern. [VM-Verwaltung](docs/PACKAGES-AND-VMS.md) · [App-Sicherungen und Wiederherstellung](docs/BACKUPS.md)

| Bereich | Funktionen |
| --- | --- |
| Desktop | Fenster, Verknüpfungen, persönliche Anordnung, mobile Ansicht |
| Dateien | Vorschau, Texteditor, Ordner, Kopieren, Verschieben, Papierkorb |
| Speicher | Ext4, XFS und ZFS, Speicherbereiche und Laufwerksstatus |
| Benutzer | Konten, Gruppen, Freigaberechte und Anmeldeschutz |
| Virtuelle Maschinen | KVM/libvirt, BIOS/UEFI, Netzwerke und Browserkonsole |
| System | Ressourcen, Dienste, Sicherungen und signierte Updates mit Rollback |

[Docker und Katalog](docs/APP-STORES.md) · [Entwicklung](docs/DEVELOPMENT.md) · [Lizenz](LICENSE)

Der eigene Titan-Code ist für nichtkommerzielle Nutzung, Änderungen und kostenlose Weitergabe freigegeben. Kommerzielle Rechte können vom Rechteinhaber gesondert erteilt werden. Drittkomponenten behalten ihre jeweiligen Lizenzen.
