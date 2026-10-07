# Titan 0.5.6 Alpha

Image, signiertes Update, Checksummen und Prüfberichte werden nach erfolgreichem Build und den zugehörigen Prüfungen im verlinkten Release veröffentlicht. Titan bleibt Alpha: zunächst mit Testdaten und auf einer separaten Testinstallation verwenden.

Dieses Release ergänzt Hell/Dunkel-Darstellung, eigene Glasflächen und Schnellaktionen auf dem Desktop und im Hauptmenü. Verschiebbare Statuswidgets, einheitliche Bestätigungen und kompaktere Verwaltungsfenster verbessern die tägliche Bedienung.

## Neu und verbessert

- **Hell, Dunkel und Automatisch:** Im Kontomenü unter Darstellung den Modus wählen. Automatisch folgt dem Betriebssystemthema. Die Einstellung bleibt pro Konto auf dem NAS gespeichert; offene und neu geöffnete Titan-Appfenster übernehmen den aktuellen Modus. Beim Abmelden wird die Darstellung zurückgesetzt.
- **Eigene Glasoptik:** Kopfzeilen, Menüs und Statuswidgets verwenden die eingestellte Desktop-Transparenz. Text und App-Inhalte bleiben deckend. Reduzierte Transparenz, stärkerer Kontrast und Browser ohne Hintergrundunschärfe erhalten deckende Flächen. TitanOS ist eine visuelle Inspiration; Code, Styles und Symbole stammen aus der eigenen Titan-Umsetzung. TitanOS-Code und -Assets werden nicht übernommen.
- **Schnellaktionen:** Auf Desktop- und Hauptmenüsymbolen per Rechtsklick, längerem Drücken für 550 ms, Umschalt+F10 oder ⋯ öffnen. Je nach Eintrag und vorhandenen Rechten stehen Öffnen, Einstellungen und Details, Starten/Stoppen sowie Verknüpfungs- und Ordneraktionen bereit. Touch und Tastatur erhalten Fokussteuerung; ein langes Drücken startet die App nicht zusätzlich. App-Schnellaktionen warten auf geladene Fenster; verspätete Antworten überschreiben keine neuere Auswahl.
- **Verknüpfung und Deinstallation:** Vom Desktop entfernen löscht nur den Verweis. App deinstallieren … ist eine eigene bestätigte Aktion; Konfiguration, Datenbanken und Nutzdaten bleiben erhalten. Bestehende Bedienrechte gelten auch für Schnellaktionen.
- **Statuswidgets verschieben:** Administratoren können den Widget-Griff ziehen oder mit Pfeiltasten bewegen; Umschalt erlaubt kleinere Schritte. Die Position bleibt pro Konto auf dem NAS gespeichert und passt sich dem verfügbaren Platz an. Die bestehenden Administratorrechte für Systemstatus und Messwerte bleiben maßgeblich.
- **Einheitliche Bestätigungen:** Ja beziehungsweise die positive Aktion steht links, Nein/Abbrechen rechts, auch in eigenen Dialogen. Ja/Nein-Abfragen fokussieren zunächst Nein. Vor der Bestätigung brechen Escape und Schließen die Abfrage ab; tatsächliche Aktionen benötigen weiterhin eine ausdrückliche Bestätigung. Im Texteditor bleibt Weiter bearbeiten die sichere fokussierte Wahl bei ungespeicherten Änderungen.
- **Mehr nutzbare Fensterfläche:** Docker-, Speicher-, Einstellungs- und Benutzeransichten verwenden kompaktere Abstände. Befehle und zugehörige Inhalte scrollen gemeinsam, Formularaktionen folgen den Feldern. Lange Protokolle und Hinweise erzeugen weniger verschachtelte Scrollbereiche. Anpassbare Seitenleisten, mobile Navigation, Dateimanager und die volle VM-Detailfläche bleiben erhalten.

## Installation und Update

Für das Installationsimage **UEFI/OVMF**, deaktiviertes Secure Boot, **8 GiB RAM** und mindestens **64 GiB virtuelle Festplatte** verwenden. Die `.img.xz` entpacken; das enthaltene Image ist 48 GiB groß. Die virtuelle Festplatte vor dem ersten Start entsprechend vergrößern. Beim Schreiben auf einen Datenträger werden dessen bisherige Daten überschrieben.

Neue Installationen sind unter `https://<NAS-IP>` erreichbar. Bestehende Installationen behalten ihre eingerichteten Webports. Nach der Releasefreigabe wird das signierte Systemupdate über **Updates & Rollback → Alpha-Kanal** angeboten; der anschließende Neustart wird ausdrücklich ausgelöst.

## Bestehende Grenzen

Der Fernzugriff aus 0.5.5 bleibt erhalten: Titan unterstützt die lokale Service URL auf Port 5102 für den gewählten Cloudflared-Connector und erhält die lokale NAS-Adresse. DNS und Tunnelroute werden weiterhin in Cloudflare eingerichtet. Das optionale Cloudflared-Verwaltungspasswort ist unabhängig von Tunnel-Token und Titan-Anmeldung.

App-Sicherungen gehören auf ein getrenntes Backupziel. Konfiguration, interne Datenbanken und Zugangsdaten werden gemeinsam gesichert; zusätzliche Nutzdaten werden ausdrücklich ausgewählt. Eine Wiederherstellung benötigt ein gestopptes, weiterhin passendes installiertes Paket und unterstützt keinen Versionswechsel. Die App bleibt danach gestoppt; der vorherige Stand bleibt für die lokale Rücksetzung erhalten.

Geprüfte relative symbolische Links innerhalb desselben ausgewählten App-Verzeichnisses bleiben erhalten. Absolute oder nach außen führende Links, verwaiste Ziele, Schleifen, Hardlinks und Spezialdateien bleiben gesperrt. Ein System-Rollback setzt gemeinsame App-Daten und Datenbanken nicht zurück. Unabhängige Sicherungen und eine praktisch geprüfte Wiederherstellung bleiben erforderlich.

Die lokale Python- und UI-Regression prüft Bedienung, Berechtigungsgrenzen und echte Caddy-Proxys. Sie ersetzt keinen realen Tunnel-, NAS-Hardware- oder Image-Starttest. Maßgeblich für die Downloadfreigabe sind die zum Release gehörenden Build- und Prüfberichte.

Details: [Desktop und Bedienung](UI-DESIGN.md), [Fernzugriff](REMOTE-ACCESS.md), [App-Katalog](APP-STORES.md), [VM-Verwaltung](PACKAGES-AND-VMS.md), [Sicherungen und Recovery](BACKUPS.md). [Release 0.5.6-alpha.1](https://github.com/ra5on/Titan/releases/tag/v0.5.6-alpha.1).
