> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.4 · Alpha · uCore · Dateimanager und Navigation

[Signaturen und Testergebnisse](https://github.com/ra5on/Titan/releases/tag/v0.4.4)

Der Dateimanager bietet einen direkten **Bearbeiten-Stift** in jeder passenden Dateizeile und die Taste **F4**. Textvorschauen erkennen UTF-8-Inhalte auch bei unbekannten Dateiendungen. **Strg/Cmd+S** und der Speichern-Knopf speichern im geöffneten Editor; Änderungsstatus, Dateigröße, Zeile/Spalte, Wortumbruch und Tab-Einrückung helfen bei der Bearbeitung.

Textdateien mit jeder Endung werden bis **1 MiB** unterstützt. UTF-8-BOM und einheitliche LF-, CRLF- oder CR-Zeilenenden bleiben erhalten. Gemischte Zeilenenden werden bei einer gespeicherten Änderung mit sichtbarem Hinweis auf LF vereinheitlicht. Office-Dateien, Bilder und Archive sind binäre Formate und brauchen ihre passende Anwendung. Zugriffsrechte und unveränderliche Systempfade bleiben wirksam.

Vor dem Schreiben wird die gelesene Dateiversion geprüft. Anschließend bestätigt Titan gespeicherte Bytes und die neue Version. Konflikte oder unbestätigte Antworten bewahren den Editorinhalt und verhindern blindes Überschreiben. Beim Schließen ungespeicherter Änderungen lässt sich **weiter bearbeiten** oder ausdrücklich **verwerfen und schließen**. Verspätete Antworten öffnen keine bereits abgewählte Datei erneut.

Werkzeugleiste, Pfad und Suche bleiben beim Scrollen der Dateiliste sichtbar. Dateiorte und Details haben eigene Scrollbereiche; Mobilgeräte können Liste und Eigenschaften gemeinsam erreichen. Bei sehr kurzen Fenstern bleiben die Aktionen über einen Scroll-Fallback erreichbar.

Das **Hauptmenü lässt sich links oben auf Symbole einklappen**. Die Auswahl bleibt pro Benutzer im jeweiligen Browser gespeichert. Schmale Desktop-/Tabletfenster starten ohne gespeicherte Auswahl platzsparend; auf Mobilgeräten bleibt das aufklappbare Menü mit Fokus- und Escape-Steuerung erhalten.

Lokal wurden **973 Python-Tests** ohne Fehler (ein historischer ISO-Fixture ausgelassen), **22 Node-Testsuiten** und die Syntax aller **15 Browser-JS-Dateien** geprüft. Browserprüfungen auf Desktop, Tablet und Smartphone bestätigen direktes Speichern, BOM/CRLF-Erhaltung, Binärschutz, Umgang mit ungespeicherten Änderungen, feste Leisten, Menü-Persistenz und eine fehlerfreie Konsole. Die verpflichtenden Image-Start-/Laufzeitprüfungen müssen vor der öffentlichen Freigabe erneut bestehen; ihre tatsächlichen Ergebnisse stehen in den signierten Release-Dateien.

**v0.4.4 wird über den signierten Update-Kanal verteilt.** Das vorhandene [v0.4.2-Installationsimage](https://github.com/ra5on/Titan/releases/download/v0.4.2/titan-0.4.2-x86_64.img.xz) bleibt verfügbar. In Titan den Kanal **Alpha** wählen, nach Updates suchen, die neue Systemversion vorbereiten und den Neustart ausdrücklich durchführen. Danach die Browserseite neu laden.

**Veröffentlichungsnachweis:** v0.4.4 hat am **2. Oktober 2026** im [Actions-Lauf 36998515941](https://github.com/ra5on/Titan/actions/runs/36998515941) den Image-Erststart und alle **zehn Laufzeitprüfungen** bestanden. Der geprüfte Source-Stand ist [a228b96fff5f](https://github.com/ra5on/Titan/commit/a228b96fff5f137b04419982feedba6ab38a5331); der [öffentliche Laufzeitbericht](https://github.com/ra5on/Titan/releases/download/v0.4.4/runtime-test.json) enthält die tatsächlichen Ergebnisse. SMB mit unterschiedlichen Benutzerrechten, Docker-App und eigenes Bridge-Netz, VMs mit verfügbarem KVM und Browserkonsolen-Verbindung, CPU/RAM sowie Systemdisk-Erweiterung sind auf diesem Stand erneut bestanden. Die virtuelle Systemdisk wurde von 32 auf 36 GiB vergrößert; Partition und XFS wuchsen jeweils um genau 4 GiB; UUIDs, Partitionsanfang, Testdatei-SHA256 und originales Raw-Image blieben erhalten. Die öffentlichen Manifest-/Prüfsummensignaturen und Asset-Digests wurden nach Veröffentlichung unabhängig geprüft. Der tatsächliche Titan-Updater erkennt v0.4.4 vom simulierten installierten v0.4.3-Stand als verfügbares signiertes Alpha-Update; es wurde dabei kein Update installiert oder Neustart ausgelöst.

**Titan bleibt Alpha.** Ein manueller Proxmox-/Hardwaretest und ein vollständiger OS-Update-/Neustart-/Rollback-Zyklus bleiben für die Beta erforderlich.

[Bedienungsnachweis](https://github.com/ra5on/Titan/blob/main/docs/TESTING.md#dateimanager-und-navigation-in-v044) · [Update-Anleitung](https://github.com/ra5on/Titan/blob/main/docs/UPDATES.md) · [Beta-Kriterien](https://github.com/ra5on/Titan/blob/main/docs/BETA.md)
