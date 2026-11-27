# Titan

Titan ist ein nichtkommerzielles Homeserver-Betriebssystem für Intel- und AMD-Rechner. Dateien, Fotos, Docker-Apps und virtuelle Maschinen lassen sich im Browser verwalten. Die Basis für System und KI-Funktionen ist der umbrelOS-Quellstand `2.1.0-beta.2`. Das Titan-Projekt prüft spätere Änderungen von Umbrel und veröffentlicht eigene, signierte Systemupdates. [Ausgangsstand bei Umbrel](https://github.com/getumbrel/umbrel/tree/27292d7044a912a8a845917b7698ad3dfdd2676d)

[Installation auf SSD oder NVMe](#installation-auf-ssd-oder-nvme) · [Systemansichten](#systemansichten)

![Titan-Desktop nach dem ersten Login](docs/bilder/desktop.png)

## Systemansichten

Die Aufnahmen stammen aus dem veröffentlichten Titan-Image. Ein Klick auf ein Bild öffnet die große Ansicht.

| Dateiverwaltung | Dateifreigabe im Heimnetz |
| --- | --- |
| [![Persönlicher Ordner mit Dokumenten, Downloads, Fotos und Videos](docs/bilder/dateien.png)](docs/bilder/dateien.png) | [![Auswahl zwischen dem gesamten persönlichen Ordner und einzelnen freigegebenen Ordnern](docs/bilder/freigabe.png)](docs/bilder/freigabe.png) |

| Virtuelle Maschinen | Live-Auslastung |
| --- | --- |
| [![Betriebssystemauswahl beim Anlegen einer virtuellen Maschine](docs/bilder/maschinen.png)](docs/bilder/maschinen.png) | [![Live-Ansicht mit CPU-Verlauf, Arbeitsspeicher und belegtem Speicherplatz](docs/bilder/auslastung.png)](docs/bilder/auslastung.png) |

| Systemeinstellungen | Speicherverwaltung |
| --- | --- |
| [![Einstellungen für Benutzer, Desktop, Sprache und Speicher](docs/bilder/einstellungen.png)](docs/bilder/einstellungen.png) | [![Zustand, Belegung und freier Speicher des Systemlaufwerks](docs/bilder/speicher.png)](docs/bilder/speicher.png) |

## Installation auf SSD oder NVMe

Für die Erstinstallation brauchst du das komprimierte AMD64-Image. Die Update-Dateien lädt Titan bei späteren Systemaktualisierungen selbst. [SSD-Image herunterladen](https://github.com/ra5on/Titan/releases/latest/download/titan-amd64.img.xz) · [Signiertes Manifest und Versionshinweise](https://github.com/ra5on/Titan/releases/latest)

1. Sichere vorhandene Daten. **Das Schreiben des Images überschreibt die Partitionstabelle und den Inhalt des gewählten Laufwerks.**
2. Lade für einen x86-64-Rechner mit UEFI die Datei `titan-amd64.img.xz` und das zugehörige `manifest.txt` aus derselben Veröffentlichung. Vergleiche den SHA-256-Wert der komprimierten Datei mit dem Eintrag im Manifest.
3. Schließe die Ziel-SSD an einen anderen Rechner an. Entpacke das Image mit einem XZ-fähigen Werkzeug und schreibe die entstandene `.img` mit einem Programm für Datenträgerabbilder auf die **gesamte SSD**. Prüfe Modell und Größe des Ziels vor dem Schreiben.
4. Baue die SSD in den Server ein und starte den Rechner im UEFI-Modus. Secure Boot muss für dieses Image ausgeschaltet sein. Verbinde den Server per Ethernet mit dem Heimnetz. Öffne die vom Router zugewiesene IP-Adresse im Browser und lege das Eigentümerkonto an.

Für spätere Updates genügt die Systemaktualisierung in den Einstellungen. Titan prüft die Freigabesignatur und den Hash des für den Rechner vorgesehenen Bundles. Zusammengehörige Teile einer größeren Aktualisierung lädt Titan selbst. Erstelle vor einem Update eine aktuelle Sicherung wichtiger Dateien und VMs. [Veröffentlichungen](https://github.com/ra5on/Titan/releases)

![Deutschsprachige Ersteinrichtung beim ersten Start von der SSD](docs/bilder/einrichtung.png)

## Apps und Fernzugriff

Die offiziellen Umbrel-Clients für Android und macOS behalten ihre bisherigen Updatewege. Titan verwendet die Anmelde- und Kopplungsschnittstellen der gemeinsamen Basis. Die Download-Schaltflächen für diese Clients öffnen auf Wunsch die offiziellen Bezugsquellen. Eine vollständige Kopplungsprüfung mit den veröffentlichten Clients auf beiden Plattformen steht aus.

Der Titan App-Katalog enthält mitgelieferte Apps und lädt die offiziellen Umbrel-App-Pakete beim ersten Start des Katalogdienstes. App-Icons und Screenshots kommen von der Umbrel-Bildergalerie. Installierte Apps beziehen ihre Container-Images aus den jeweiligen Registrys. Weitere kompatible Kataloge lassen sich als Community-Stores hinzufügen. [Umbrel-App-Pakete](https://github.com/getumbrel/umbrel-apps) · [Bildergalerie](https://github.com/getumbrel/umbrel-apps-gallery)

Als Eigentümer kannst du die Weboberfläche einer laufenden Docker-App im Titan-Desktop öffnen. Dafür startet auf dem Server ein temporärer Browser mit Zugang zu dieser App. Beim ersten Öffnen lädt Titan das Browser-Image aus seiner GitHub-Veröffentlichung und prüft die Prüfsumme. Die Sitzung läuft über dieselbe Webadresse wie der Desktop. Ein Reverse-Proxy oder Cloudflare-Tunnel muss HTTP und WebSocket-Verbindungen an Titan weiterleiten. Für diese Ansicht genügt ein einziges öffentliches Ziel. Mitgliedskonten und reine Tor-Apps verwenden den herkömmlichen App-Aufruf. Der eingeschränkte Browser eignet sich für webbasierte Bedienoberflächen. Eine Sitzung mit einem öffentlichen Cloudflare-Tunnel wurde bisher nicht separat getestet.

## Virtuelle Maschinen

| Funktion | Verwendung und Voraussetzungen |
| --- | --- |
| Vorhandenes QCOW2-Abbild | Lege die eigenständige `.qcow2`-Datei in Titan ab und wähle sie beim Anlegen der VM aus. Ein komprimiertes Home-Assistant-OS-Abbild für KVM/OVA muss vorher entpackt werden. Der Import arbeitet mit einer Kopie. Images mit externen Daten- oder Basisdateien werden abgewiesen. |
| Autostart | Aktiviere pro VM die Einstellung **Autostart**, damit Titan sie beim Systemstart startet. |
| Ordner teilen | Wähle einen Ordner aus deinem persönlichen Home-Verzeichnis und vergib einen Freigabenamen. Der Gast braucht einen virtiofs-Treiber. In einem Linux-Gast lässt sich beispielsweise die Freigabe `medien` auf ein vorhandenes Verzeichnis mit `mount -t virtiofs medien /mnt/medien` einhängen. Freigaben sind standardmäßig schreibgeschützt. |
| USB-Geräte | Weise einen USB-Port der VM zu. Das ist unter anderem für Zigbee-Adapter und den Coral USB Accelerator vorgesehen. Der Coral-Stick wechselt beim Laden seiner Firmware die USB-Kennung. Die Zuordnung orientiert sich am physischen Anschluss. |
| iGPU, NVIDIA-/AMD-GPU, NPU | Der Host braucht KVM und eine aktive IOMMU. Das Gerät muss als unterstützte PCI-Funktion sichtbar und seine vollständige, geeignete IOMMU-Gruppe für `vfio-pci` vorbereitet sein. Ein direkt zugewiesenes Gerät steht dem Gast exklusiv zur Verfügung. Änderungen an der PCI-Zuordnung werden beim nächsten VM-Start wirksam. |

Home Assistant OS 18.4 wurde aus dem offiziellen QCOW2-Abbild importiert, sektorweise verglichen und mit QEMU und UEFI bis zum Login gestartet. Ein separater Linux-Gast las und schrieb Dateien auf einer virtiofs-Testfreigabe. Bei einer hostseitig schreibgeschützten Freigabe konnte derselbe Gast lesen und erhielt beim Schreibversuch einen Dateisystemfehler. Durchreichung und Treiberbetrieb eines konkreten Coral-Sticks, einer Grafikkarte oder einer integrierten NPU wurden bislang nicht an physischer Hardware bestätigt. [Home Assistant OS](https://github.com/home-assistant/operating-system/releases/tag/18.4) · [VFIO und IOMMU-Gruppen](https://docs.kernel.org/driver-api/vfio.html) · [Coral USB Accelerator](https://coral.ai/docs/accelerator/get-started/)

## KI und Netzwerkverbindungen

Der Start des veröffentlichten Images von Titan 0.1, die Einrichtung des Eigentümerkontos und der Aufruf des Desktops wurden mit UEFI und einer virtuellen NVMe geprüft. Im Browser- und Netzwerkmitschnitt dieses Ablaufs gab es keine Anfragen an öffentliche Umbrel-Dienste. Für die Geräteerkennung der offiziellen Clients verwendet Titan im lokalen Netz weiterhin mDNS-Namen wie `umbrel.local`. [Boot- und Browsertest](https://github.com/ra5on/Titan/actions/runs/45718480622)

Suche, Texterkennung und Transkription verwenden lokale Modelle. Bei Bedarf bezieht Titan Modelldateien von ihren Originalquellen und prüft ihre SHA-256-Werte. Für die mit der Gesichtserkennung verwendeten InsightFace-Gewichte beschränkt der Anbieter die öffentliche Freigabe auf nichtkommerzielle Forschung. Diese Gewichte müssen mit den passenden Nutzungsrechten separat bereitgestellt werden. Für externe KI-Agenten steht die MCP-Anbindung der Basis zur Verfügung. [Modellquellen und Prüfsummen](packages/umbreld/source/modules/files/models.json) · [Nutzungsbedingungen von InsightFace](https://github.com/deepinsight/insightface#license)

| Funktion | Netzwerkziel |
| --- | --- |
| Systemupdates und Schlüssel | Titan-Repository und Titan-Releases auf GitHub. Der Updateabruf übermittelt weder Hardwarekennung noch installierte Version an den Updatekanal. |
| App-Katalog und Fotos | Titan synchronisiert den offiziellen Katalog über GitHub und lädt App-Bilder aus der Umbrel-Bildergalerie. Eine zusätzliche Foto-Kartenquelle kann der Betreiber über `TITAN_MAP_URL` einrichten. |
| App-Installation und Modelle | Die konfigurierte Container-Registry beziehungsweise die in der Modelldatei genannten Quellen, darunter Hugging Face, ModelScope und GitHub. |
| Cloud-Konten | Verbindungen gehen zum ausgewählten Dienst. Anbindungen über OAuth erfordern einen eigenen Callback-Dienst und eigene Client-Zugangsdaten. |
| Native Clients, Community-Stores, installierte Apps und Tunnel | Die jeweiligen Anbieter und die eigene Konfiguration bestimmen deren Netzwerkziele. Ein öffentlicher Tunnel stellt eine Verbindung zum gewählten Tunnelanbieter her. |

## Image selbst bauen

Der AMD64-Build läuft unter Linux mit Node.js 26, Docker Engine und Buildx. Führe die folgenden Befehle im Stammverzeichnis des Repositorys aus. [Build-Konfiguration auf GitHub](.github/workflows/ci.yml)

```sh
npm --prefix packages/umbreld ci --ignore-scripts
npm --prefix packages/ui ci
npm --prefix packages/ui run build
packages/os/build-titan.sh
```

Die fertigen Dateien liegen unter `packages/os/build/titan-<Version>/`. Die Projektverantwortlichen prüfen Änderungen am festgelegten umbrelOS-Ausgangsstand, testen das gebaute Image und signieren Manifest und Versionshinweise mit einem Titan-Freigabeschlüssel. Der Updater und der erste Download des App-Browsers greifen ohne GitHub-Anmeldung zu. Wird das Repository privat, müssen Feed, Schlüssel und Release-Dateien vorher an eine öffentlich erreichbare Adresse umziehen. Der Adresswechsel muss die installierten Geräte über den bisherigen Updatekanal erreichen. [Signierwerkzeug](scripts/titan-sign-release)

## Herkunft, Lizenzen und Weitergabe

Für den von Umbrel übernommenen Betriebssystemcode gilt die **PolyForm Noncommercial License 1.0.0**. Titan gibt seine Bearbeitungen dieses Codes zu denselben Bedingungen weiter. Die Lizenz erlaubt die Nutzung, Änderung und Weitergabe für die darin beschriebenen nichtkommerziellen Zwecke. Bei jeder Weitergabe von erfasstem Code oder eines fertigen Images müssen die Empfänger den Lizenztext oder dessen URL sowie alle vom Lizenzgeber mitgelieferten Zeilen erhalten, die mit `Required Notice:` beginnen. Der Originaltext ist im Repository enthalten und lässt sich während der Ersteinrichtung direkt auf dem Server öffnen. [Lizenztext](LICENSE.md) · [Umbrels Lizenz-FAQ](https://github.com/getumbrel/umbrel/wiki/License-FAQ)

Für kommerzielle Angebote wie vorinstallierte Server, kostenpflichtiges Hosting oder bezahlten Support für den Fork verweist Umbrel auf eine gesonderte Vereinbarung. Ansprechpartner für die kommerzielle Nutzung des Umbrel-Codes ist `partner@umbrel.com`. [Lizenzangaben des ursprünglichen Projekts](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/README.md#license)

Für Drittsoftware, Container-Images, App-Pakete, Schriften, Logos und Screenshots gelten die Rechte der jeweiligen Urheber und Anbieter. Ein Eintrag im öffentlichen App-Katalog allein erteilt keine pauschale Erlaubnis zur Spiegelung. Die Datei `titan-paketquellen.tsv` im Release führt die installierten Debian- und Herstellerpakete mit ihren Versionen und Bezugsquellen für System und App-Browser auf. Zur modifizierten Avahi-Version gehören zusätzlich die Patches im Repository. Weitere Komponenten, Bezugsquellen und Buildschritte dokumentiert der Build der gemeinsamen Basis. Die Paketlizenzen liegen im jeweiligen Dateisystem unter `/usr/share/doc`. [Avahi-Patches](packages/os/avahi-patches) · [System-Build](packages/os/umbrelos.Dockerfile) · [App-Browser-Build](packages/os/viewer/Dockerfile)

Umbrel und umbrelOS bezeichnen das ursprüngliche Projekt und dessen Software. Für Fragen und Fehlerberichte zu Titan ist das Titan-Projekt zuständig. [Titan auf GitHub](https://github.com/ra5on/Titan)

## Gewährleistung, Haftung und Datensicherung

Titan wird unentgeltlich im jeweils vorliegenden Zustand bereitgestellt. Das Projekt übernimmt keine Garantie für Fehlerfreiheit, Verfügbarkeit, Kompatibilität mit bestimmter Hardware oder die Wiederherstellbarkeit von Daten. Soweit gesetzlich zulässig, ist die Haftung der Projektverantwortlichen und Mitwirkenden für Schäden aus Installation, Updates oder Betrieb ausgeschlossen. Dazu zählen insbesondere Datenverlust, beschädigte Dateisysteme, fehlgeschlagene Wiederherstellungen und Betriebsausfälle.

Zwingende gesetzliche Ansprüche bleiben bestehen. Der Ausschluss gilt insbesondere nicht bei Vorsatz oder grober Fahrlässigkeit, bei schuldhafter Verletzung von Leben, Körper oder Gesundheit oder soweit das jeweils anwendbare Produkthaftungsrecht eine Haftung vorschreibt. [§ 276 BGB](https://www.gesetze-im-internet.de/bgb/__276.html) · [§ 309 Nr. 7 BGB](https://www.gesetze-im-internet.de/bgb/__309.html)

**Das Schreiben eines Systemimages überschreibt das gewählte Laufwerk einschließlich seiner Partitionen und Daten.** Prüfe das Ziellaufwerk anhand von Modell und Größe. Sichere wichtige Dateien, Konfigurationen und VM-Daten vor Installation oder Updates auf einem getrennten Datenträger und prüfe, ob sich die Sicherung wiederherstellen lässt.
