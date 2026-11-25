# Titan

Titan ist ein unabhängiges, nichtkommerzielles Homeserver-Betriebssystem auf Basis von umbrelOS. Es soll Dateien, Docker-Apps und virtuelle Maschinen unter einer Oberfläche vereinen und die KI-Suche, Transkription und Anbindung von KI-Agenten aus umbrelOS beibehalten. [Quellstand des ursprünglichen Projekts](https://github.com/getumbrel/umbrel/tree/27292d7044a912a8a845917b7698ad3dfdd2676d)

**Titan befindet sich in der Planung.** Ein installierbares Systemimage steht noch aus.

## Installation und Updates

Für Intel- und AMD-Rechner ist ein Image vorgesehen, das direkt auf eine interne SSD oder NVMe geschrieben wird. Bestehende Installationen sollen ihre Updates über einen eigenen Titan-Kanal erhalten. Das Projekt prüft neue Änderungen aus umbrelOS und signiert die für Titan freigegebenen Updates.

## Apps und Fernzugriff

Die offiziellen Umbrel-Apps für Android und macOS sollen sich mit Titan koppeln lassen und weiterhin über ihre bisherigen Kanäle aktualisiert werden. Die Kompatibilität auf beiden Plattformen ist ein Ziel für die erste Veröffentlichung.

Docker-Apps sollen sich auch unterwegs in einem Fenster des Titan-Desktops bedienen lassen. Dafür soll eine einzige HTTPS-Adresse genügen, etwa über einen Cloudflare-Tunnel. Die einzelnen Container brauchen bei diesem Zugriff keine eigene öffentliche Adresse.

## Virtuelle Maschinen

Für Home Assistant OS und andere Gastbetriebssysteme sind der Import vorhandener QCOW2-Abbilder und die gezielte Freigabe von NAS-Ordnern über virtiofs geplant.

**USB-Geräte.** Die umbrelOS-Basis unterstützt die Zuweisung einzelner USB-Geräte an eine VM, darunter Zigbee-Adapter und externe KI-Beschleuniger wie den **Coral USB Accelerator (Edge TPU)**. Die Coral-Laufzeit im Gast lädt die Firmware auf den Stick. Dabei meldet er sich mit einer anderen USB-Kennung neu an. Der geplante Titan-Hardwaretest prüft, ob der Stick beim Kennungswechsel und nach einem VM-Neustart zugeordnet bleibt und ein Modell im Gast auf der Edge TPU ausführt. [USB-Zuordnung im Ausgangsstand](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/packages/umbreld/source/modules/machines/usb-devices.ts#L7-L27) · [Coral-Dokumentation](https://coral.ai/docs/accelerator/get-started/)

**PCI-Geräte.** Für die direkte Zuweisung an eine VM sind drei Geräteklassen vorgesehen.

- **Integrierte Grafik (iGPU)** für Gäste, die die Grafikeinheit des Prozessors nutzen sollen.
- **Separate Grafikkarten von NVIDIA und AMD** für Grafik- oder Rechenaufgaben im Gast.
- **Integrierte KI-Beschleuniger (NPU)** für Inferenz im Gast, sofern die Plattform die NPU als isolierbares Gerät bereitstellt.

Bei einer direkten Zuweisung nutzt eine VM das Gerät exklusiv. Nutzt ein Medienserver auf dem NAS dieselbe GPU zum Transcodieren, muss er sie zuvor freigeben. Die Unterstützung hängt vom Gerätemodell, der Firmware, der IOMMU-Gruppierung und dem Treiber im Gast ab. Tests mit konkreten GPU- und NPU-Modellen stehen noch aus. [Linux-Dokumentation zu VFIO und Gerätegruppen](https://docs.kernel.org/driver-api/vfio.html)

## App-Katalog und Netzwerkzugriffe

Umbrel pflegt App-Pakete und Galeriebilder in eigenen Repositories. Die Store-Oberfläche bezieht außerdem Inhalte von `apps.umbrel.com`. Container-Images kommen aus den Registries der jeweiligen Anbieter. [App-Katalog](https://github.com/getumbrel/umbrel-apps) · [Bildergalerie](https://github.com/getumbrel/umbrel-apps-gallery) · [Store-Anbindung im Ausgangsstand](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/packages/ui/src/features/app-store/constants.ts)

Ziel ist der Betrieb von Titan-Server und Weboberfläche ohne automatische Anfragen an Umbrel. Der Ausgangsstand verwendet noch Umbrel-Dienste für Update-Prüfung, Signaturschlüssel, Kataloginhalte, Bilder und Karten. Das Projekt wird diese Verbindungen umstellen und die Netzwerkzugriffe von Server und Browser prüfen. Die offiziellen Umbrel-Apps, installierte Dienste und ausgewählte KI-Anbieter können eigene Verbindungen aufbauen.

## Herkunft, Lizenzen und Weitergabe

Für den von Umbrel übernommenen Betriebssystemcode gilt die **PolyForm Noncommercial License 1.0.0**. Titan gibt seine Bearbeitungen dieses Codes zu denselben Bedingungen weiter. Die Lizenz erlaubt die Nutzung, Änderung und Weitergabe für die darin beschriebenen nichtkommerziellen Zwecke. Bei jeder Weitergabe von erfasstem Code oder eines fertigen Images müssen die Empfänger den Lizenztext oder dessen URL sowie alle vom Lizenzgeber mitgelieferten Zeilen erhalten, die mit `Required Notice:` beginnen. Der Originaltext ist in diesem Repository enthalten. [Lizenztext](LICENSE.md) · [Umbrels Lizenz-FAQ](https://github.com/getumbrel/umbrel/wiki/License-FAQ)

Für kommerzielle Angebote wie vorinstallierte Server, kostenpflichtiges Hosting oder bezahlten Support für den Fork verweist Umbrel auf eine gesonderte Vereinbarung. Ansprechpartner für die kommerzielle Nutzung des Umbrel-Codes ist `partner@umbrel.com`. [Lizenzangaben des ursprünglichen Projekts](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/README.md#license)

Für Drittsoftware, Container-Images, App-Pakete, Schriften, Logos und Screenshots gelten die Rechte der jeweiligen Urheber und Anbieter. Ein Eintrag im öffentlichen App-Katalog allein erteilt keine pauschale Erlaubnis zur Spiegelung. Vor der Auslieferung eines Images oder Katalogs prüft Titan die tatsächlich enthaltenen Bestandteile, übernimmt vorgeschriebene Hinweise und erfüllt gegebenenfalls Pflichten zur Bereitstellung von Quellcode.

Umbrel und umbrelOS bezeichnen das ursprüngliche Projekt und dessen Software. Für Fragen und Fehlerberichte zu Titan ist das Titan-Projekt zuständig. [Titan auf GitHub](https://github.com/ra5on/Titan)

## Gewährleistung, Haftung und Datensicherung

Titan wird unentgeltlich im jeweils vorliegenden Zustand bereitgestellt. Das Projekt übernimmt keine Garantie für Fehlerfreiheit, Verfügbarkeit, Kompatibilität mit bestimmter Hardware oder die Wiederherstellbarkeit von Daten. Soweit gesetzlich zulässig, ist die Haftung der Projektverantwortlichen und Mitwirkenden für Schäden aus Installation, Updates oder Betrieb ausgeschlossen. Dazu zählen insbesondere Datenverlust, beschädigte Dateisysteme, fehlgeschlagene Wiederherstellungen und Betriebsausfälle.

Zwingende gesetzliche Ansprüche bleiben bestehen. Der Ausschluss gilt insbesondere nicht bei Vorsatz oder grober Fahrlässigkeit, bei schuldhafter Verletzung von Leben, Körper oder Gesundheit oder soweit das jeweils anwendbare Produkthaftungsrecht eine Haftung vorschreibt. [§ 276 BGB](https://www.gesetze-im-internet.de/bgb/__276.html) · [§ 309 Nr. 7 BGB](https://www.gesetze-im-internet.de/bgb/__309.html)

**Das Schreiben eines Systemimages überschreibt das gewählte Laufwerk einschließlich seiner Partitionen und Daten.** Prüfe das Ziellaufwerk anhand von Modell und Größe. Sichere wichtige Dateien, Konfigurationen und VM-Daten vor Installation oder Updates auf einem getrennten Datenträger und prüfe, ob sich die Sicherung wiederherstellen lässt.
