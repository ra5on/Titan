# Titan 0.8.0: Wiederherstellung und einfache Updates

## Erweiterter Auftrag: vollständige Stable-Veröffentlichung

Der Nutzer hat am 10. Oktober 2026 das Veröffentlichungsziel auf eine direkt
nutzbare Stable-Version konkretisiert. Die folgende Erweiterung ist ein
Abnahmeauftrag, keine Aussage über bereits erreichte Funktionsgleichheit.
Die älteren Prüfberichte unten gelten ausschließlich für ihre genannten Stände.

- Funktionsumfang und Bedienabläufe orientieren sich am verlinkten TitanOS
  (https://github.com/ra5on/TitanOS), einschließlich Speicher- und VM-Verwaltung.
  Login, Desktop und VM-Darstellung werden eigenständig gestaltet und umgesetzt.
  Das Ändern der Oberfläche hebt keine Lizenzpflicht für übernommenen Backend-Code auf.
- QCOW2 muss unmittelbar als VM-Bootplatte importierbar sein, per Upload und
  Auswahl vom NAS, ohne manuelle Konvertierung. Abnahme: ein echtes Gastbetriebssystem
  starten, Konsole bedienen, herunterfahren und nach Hostneustart wieder starten;
  defekte Images und nicht auflösbare externe Backing-Dateien sicher behandeln.
- Der gewünschte vollständige Appstore ersetzt den bisherigen begrenzten Katalog.
  Der Nutzer hat den Umbrel-Katalog mit eigener Titan-Oberfläche gewählt und
  die Umsetzung ausdrücklich beauftragt. Umbrels Store-Oberfläche wird nicht übernommen.
  Installation, Erreichbarkeit, Persistenz, Updates, Fehlerbehandlung und
  Deinstallation mit klarer Entscheidung über Nutzdaten müssen abgenommen werden.
- Ein gemeinsamer Update-Button bleibt erhalten; Veröffentlichungen kommen
  weiterhin über den eigenen GitHub-Kanal. Signaturprüfung, tatsächlicher Wechsel,
  Neustart, Bootbestätigung und Rückfall müssen mit veröffentlichten Artefakten
  geprüft werden.
- Vollständige Wiederherstellung auf getrennten Ersatzdatenträgern bleibt Pflicht:
  Konten, Freigaben und Rechte, App-Datenbanken und VM-Platten nach Restore praktisch
  verwenden; Unterbrechung und Wiederaufnahme prüfen. Ein Rettungsplan allein ist
  keine Datensicherung.

Vor der Stable-Freigabe benötigt jeder zugesagte Bereich einen nachvollziehbaren
Nachweis für denselben Release-Kandidaten. Offene Kernfunktionen, fehlgeschlagene
oder übersprungene Pflichtprüfungen sperren die Veröffentlichung als Stable.
Quelltests, Image-/VM-Laufzeittests und physische Hardwareprüfungen werden getrennt
ausgewiesen. Dokumentierte Hardwaregrenzen bleiben auch bei einer Stable-Version
bestehen. Kein Beta-Etikett ersetzt die Fertigstellung; umgekehrt ersetzt das
Stable-Etikett keine erfolgreiche Abnahme.

Arbeitsbasis: 0.7.0, `e0b8a80`. Nutzerauftrag vom 10. Oktober 2026:
Ersatzhardware-Wiederherstellung und ein gemeinsamer Update-Button. Keine USV
vorhanden; USV-Hardwareabnahme ist keine Voraussetzung dieses Auftrags.

## Zielbetrieb: Titan direkt auf der Hardware

Am 10. Oktober konkretisiert: Titan soll direkt auf dem Rechner laufen und
Proxmox ersetzen. Testausstattung ist laut Nutzer vorhanden. Anschließend präzisiert: breite
Hardware-Kompatibilität, keine Bindung an einen bestimmten Testrechner. Die
Entwicklung hängt daher nicht von weiteren Angaben zu einem einzelnen Host ab. Eine
Proxmox-VM bleibt eine isolierte Entwicklungsumgebung, nicht die abschließende
Abnahme des Zielbetriebs. Es wird keine bestehende Proxmox-Installation aufgrund
dieser allgemeinen Zielbeschreibung überschrieben.

Für die Abnahme werden repräsentative AMD64-Konfigurationen und unterschiedliche
Speicher-/Netzwerkgeräte benötigt. Eine universelle Kompatibilitätszusage für
alle Architekturen oder Controller ergibt sich daraus nicht. Zu prüfen sind:

- Installation und UEFI-Start von der freigegebenen Systemplatte; Kaltstart,
  geordneter Neustart sowie Auswahl und Rückfall der A/B-Systemstände.
- Erkennung von Netzwerkadaptern und Speichercontrollern, tatsächlich nutzbare
  Datenlaufwerke und stabile Laufwerkszuordnung auch nach geändertem Anschluss.
- Netzwerkzugang nach Neuinstallation und Wiederherstellung, einschließlich
  einer erreichbaren lokalen Fehlerbehebung bei geänderter Netzwerkkarte.
- Native KVM-Virtualisierung: ein tatsächlich installiertes Gastbetriebssystem
  starten, geordnet herunterfahren und nach einem Hostneustart erneut starten.
  USB-/PCI-Durchreichung nur für die konkret benötigten Geräte zusagen und prüfen.
- Vollständige Wiederherstellung auf leerer Ersatzhardware mit abgetrennter
  Originalsystemplatte: Konten, SMB-Rechte, ACLs, App-Datenbanken und VM-Platten
  prüfen; Anwendungen und einen Gast tatsächlich starten. Geänderte
  Laufwerkskennungen und Netzwerkkarten gehören ausdrücklich in den Test.
- Unterbrechung der Wiederherstellung in einer entbehrlichen Testumgebung:
  unvollständige Daten dürfen nicht als erfolgreich wiederhergestellt gelten
  oder unkontrolliert mit gestarteten Anwendungen verwendet werden.

Das Ablösen von Proxmox ist keine Zusage, vorhandene Proxmox-Konfigurationen,
LXC-Container oder Clusterfunktionen automatisch zu übernehmen. Falls vorhandene
Workloads migriert werden sollen, werden deren Sicherungen und Importpfade vor
Änderungen am bisherigen Host gesondert geprüft.

## Geplante Umsetzung und Abnahme

1. Ein Updateangebot für Titan. Beide signierten Veröffentlichungswege werden
   geprüft; der Nutzer wählt keinen technischen Updatebereich. Ein persistenter
   Auftrag aktualisiert zuerst die Oberfläche, setzt sich im neuen Prozess fort
   und bereitet anschließend den Systemstand für den bestätigten Neustart vor. Unterbrechungen, geänderte Angebote,
   Rechteentzug und Rückfall müssen sichtbar bleiben. Details und manuelles
   Rollback gehören in einen aufklappbaren Bereich.
2. Vollständige Wiederherstellung benötigt mehr als den bisherigen
   Konfigurationsimport: Konten/SMB, ACLs, Daten, Apps samt Datenbanken, VM-Disks
   und Dienstkonfiguration. Sicherungsumfang vorab inventarisieren; fehlende oder
   nicht unterstützte Datenträger dürfen nicht als vollständig gesichert gelten.
   Kalte Sicherung mit angehaltenen Schreibern, geprüfte Archivpfade und Metadaten,
   verifizierte Übertragung, genügend Zielplatz, unveränderte Quelle und
   Wiederanlauf nach Unterbrechung sind Pflicht.
3. Die frische Zielinstallation darf keine bestehenden Nutzdaten überschreiben.
   Herkunft, kompatibler Systemstand, Speicherzuordnung und Vollständigkeit werden
   vor Änderungen geprüft. Die bisherige sichere Same-Host-Prüfung wird nicht
   einfach abgeschaltet. Wiederherstellung muss auf einer getrennten frischen
   Testinstallation mit gelöschtem altem System und tatsächlichen Nutzdaten
   abgenommen werden.
4. Regression: gezielte Zustands-/Negativtests, vollständige Python/UI-Suiten,
   Browserprüfung des vereinfachten Ablaufs und Recovery-Dialogs sowie reale
   Container-/UEFI-/SMB-/Update-/Wiederherstellungstests auf isolierten Runnern.
5. Veröffentlichung erst nach den relevanten Gates. Bekannte Grenzen und
   verbleibende Hardwareprüfungen konkret dokumentieren; keine pauschale
   Behauptung, sämtliche Hardware oder Stromausfälle seien geprüft.

## Nicht durch eine Versionskennung gelöst

Reale Controller-/Plattenkompatibilität und Dauerbetrieb brauchen die konkrete
Zielhardware. Ein Test in QEMU ist davon getrennt zu berichten. Vorhandene
historische Backupformate bleiben lesbar; ein Teilbackup darf nicht nachträglich
als vollständige Disaster-Recovery-Sicherung bezeichnet werden.

## Arbeitsstand, noch keine Freigabe

Der gemeinsame manuelle Updateauftrag und die vereinfachte Seite sind implementiert.
Die Archivschicht für Recovery bewahrt Sparse-Dateien, Hardlinks, Dateirechte und
Xattrs und prüft Archivpfade sowie Prüfsummen vor der Extraktion.

Noch offen sind der vollständige Recovery-Hostablauf (konsistentes Anhalten,
Inventarisierung aller Speicher, Zielzuordnung einschließlich ZFS, Wiederanlauf
nach Unterbrechung), dessen Bedienoberfläche und die Abnahme auf einer getrennten
frischen Installation. Die Archivtests allein belegen keine vollständige
Wiederherstellung. Automatische Updates verwenden bislang weiterhin den
bestehenden Systemupdate-Zeitplan. Für diese Arbeit wurde noch kein Stable-Release
erstellt; Version und bestehende Releases bleiben unverändert.

### Lokale Prüfungen vom 10. Oktober

- Vollständige Python-Suite: 1962 Tests, erfolgreich, 12 übersprungen.
- Nachfolgende Änderungen zusätzlich gezielt geprüft: 20 gemeinsame
  Updateabläufe, 10 Archivtests, 17 HTTP-Tests und 73 bestehende Updatetests.
- Alle 80 JavaScript-Verhaltenstests erfolgreich.
- Browser: gemeinsame Suche in der isolierten Demo ausgeführt; die Oberfläche
  zeigte anschließend ausdrücklich den Demo-Status. Eine echte Installation
  und die Wiederherstellung eines vollständigen NAS sind damit nicht belegt.

### GitHub-Quellprüfung

Der Entwurfsstand `7b42c59` bestand sowohl den Push- als auch den PR-Lauf:
[Push-CI](https://github.com/ra5on/Titan/actions/runs/38033859681),
[PR-CI](https://github.com/ra5on/Titan/actions/runs/38033874817).
Dies sind Quell-/API-/UI-Prüfungen, keine neue Image- oder Hardwareabnahme.

### Breitere Hardwarebasis im Build

Der Build fordert nun ausdrücklich `linux-image-amd64`, Realtek-/BNX2-/BNX2X-/
QLogic-/sonstige Debian-Firmware sowie Intel-/AMD-Microcode an. `MODULES=most`
fixiert die portable Initramfs-Konfiguration unabhängig von der Build-Appliance.
Die neue Build-Prüfung `image/debian/ab/verify-initramfs.sh` verweigert einen
Cloud-Kernel und prüft wichtige Bootmodule gegen den tatsächlich ausgelieferten
Kernel und das erzeugte Initramfs. Eingebaute Module sowie komprimierte Module
und usr-merged Pfade werden unterstützt.

Grundlagen: [Debian Initramfs-Konfiguration](https://manpages.debian.org/trixie/initramfs-tools-core/initramfs.conf.5.en.html),
[Realtek-Firmware](https://packages.debian.org/trixie/firmware-realtek),
[QLogic-Firmware](https://packages.debian.org/trixie/firmware-qlogic).

Sechs ausführbare Tests prüfen die neue Build-Sperre mit Modulverzeichnissen
und Initramfs-Inventaren, einschließlich fehlendem NVMe-Treiber, falscher
Kernelzuordnung und fehlgeschlagener Auflistung. Die 141 bestehenden Debian-Tests bestehen ebenfalls (einer übersprungen),
einschließlich der elf Storage-Komponententests. Ein neues Image mit diesen
Änderungen wurde noch nicht gebaut oder auf physischer Hardware gestartet.
