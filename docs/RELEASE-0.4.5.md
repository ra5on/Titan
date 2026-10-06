> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.5 · Alpha · Neuer NAS-Desktop

Titan erhält einen hellen NAS-Desktop nach der gewünschten FygoOS-Bedienrichtung: eigene farbige Anwendungssymbole, kompakte Navigation und klare Verwaltungsfenster. Die Startseite verbindet direkte App-Zugriffe mit den weiterhin gemessenen Systemwerten. Die Statuskarten bleiben pro Konto anordbar; Uhrzeit, CPU und RAM aktualisieren sich automatisch.

**Einstellungen** sind ein eigenes Zentrum mit zehn direkt auswählbaren Kategorien, Suche und separaten Seiten für Servername, Update-Kanal und Komponentenprüfung. Getrennte Einstellungsformulare erhalten alle Werte der jeweils anderen Bereiche.

**Virtuelle Maschinen** erhalten Ansichten für Maschinen, Übersicht, ISO-Medien und Host-Hardware. CPU-/RAM-/Laufwerksdaten, P-/E-Kerne bei vorhandener Hostmeldung, vorhandene Laufwerksimages und alle bisherigen Aktionen bleiben erreichbar. Konfigurierte Ressourcen und gemessene Auslastung sind klar bezeichnet.

**Docker** erhält einen eigenen Manager für installierte Apps, Status und Netzwerkadressen. Anmeldung, Start/Stop, Protokolle, Sicherungen und Netzwerkverwaltung bleiben erhalten. Der **App Store** bleibt ein separater Bereich mit 42 Vorlagen und den bisherigen Installationsoptionen.

Der **Dateimanager** verwendet eine helle Explorer-Ansicht. Befehle, Pfad und Suche stehen fest; Liste, Dateiorte und Eigenschaften scrollen in ihren Bereichen. Die direkte Bearbeitung von UTF-8-Textdateien beliebiger Endung bis 1 MiB samt Strg/Cmd+S, Versionsprüfung und Schutz ungespeicherter Änderungen bleibt erhalten. Binäre Formate und schreibgeschützte Ziele werden nicht überschrieben.

Die Oberfläche passt sich Desktop, Tablet und Smartphone an. Eine gespeicherte Menüpräferenz bleibt bestehen; neue Desktop-Sitzungen starten mit einem kompakten, scrollbar sichtbaren Dock. Es werden eigene SVG-/CSS-Grafiken verwendet.

Lokal bestanden 973 Python-Tests (ein historischer ISO-Fixture ausgelassen), 25 Node-Testsuiten und 18 Browser-JS-Syntaxprüfungen. Browserprüfungen auf Desktop, Tablet und Smartphone bestätigen die neuen Ansichten, erhaltene Einstellungen, gespeicherte Kartenreihenfolge, direkte Dateibearbeitung und eine fehlerfreie Konsole. Die Veröffentlichung setzt außerdem die verpflichtenden Image-Start-/Laufzeitprüfungen voraus. Tatsächliche Ergebnisse stehen nach erfolgreicher Freigabe in den signierten Release-Berichten.

**v0.4.5 kommt über den signierten Update-Kanal.** Das vorhandene [v0.4.2-Installationsimage](https://github.com/ra5on/Titan/releases/download/v0.4.2/titan-0.4.2-x86_64.img.xz) bleibt verfügbar. Kanal **Alpha** wählen, nach Updates suchen, v0.4.5 vorbereiten und den Neustart ausdrücklich durchführen. Danach die Browserseite neu laden.

**Veröffentlichungsnachweis:** v0.4.5 hat am **2. Oktober 2026** im [Actions-Lauf 37034137762](https://github.com/ra5on/Titan/actions/runs/37034137762) den Image-Erststart und alle **zehn Laufzeitprüfungen** bestanden. Der geprüfte Source-Stand ist [67e5fab51b7a](https://github.com/ra5on/Titan/commit/67e5fab51b7afdad3dd4782c93b6596a43caf3e1); der [öffentliche Laufzeitbericht](https://github.com/ra5on/Titan/releases/download/v0.4.5/runtime-test.json) dokumentiert die tatsächlichen Ergebnisse. Geprüft wurden Administrator-Ersteinrichtung, App-Katalog/Anmeldung, Update-Zustand, CPU/RAM, Systemdisk-Erweiterung, SMB mit mehreren Benutzerrechten, installierte Komponenten, Docker-App mit Standard- und eigenem Bridge-Netz sowie VM-Lebenszyklus und authentifizierte Browserkonsolen-Verbindung mit RFB 3.8. Die Systemdisk wuchs von 32 auf 36 GiB; Partition und XFS wuchsen um genau 4 GiB, während Partitionsanfang, UUIDs, Testdatei-SHA256 und originales Raw-Image erhalten blieben. Wiederholungen waren wirkungslos. Die öffentlichen Manifest-/Prüfsummensignaturen und sämtliche Asset-Digests wurden unabhängig überprüft. Der tatsächliche Titan-Updater erkennt v0.4.5 vom simulierten installierten v0.4.4-Stand als verfügbares signiertes Alpha-Update; dabei wurde weder ein Update installiert noch ein Neustart ausgelöst.

**Titan bleibt Alpha.** Der manuelle Proxmox-/Hardwaretest und der vollständige OS-Update-/Neustart-/Rollback-Zyklus bleiben für die Beta erforderlich.

[Bedienungsnachweis](https://github.com/ra5on/Titan/blob/main/docs/TESTING.md#nas-desktop-und-manager-in-v045) · [Update-Anleitung](https://github.com/ra5on/Titan/blob/main/docs/UPDATES.md) · [Beta-Kriterien](https://github.com/ra5on/Titan/blob/main/docs/BETA.md)
