# Titan 0.5.5 Alpha

Dieses Release ergänzt den Fernzugriff über Cloudflare, kompakte VM-Kacheln und unabhängige App-Sicherungen. Der App Store gibt beim Scrollen mehr Platz für Anwendungen frei; anpassbare Seitenleisten und persönliche Desktop-Einstellungen verbessern die Platznutzung. **Titan bleibt Alpha: zunächst mit Testdaten und auf einer separaten Testinstallation verwenden.**

## Neu und verbessert

- **Cloudflared Web:** Das Verwaltungspasswort ist bei neuen Installationen optional. Ein leeres Passwort schaltet die Basic-Anmeldung der Connector-Verwaltung aus. Tunnel-Token und Titan-Anmeldung sind davon unabhängig; vorhandene Zugangsdaten bleiben erhalten.
- **Fernzugriff:** Unter **Systemsteuerung → Allgemein** eine zusätzliche öffentliche HTTPS-Adresse und den tatsächlichen Connector wählen. Titan zeigt die passende lokale **Service URL auf Port 5102** für Host-Netz oder erkannte Docker-Bridge an, ergänzt die benötigte begrenzte Firewallregel und erhält die lokale NAS-Adresse. Eine Diagnose unterscheidet Connectorstatus, lokales Ziel und öffentlichen HTTPS-Zugang. DNS und Tunnelroute werden weiterhin in Cloudflare eingerichtet; es erfolgt keine automatische Cloudflare-Konfiguration mit einem API-Token. Öffentliche App-Adressen werden ausdrücklich hinterlegt.
- **VM-Verwaltung:** Jede VM erhält eine kompakte Kachel mit Name, Status, gemessener CPU-Auslastung und RAM auf dem NAS (RSS). Die Werte aktualisieren sich alle fünf Sekunden; fehlende Messwerte bleiben erkennbar. Ein Klick öffnet Details über die nutzbare Fensterfläche. Zurück erhält Suche und Auswahl; die Konsole nutzt die verfügbare Fläche.
- **App Store:** Katalogaktionen, Ansichten, Hinweise und Suche scrollen zusammen mit den Apps. Eine stehenbleibende obere Leiste verkleinert die App-Liste nicht mehr. Suchbegriff, Filter und die gewählte Ansicht bleiben beim Wechsel der Bereiche erhalten.
- **Seitenleisten:** Systemsteuerung, Speicher, Docker und VM-Verwaltung erhalten verstellbare Breiten per Ziehen oder Tastatur; auch die Benutzer- und Docker-Details lassen sich bei genügend Platz anpassen. Die Wahl bleibt pro Konto und Arbeitsbereich im Browser gespeichert; auf Mobilgeräten bleibt die kompakte Navigation erhalten. VM-Details nutzen die volle Fläche.
- **Persönlicher Desktop:** Im Benutzermenü und unter Persönlich Transparenz von 0 bis 100 % einstellen sowie beim Klick auf den freien Desktop zwischen Nichts und Alle Fenster minimieren wählen. Diese Einstellungen werden pro Konto auf dem NAS gespeichert. Text und App-Inhalte behalten ihre volle Deckkraft.
- **App-Sicherungen:** Im zentralen Sicherungsassistenten installierte Apps auswählen. Konfiguration, interne Datenbanken und Zugangsdaten werden gemeinsam auf dem getrennten Backupziel gesichert; Nutzdaten lassen sich ausdrücklich zusätzlich auswählen. Titan hält die App für einen konsistenten Stand an und startet danach nur die zuvor laufenden Dienste.
- **App-Wiederherstellung:** Gestoppte, weiterhin passende installierte Pakete lassen sich aus der Sicherung wiederherstellen. Titan prüft Vorlage, lokale und neu erstellte Images, Archiv und Rechte; ein Versionswechsel wird abgewiesen. Die App bleibt gestoppt. Der vorherige Stand bleibt für die lokale Rücksetzung erhalten; bei unvollständiger Rücksetzung sperrt ein Recovery-Marker den Start.

## Installation und Update

Für das Installationsimage **UEFI/OVMF**, deaktiviertes Secure Boot, **8 GiB RAM** und mindestens **64 GiB virtuelle Festplatte** verwenden. Die `.img.xz` entpacken; das enthaltene Image ist 48 GiB groß. Die virtuelle Festplatte vor dem ersten Start entsprechend vergrößern. Beim Schreiben auf einen Datenträger werden dessen bisherige Daten überschrieben.

Neue Installationen sind unter `https://<NAS-IP>` erreichbar. Bestehende Installationen behalten ihre eingerichteten Webports. Das signierte Systemupdate wird über **Updates & Rollback → Alpha-Kanal** installiert; der anschließende Neustart wird ausdrücklich ausgelöst.

Ein System-Rollback setzt gemeinsame App-Daten und Datenbanken nicht zurück. Unabhängige Sicherungen und eine praktisch geprüfte Wiederherstellung bleiben erforderlich. Ein erfolgreicher Demoablauf ersetzt keinen echten Tunneltest, NAS-Hardwaretest oder Image-Starttest.

Details: [Fernzugriff](REMOTE-ACCESS.md), [App-Katalog](APP-STORES.md), [VM-Verwaltung](PACKAGES-AND-VMS.md), [Sicherungen und Recovery](BACKUPS.md), [Desktop und Seitenleisten](UI-DESIGN.md). Verfügbare Image-, Update-, Prüfsummen- und Prüfbericht-Dateien gehören zum Release.
