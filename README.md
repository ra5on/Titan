# Titan

Titan ist ein unabhängiger, nichtkommerzieller Fork von umbrelOS für den eigenen Homeserver. Die Grundlage ist umbrelOS 2.1 mit seiner KI-Suche, automatischen Transkription und Anbindung für KI-Agenten. Titan wird von ra5on gepflegt. Umbrel entwickelt das ursprüngliche Betriebssystem. TitanOS ist ein eigenständiges Projekt, aus dem einzelne Funktionen in Titan einfließen sollen. [Umbrel-Quellstand](https://github.com/getumbrel/umbrel/tree/27292d7044a912a8a845917b7698ad3dfdd2676d) · [TitanOS](https://github.com/ra5on/TitanOS)

## Stand und Versionen

**Titan 0.1 ist in Planung.** Ein installierbares Titan-Image und ein getesteter Update-Kanal stehen noch aus. Die erste Version ist für Intel- und AMD-Rechner mit interner SSD oder NVMe vorgesehen. Die Titan-Versionen zählen von `0.1` bis `0.9`, danach folgen `1.0`, `1.1` und so weiter. Diese Nummer ist zugleich der Git-Tag.

Für die Erstinstallation ist ein direkt auf die SSD schreibbares Image geplant. Bestehende Installationen sollen signierte Titan-Updates beziehen. Neue Umbrel-Veröffentlichungen werden zunächst im Projekt geprüft. Welche Änderungen auf den Homeserver kommen, entscheidet die Freigabe durch Titan.

## Geplanter Funktionsumfang

- **Offizielle Umbrel-Apps.** Die Android- und Mac-App sollen sich mit Titan koppeln können und ihre Updates weiterhin auf dem üblichen Weg erhalten. Die Kompatibilität wird vor der ersten Freigabe auf beiden Plattformen getestet.
- **Docker-Apps über eine Adresse öffnen.** Nach dem Vorbild der TitanOS-Fernansicht soll eine App innerhalb des Titan-Desktops bedienbar sein, auch über einen einzelnen Cloudflare-Tunnel.
- **Virtuelle Maschinen.** Vorgesehen sind der Import eines Home-Assistant-OS-Abbilds im QCOW2-Format und die Freigabe ausgewählter NAS-Ordner an einzelne Gäste über virtiofs. Die USB-Durchreichung für Geräte wie Zigbee-Adapter bringt die Umbrel-Basis bereits mit. [Umbrels Versionshinweise](https://github.com/getumbrel/umbrel/releases/tag/2.1.0-beta.1)

## App Store und Verbindungen zu Umbrel

Der Store, den man im Desktop sieht, besteht aus mehreren Teilen. Die Oberfläche gehört zum Betriebssystem. Umbrel pflegt die Installationspakete in einem eigenen Git-Repository und die Icons und Screenshots in einer separaten Galerie. Hinzu kommen Inhalte von `apps.umbrel.com` und die Container-Images der jeweiligen App-Anbieter. [App-Katalog](https://github.com/getumbrel/umbrel-apps) · [Bildergalerie](https://github.com/getumbrel/umbrel-apps-gallery) · [Store-Anbindung im Ausgangsstand](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/packages/ui/src/features/app-store/constants.ts)

**Ziel ist, dass der Titan-Server und seine Weboberfläche im Normalbetrieb keine Anfragen an Umbrel senden.** Dafür müssen unter anderem Update-Prüfung, Signaturschlüssel, Katalog, Bilder und Kartenquellen umgestellt werden. Der Ausgangsstand enthält diese Verbindungen noch. Vor einer entsprechenden Zusage prüft das Projekt die Netzwerkzugriffe von NAS und Browser. Die offiziellen Umbrel-Apps, vom Nutzer installierte Dienste und selbst gewählte KI-Anbieter haben eigene Netzwerkverbindungen.

## Herkunft, Lizenzen und Weitergabe

Für den von Umbrel übernommenen Betriebssystemcode gilt die **PolyForm Noncommercial License 1.0.0**. Titan gibt seine Bearbeitungen dieses Codes zu denselben Bedingungen weiter. Die Lizenz erlaubt die Nutzung, Änderung und Weitergabe für die darin beschriebenen nichtkommerziellen Zwecke. Bei jeder Weitergabe von erfasstem Code oder eines fertigen Images müssen die Empfänger den Lizenztext oder dessen URL sowie alle vom Lizenzgeber mitgelieferten Zeilen erhalten, die mit `Required Notice:` beginnen. Der Originaltext ist in diesem Repository enthalten. [Lizenztext](LICENSE.md) · [Umbrels Lizenz-FAQ](https://github.com/getumbrel/umbrel/wiki/License-FAQ)

Für kommerzielle Angebote wie vorinstallierte Server, kostenpflichtiges Hosting oder bezahlten Support für den Fork verweist Umbrel auf eine gesonderte Vereinbarung. Ansprechpartner für die kommerzielle Nutzung des Umbrel-Codes ist `partner@umbrel.com`. [Lizenzangaben des ursprünglichen Projekts](https://github.com/getumbrel/umbrel/blob/27292d7044a912a8a845917b7698ad3dfdd2676d/README.md#license)

Für Drittsoftware, Container-Images, App-Pakete, Schriften, Logos und Screenshots gelten die Rechte der jeweiligen Urheber und Anbieter. Ein Eintrag im öffentlichen App-Katalog allein erteilt keine pauschale Erlaubnis zur Spiegelung. Vor der Auslieferung eines Images oder Katalogs prüft Titan die tatsächlich enthaltenen Bestandteile, übernimmt vorgeschriebene Hinweise und erfüllt gegebenenfalls Pflichten zur Bereitstellung von Quellcode. Das gilt auch für übernommene TitanOS-Dateien. TitanOS veröffentlicht seinen Code unter der FSL-1.1-ALv2. [TitanOS-Lizenz](https://github.com/ra5on/TitanOS/blob/HEAD/LICENSE.md)

Die Namen Umbrel und umbrelOS bezeichnen hier die Herkunft der Software und die angestrebte Kompatibilität. Titan wird unabhängig von Umbrel veröffentlicht. Fragen und Fehlerberichte zum Fork gehören in das Titan-Projekt. [Titan auf GitHub](https://github.com/ra5on/Titan)

## Gewährleistung, Haftung und Datensicherung

Titan wird unentgeltlich im jeweils vorliegenden Zustand bereitgestellt. Das Projekt übernimmt keine Garantie für Fehlerfreiheit, Verfügbarkeit, Kompatibilität mit bestimmter Hardware oder die Wiederherstellbarkeit von Daten. Soweit gesetzlich zulässig, ist die Haftung der Projektverantwortlichen und Mitwirkenden für Schäden aus Installation, Updates oder Betrieb ausgeschlossen. Dazu zählen insbesondere Datenverlust, beschädigte Dateisysteme, fehlgeschlagene Wiederherstellungen und Betriebsausfälle.

Zwingende gesetzliche Ansprüche bleiben bestehen. Der Ausschluss gilt insbesondere nicht bei Vorsatz oder grober Fahrlässigkeit, bei schuldhafter Verletzung von Leben, Körper oder Gesundheit oder soweit das jeweils anwendbare Produkthaftungsrecht eine Haftung vorschreibt. [§ 276 BGB](https://www.gesetze-im-internet.de/bgb/__276.html) · [§ 309 Nr. 7 BGB](https://www.gesetze-im-internet.de/bgb/__309.html)

**Das Schreiben eines Systemimages überschreibt das gewählte Laufwerk einschließlich seiner Partitionen und Daten.** Prüfe das Ziellaufwerk anhand von Modell und Größe. Sichere wichtige Dateien, Konfigurationen und VM-Daten vor Installation oder Updates auf einem getrennten Datenträger und prüfe, ob sich die Sicherung wiederherstellen lässt.
