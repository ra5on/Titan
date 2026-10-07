# Paketzentrum und VM-Verwaltung

## Vier verwaltete Pakete

Titan bietet Immich, AdGuard Home, Pi-hole und Nextcloud mit Euro-Office an.
Datenbank, Cache, Hintergrundaufgaben und Office gehören zur jeweiligen
Installation. Der Paketstatus prüft jeden Dienst: Ein laufender Hauptcontainer
allein ist kein Beleg für ein funktionierendes Paket. Der einmalige
Office-Einrichtungscontainer gilt nach erfolgreichem Ende als abgeschlossen.

Im Paketdialog stehen Übersicht, Einstellungen und Protokolle zur Verfügung.
Protokolle können für jeden Dienst geladen werden; gespeicherte Zugangsschlüssel
werden ausgeblendet. Diagnose prüft Datenordner, Netzwerk, Geräte und Dienste.
Reparieren erstellt fehlende Container erneut und prüft die Office-Verbindung.
Gespeicherte Daten und generierte Schlüssel bleiben erhalten.

Ports und die NAS-Adresse des Office-Pakets können bei vollständig gestopptem
Paket verändert werden. Konten und Passwörter werden in der jeweiligen App
verwaltet, weil Startumgebungsvariablen bereits angelegte Nextcloud- und
Datenbankkonten nicht zuverlässig verändern.

Titan verwendet freigegebene Paketvorlagen und übernimmt beim Update alle
zugehörigen Dienste gemeinsam. Die installierte Definition wird mit einem
Digest in den geschützten Verwaltungsdaten festgehalten. Eine spätere
Titan-Version darf eine neue Vorlage anbieten, ohne dass die bisherige
Installation als fremder Container behandelt wird. Veränderte Definitionen ohne
passenden Digest werden weiter blockiert.

Vor Einstellungen und Paketupdates wird eine kalte Sicherung des privaten
App-Verzeichnisses erstellt. Sie enthält Konfiguration, interne Datenbanken und
Verbindungsschlüssel. Fotos, Dokumente und andere Nutzdaten im separat gewählten
Datenordner gehören nicht zu dieser Sicherung und müssen zusätzlich über die
Dateisicherung gesichert werden. Ein fehlgeschlagenes Update startet nach einer
möglichen Datenbankmigration keine älteren Images automatisch. Diagnose und
Reparatur bleiben verfügbar; der Pfad der vorherigen Sicherung wird angezeigt.

Das Euro-Office-Paket stellt dem privilegierten Office-Gateway eine verifizierte
interne Containeradresse und den Verbindungsschlüssel bereit. Der Schlüssel
besitzt keine öffentliche HTTP-Leseroute. Die Dokumentintegration prüft
Dateiberechtigungen und Revisionen beim Öffnen und beim Speichern. Bei einer
ODF-Datei wird ein vom Editor geliefertes OOXML-Ergebnis vor dem Speichern zurück
in das ursprüngliche Format konvertiert.

## VM-Register

Die Maschinenübersicht verwendet kompakte Kacheln mit Name, Status, CPU live und
**RAM auf NAS (RSS)**. RSS ist der gemessene residente Speicher des VM-Prozesses
einschließlich Verwaltungsaufwand; er unterscheidet sich vom konfigurierten
Gast-RAM und der Belegung im Gast. Die Werte aktualisieren sich alle fünf
Sekunden. Fehlende Messungen werden als unbekannt angezeigt; ausgeschaltete VMs
zeigen keine veraltete CPU-/RAM-Auslastung.

Ein Klick auf eine Kachel öffnet die Details in der nutzbaren Fensterfläche.
Eine zusätzliche dauerhaft sichtbare Maschinenliste entfällt. **Zurück** erhält
Suchbegriff und Filter und stellt den Fokus auf die ausgewählte VM wieder her.
Kachelraster und Details passen sich an die tatsächliche Fensterbreite an.

Die Detailansicht trennt Konsole, Hardware, Netzwerk und Sicherungen. Die
Browserkonsole verbindet sich direkt; sie öffnet keinen separaten Tab.
Gastagent, zusätzliche Festplatten und Netzwerkkarten werden im ausgeschalteten
Zustand eingerichtet. Bis zu acht verwaltete qcow2-Laufwerke und acht
Netzwerkkarten werden pro VM unterstützt. Das Trennen eines Laufwerks erhält die
Image-Datei.

Der optionale VirtIO-Gastagent-Kanal benötigt zusätzlich den Dienst
`qemu-guest-agent` im Gast. Wenn er antwortet, erscheinen Gast-IP-Adressen und
Herunterfahren über den Agent wird angeboten. Ein fehlender Agent verhindert
den normalen VM-Start und die reguläre ACPI-Abschaltung nicht.

Ein Klon kopiert alle Laufwerke in eigenständige qcow2-Dateien, übernimmt
UEFI-Variablen in eine eigene Datei und bekommt eine neue UUID sowie neue
MAC-Adressen. Exklusive USB-/Hostgeräte werden nicht übernommen. IP-Adresse und
Rechnername innerhalb des Gastes können trotzdem identisch sein und sollten vor
dem ersten gemeinsamen Start angepasst werden.

## Snapshot und Sicherung

Snapshots sind **kalte Laufwerks-Snapshots bei vollständig ausgeschalteter VM**.
Titan erfasst alle verwalteten Laufwerke sowie inaktive VM-Konfiguration und
UEFI-Variablen. RAM und laufende Gastprozesse werden nicht gespeichert. Es wird
kein laufendes Dateisystem eingefroren und kein Live-Snapshot als konsistent
ausgegeben.

Vor der Wiederherstellung werden interne Sicherheits-Snapshots erzeugt. Wenn ein
weiteres Laufwerk nicht wiederhergestellt werden kann, werden bereits geänderte
Laufwerke auf ihren vorherigen Zustand zurückgesetzt. Bei einer fehlgeschlagenen
Rücknahme bleiben Sicherheits-Snapshots für die manuelle Wiederherstellung
erhalten; die VM muss ausgeschaltet bleiben. Nach erfolgreicher Wiederherstellung
bleibt sie ebenfalls ausgeschaltet.

Die Laufwerksanzahl kann nicht verändert werden, solange Snapshots vorhanden
sind. Zuerst diese Snapshots entfernen oder einen unabhängigen Klon anlegen.
Snapshots liegen intern in denselben qcow2-Dateien und schützen nicht vor dem
Ausfall des NAS-Laufwerks. Die externe VM-Archivierung erfasst alle verwalteten
Laufwerke, VM-XML und UEFI-Variablen gemeinsam. Ältere Sicherungen mit einem
Laufwerk bleiben lesbar. Die Wiederherstellung schreibt neue Dateien in den
gewählten VM-Speicher, erzeugt eine neue UUID und übernimmt keine fremden
Hostpfade oder exklusiven USB-/PCI-Geräte aus dem Archiv.

## Verifikation

`tests/test_vm_extensions.py` arbeitet mit echten `qemu-img`- und
`qemu-io`-Dateien. Es prüft Mehrdisk-Snapshot/Wiederherstellung, unabhängiges
Klonen, Rücknahme eines Fehlers auf dem zweiten Laufwerk, UEFI-Variablen,
Metadatenprüfung und Verweigerung laufender Änderungen. Die übrigen VM- und
Pakettests prüfen libvirt- und Docker-Verwaltung sowie Protokollschutz. Ein
echtes Gastbetriebssystem, Browser-Tastatur/Maus und physische Geräte bleiben
Teil des manuellen Betatests.

Der GitHub-Workflow `App package runtime checks` startet jedes vollständige
Paket auf einem kurzlebigen Runner. Für Nextcloud/Office prüft
`scripts/smoke-office-gateway.py` zusätzlich Titans echten HTTP-Gateway mit
temporären Dokumenten: Der laufende Dokumentserver lädt ein Dokument über die
Docker-Bridge, konvertiert es über seine [Conversion API](https://api.onlyoffice.com/docs/docs-api/additional-api/conversion-api/request/),
und ein signierter Callback schreibt das Ergebnis mit Revisionsprüfung zurück.
Der Test prüft zudem den JavaScript-/Dokumentproxy, erhaltene Dateirechte,
abgewiesene Signaturen und die Rückkonvertierung eines ODT-Originals. Dieser
CI-Test ersetzt keinen manuellen Test der interaktiven Bearbeitung und
Zusammenarbeit im Browser.
