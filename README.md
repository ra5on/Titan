# Titan

**Dein NAS. Deine Dateien. Deine Anwendungen.**

Titan ist eine eigenständige NAS-Oberfläche auf Debian mit persönlichem Desktop, Dateimanager, Freigaben, virtuellen Maschinen und Docker-Verwaltung.

**Entwicklungsstand: 0.5.3 · Alpha.** Dieser Quellstand ist noch keine neue Image-Veröffentlichung und keine Freigabe für produktive Daten.

![Titan Desktop](docs/images/desktop-control-panel.jpg)

## Docker mit BigBear

Unter **App Store → BigBear-Katalog** lassen sich unterstützte Docker-Compose-Vorlagen laden. Vor der Installation wählst du Speicherbereich, Ports, Zugangsdaten und gegebenenfalls Netzwerk sowie Geräte aus. Datenbanken und Zusatzdienste werden als zusammengehöriger Stack eingerichtet.

- Anwendungen und einzelne Dienste starten, stoppen und neu starten.
- Status, Abhängigkeiten, Protokolle und Einstellungen an einem Ort ansehen.
- Installierte Vorlagen dauerhaft speichern; ein Katalog-Refresh verändert keine laufenden Stacks.
- Beim Deinstallieren Konfiguration, Datenbanken und Nutzdaten erhalten.
- Nicht unterstützte Vorlagen mit konkretem Grund anzeigen.

BigBear-Vorlagen werden bei Bedarf vom Herausgeber abgerufen und nicht mit Titan ausgeliefert. Die Importprüfung ersetzt keine Betriebsprüfung jeder einzelnen Anwendung. Nutzungsbedingungen der Vorlagen, Bilder und Anwendungen gelten unabhängig von Titan.

![Docker-Verwaltung](docs/images/docker-stacks.jpg)

## Weitere Funktionen

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
