# Titan

**Dein NAS. Deine Dateien. Dein Desktop.**

Titan ist ein eigenständiges NAS-System auf Debian für AMD64. Die Weboberfläche verbindet einen persönlichen Desktop mit Dateimanager, Speicherverwaltung, Freigaben, Docker-Compose-Apps, virtuellen Maschinen und signierten Systemupdates.

**Version 0.5.9-alpha.1 · Alpha.** Zunächst in einer separaten VM und mit Testdaten verwenden.

[**Installationsimage herunterladen (.img.xz)**](https://github.com/ra5on/Titan/releases/download/v0.5.9-alpha.1/titan-0.5.9-alpha.1-amd64.img.xz) · [Release, signiertes Update und Prüfberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.9-alpha.1) · [Änderungen in 0.5.9](docs/RELEASE-0.5.9.md)

![Titan Desktop mit persönlichen Widgets](docs/images/titan-desktop.jpg)

*Die Screenshots zeigen die lokale Demo mit Beispieldaten. Die Demo führt keine Installationen oder Änderungen am echten NAS aus.*

## Installieren und öffnen

Für eine neue Test-VM: **UEFI/OVMF, Secure Boot aus, 8 GiB RAM, mindestens 2 CPUs und 64 GiB virtuelle Festplatte**. Das entpackte Rohimage ist 48 GiB groß. Die virtuelle Platte vor dem ersten Start auf die gewünschte Kapazität erweitern; Titan vergrößert seinen Datenbereich beim Start. Für VMs innerhalb von Titan muss der Host verschachtelte Virtualisierung erlauben.

1. Die `.img.xz` aus dem Release herunterladen und die mitgelieferte Prüfsumme prüfen.
2. Entpacken und das `.img` als Systemplatte importieren oder auf den vorgesehenen Datenträger schreiben. **Das Schreiben überschreibt das Ziel.**
3. Titan starten und im eigenen Netz `https://<NAS-IP>` öffnen.
4. Den Administrator selbst einrichten. Es gibt kein vorgegebenes Kennwort.

Neuinstallationen verwenden **HTTPS auf Port 443**; HTTP auf Port 80 leitet dorthin weiter. Das lokale Zertifikat ist selbstsigniert. Bestehende Installationen behalten bei einem Update ihre bisherigen Webports. Unter **Systemsteuerung → Allgemein → Webzugriff** können Protokoll und Ports geändert werden. Die neue Adresse muss innerhalb von **120 Sekunden** bestätigt werden; sonst stellt Titan die bisherige Einstellung wieder her.

[Installationsanleitung](docs/INSTALL.md) · [Image, Partitionen und Proxmox](docs/TITAN-IMAGE.md)

## Persönlicher Desktop

Jedes Konto erhält eigene Verknüpfungen, Widgetpositionen und Darstellungsoptionen. Fenster lassen sich öffnen, verschieben, verkleinern und minimieren. Die Seitenleisten in Dateimanager, VM-Verwaltung, Docker, Speicher und Systemsteuerung können am Trenner breiter oder schmaler gezogen werden.

Im Kontomenü stehen **Hell, Dunkel und Automatisch** sowie ein globaler Transparenzregler für den eigenen Desktop bereit. Automatisch folgt dem Betriebssystem. Bereits geöffnete Titan-Fenster und Konsolen wechseln mit. Für einen Klick auf freien Desktop lässt sich auswählen, ob die Fenster minimiert werden oder nichts geschieht.

Über **Widgets hinzufügen** öffnet sich eine Galerie für Uhr, CPU, RAM, Systemstatus, Meldungen und Aktivität. Die Karten lassen sich einzeln platzieren. Regelmäßige Messwertupdates ändern die Werte innerhalb der bestehenden Karten; die Widgets werden dabei nicht neu aufgebaut. Systemmesswerte bleiben Administratoren vorbehalten.

Rechtsklick, längeres Drücken oder **Umschalt+F10** öffnen passende Schnellaktionen. Auf Desktop und im Hauptmenü können Verknüpfungen hinzugefügt oder entfernt und Appaktionen geöffnet werden. Innerhalb von Anwendungen greifen die Menüs auf die jeweiligen vorhandenen Aktionen zu. Das Entfernen einer Desktop-Verknüpfung deinstalliert keine App. Bestätigungen zeigen die positive Aktion links und **Nein/Abbrechen rechts**.

![Widget-Galerie zum Hinzufügen und Entfernen einzelner Karten](docs/images/titan-widgets.jpg)

## Dateien verwalten

![Dateimanager mit kompakter Werkzeugleiste und einblendbaren Details](docs/images/titan-files.jpg)

Der Dateimanager bietet Listen- und Kachelansicht, anpassbare Seitenleiste, Navigation, Suche, Vorschau und einen bei Bedarf einblendbaren Detailbereich. Dateien und Ordner lassen sich kopieren, verschieben, umbenennen und über den Papierkorb entfernen. UTF-8-Dateien bis 1 MiB können direkt bearbeitet werden; unterstützte Bilder, Medien und Textdateien erhalten eine Vorschau.

**Mehrere Dateien können per Drag-and-drop in den geöffneten beschreibbaren Ordner geladen werden.** Der Upload zeigt Dateiname, Fortschritt und Position in der Warteschlange. „Abbrechen“ stoppt die Übertragung und die restliche Warteschlange. Bereits vollständig übertragene Dateien bleiben erhalten. Ordnerdrops werden mit einer verständlichen Meldung abgewiesen.

Neue Uploads landen zunächst in einem privaten Zwischenbereich. Erst nach vollständiger Übertragung wird die fertige Datei atomar in den Zielordner übernommen. Gleichnamige vorhandene Dateien werden nicht überschrieben. Ein abgebrochener Upload blockiert nachträglich eintreffende Teilstücke; nach einem Netzabbruch verbliebene Zwischenstände werden nach Ablauf der Aufbewahrung beim nächsten Upload bereinigt.

Datei- und Ordnermenüs bieten Aktionen passend zur Auswahl und den Zugriffsrechten. Im freien Dateibereich sind unter anderem Hochladen, Neuer Ordner, Neue Datei, Einfügen und Aktualisieren erreichbar. Administratoren können einen zeitlich begrenzten **Root-Modus** für Systemdateien aktivieren; dafür werden Passwort und gegebenenfalls der zweite Faktor erneut geprüft.

## Eigene Compose-Apps

![Titan Apps mit eigenen Docker-Compose-Rezepten](docs/images/titan-apps.jpg)

Titan bietet lokal gepflegte Compose-Rezepte an. **BigBear und externe Store-Downloads sind entfernt.** Vorhandene, früher installierte Anwendungen behalten ihre gespeicherte Vorlage, Konfiguration und Daten und bleiben verwaltbar.

Die Einrichtung zeigt echte Schritte wie Docker prüfen, Dateien vorbereiten, Images laden, Container erstellen, starten und Bereitschaft prüfen. Der Verlauf bleibt nach einem Fensterwechsel erhalten. Fehler und unterbrochene Schritte bleiben sichtbar und lassen sich fortsetzen. Ein gestarteter Container allein wird nicht als erfolgreiche Einrichtung ausgegeben.

| App | Enthalten und Einrichtung |
| --- | --- |
| **Cloudflare Tunnel** | Offizieller Connector, Tunnel-Token einfügen, kein zusätzliches Verwaltungspasswort. Titan richtet das lokale Ziel ein und prüft Verbindung und optional die öffentliche HTTPS-Adresse getrennt. |
| **Immich** | Immich-Server, Machine Learning, PostgreSQL und Valkey. Speicherziel auswählen und den vollständigen Verbund installieren; das erste Immich-Konto anschließend in dessen Weboberfläche einrichten. |
| **AdGuard Home** | DNS-Filter mit eigener Webeinrichtung. DNS- und Webports werden auf Verfügbarkeit geprüft; Geräte beziehungsweise Router müssen danach AdGuard als DNS-Server verwenden. |
| **Tailscale** | Eigener Node mit Auth-Key und optionalem Subnet-Routing für ausdrücklich angegebene private Netze. Den Node und angekündigte Routen gegebenenfalls im Tailscale-Konto freigeben. |

Immich benötigt zusätzlichen Arbeitsspeicher und Platz für Originale, Vorschaubilder und Datenbank. Die Rezeptlimits des gesamten Verbunds betragen **6,25 GiB**, davon 2 GiB für PostgreSQL. Mit NAS- und Installationsreserve prüft Titan konservativ 7,75 GiB verfügbaren RAM; ein bereits ausgelasteter 8-GiB-Host kann deshalb abgewiesen werden. Für Immich zusammen mit weiteren Apps sind 16 GiB oder mehr sinnvoll.

Tailscale läuft im **Userspace-Modus** ohne privilegierten Container, Hostnetz oder Änderungen an Host-Routing und Firewall. Subnet-Routing unterstützt TCP und UDP; Ping ist eingeschränkt, andere IP-Protokolle werden nicht weitergeleitet. Das Zielnetz muss vom Container aus erreichbar sein. Eine zusätzlich eingetragene NAS-IP wird als ausdrückliche einzelne Hostroute angekündigt; der Zugriff erfolgt über diese private IP. Die in Tailscale angebotenen Routen benötigen eine Freigabe im Tailscale-Konto; Installation allein bestätigt keinen Zugriff von einem externen Gerät.

Bei Cloudflare muss der öffentliche Hostname im Cloudflare-Konto dem angezeigten lokalen HTTP-Ziel zugeordnet werden. Der Tunnel-Token kann DNS und öffentliche Routen nicht anlegen. Geschützte Tokens und Auth-Keys werden nicht erneut in Formularen angezeigt.

[Apps und Installation](docs/APP-STORES.md) · [Cloudflare und Tailscale](docs/REMOTE-ACCESS.md)

## Docker verwalten

Die Docker-Ansicht zeigt Container, Compose-Gruppen, Images, Netzwerke und Volumes. CPU- und RAM-Messwerte werden getrennt vom Verbindungsstatus angezeigt. Die Übersicht nutzt kompakte Kennzahlen; Details öffnen sich nur bei Bedarf. Listen und Detailbereiche behalten ihre Scrollposition beim Wechsel.

Starten, Stoppen, Neustarten und weitere Aktionen verwenden den tatsächlichen Docker-Zustand. Fehler beim Laden oder bei Messwerten werden angezeigt. Spät eintreffende Logantworten können einen bereits geschlossenen oder gewechselten Detailbereich nicht wieder öffnen.

## Virtuelle Maschinen und Konsolen

![VM-Kacheln mit frei geschriebenem Anzeigenamen](docs/images/titan-vm-tiles.jpg)

![VM-Verwaltung mit Sicherungen und Wiederherstellung als neue VM](docs/images/titan-vms.jpg)

VM-Kacheln zeigen den frei wählbaren Namen sowie gemessene CPU- und RAM-Werte. **Großbuchstaben, Leerzeichen und Umlaute** sind in Anzeigenamen möglich; interne Libvirt- und Dateinamen bleiben davon getrennt. Ein Klick öffnet Konfiguration, Datenträger, Netzwerke, Konsole und Sicherungen. Regelmäßige Aktualisierungen erhalten die laufende Ansicht und eine bereits verbundene Konsole.

**Snapshots und Sicherungen** sind direkt in den VM-Details erreichbar. Bei laufenden VMs fordert Titan zunächst ein ausdrücklich bestätigtes, geordnetes Herunterfahren an. Snapshots sichern den Datenträgerzustand, keinen laufenden RAM-Zustand. Ein vollständiger Snapshot kann **als neue, ausgeschaltete VM** wiederhergestellt werden: mit eigener UUID, MAC-Adresse und unabhängigen Datenträgern. Die ursprüngliche VM bleibt erhalten. Unvollständige Snapshots werden nicht zur Wiederherstellung angeboten.

Das **Titan-Terminal** und die **VM-Konsole** besitzen kompakte Werkzeugleisten, passende Dunkel-/Hellflächen und Schnellaktionen. Das Terminal bietet Kopieren, Einfügen, Alles markieren, Bildschirm leeren und Befehl abbrechen; die VM-Konsole zusätzlich Gast-Tastenkombinationen, Skalierung, Vollbild und eine Textzwischenablage. Gemeinsames Kopieren und Einfügen mit dem Gast benötigt Unterstützung im Gastsystem. Browser können den direkten Zwischenablagezugriff beschränken; dafür steht ein Textdialog bereit. Terminal und einzelne VM-Konsolen können als Desktop-Verknüpfung abgelegt werden.

[VMs, Snapshots und Grenzen](docs/PACKAGES-AND-VMS.md) · [App-Sicherungen](docs/BACKUPS.md)

![Titan-Terminal mit Schnellaktionen](docs/images/titan-terminal.jpg)

## Anmeldung, Verwaltung und Updates

![Titan Anmeldung](docs/images/titan-login.jpg)

Die Anmeldung unterstützt Passwort, optionalen zweiten Faktor und Anmeldeschutz. Das neue kompakte Layout passt auf große und kleine Bildschirme. Konten, Gruppen und Freigaberechte bleiben zentral verwaltbar.

**Bei jeder erfolgreichen Administrator-Anmeldung prüft Titan im Hintergrund auf Updates.** Ein verfügbares Update erscheint als Benachrichtigung und markiert die Glocke; diese öffnet direkt den Updatebereich. Normale Benutzer und eingebettete Appfenster starten diese Prüfung nicht. Unter **Updates & Rollback** können Administratoren nach Updates suchen, das signierte RAUC-Paket installieren und anschließend den Neustart bestätigen.

Titan verwendet zwei Systembereiche. Ein Update schreibt den inaktiven Bereich; ein bestätigter vorheriger Systemstand kann wieder ausgewählt werden. **Ein System-Rollback setzt gemeinsam genutzte App-Daten und Datenbanken nicht zurück.** Unabhängige Sicherungen und eine praktisch geprüfte Wiederherstellung bleiben erforderlich. Eine App-Wiederherstellung benötigt ein gestopptes, weiterhin passendes installiertes Paket und lässt die App anschließend gestoppt.

Weitere Bereiche umfassen Ext4/XFS/ZFS-Speicher, Laufwerksstatus, Dienste, Freigaben und Systemressourcen. Destruktive Aktionen und Änderungen an Netzwerk oder Systemschutz bleiben ausdrücklich bestätigungspflichtig.

## Entwicklung und Prüfung

```sh
python3 -m pip install PyYAML
python3 -m unittest discover -s tests
python3 -m titan.server --demo --host 127.0.0.1 --port 5089
```

Die Demo ist eine Vorschau mit simulierten Hostfunktionen. Sie ersetzt keine Prüfung auf echter Hardware oder mit echten Cloudflare-/Tailscale-Konten. Der Release-Workflow baut das Installationsimage und das signierte Update und veröffentlicht sie erst nach Quellcode-, App-, Boot-, Laufzeit- und Wiederherstellungsprüfungen. Die Berichte werden dem Release beigefügt.

Für dieses Alpha-Installationsimage verwendet die A/B-Prüfung eine private, als Altstand markierte Kopie des aktuellen Builds. Sie prüft Systemwechsel, Datenerhalt, Rollback und Fehlerwiederherstellung. Ein Upgrade von einem tatsächlich älteren veröffentlichten Titan-Image ist damit nicht vollständig nachgewiesen und muss separat geprüft werden.

[Entwicklung und Testgrenzen](docs/DEVELOPMENT.md) · [Bedienung und Layout](docs/UI-DESIGN.md) · [Updates](docs/UPDATES.md)

TitanOS dient ausschließlich als visuelle Orientierung. Titan verwendet eigenen Oberflächencode und eigene Gestaltung; Code und Assets von TitanOS wurden nicht übernommen.

## Lizenz

Der eigene Titan-Code ist für nichtkommerzielle Nutzung, Änderungen und kostenlose Weitergabe freigegeben. Kommerzielle Rechte können vom Rechteinhaber gesondert erteilt werden. Drittkomponenten behalten ihre jeweiligen Lizenzen. [Lizenz](LICENSE)
