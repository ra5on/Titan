# Titan 0.5.0 · Prüfnachweis vor dem NAS-Test

Stand: 4. Oktober 2026. Titan bleibt Alpha.

## Lokal geprüft

- Vollständige Python-Regression: **1.174 Tests, bestanden; eine Prüfung übersprungen**. Enthalten sind echte lokale HTTP-Server, Zugriffsrechte, widerrufene Office-Sitzungen, Dateisuche, Sicherung/Wiederherstellung, Paketkonfiguration und QEMU-Laufwerksfixtures. Lokale Office-Cache-Adressen mit implizitem oder ausgeschriebenem Standardport sowie Converter-Pfaden behalten ihre Dokument-, Anmelde- und Freigabeprüfung; fremde Hosts, Ports, Protokolle und Dokumente bleiben abgewiesen. VM-Snapshots verwenden einen expliziten qcow2-Treiber mit QEMU-8.2-kompatibler Syntax; echte Erstellen-/Wiederherstellen-/Entfernen-Roundtrips und unsichere Imageformate sind geprüft. Die erste Office-Einrichtung wartet auf den Nextcloud-Webcache und bleibt bei dauerhaftem Verbindungsfehler unvollständig.
- **35 JavaScript/UI-Suites** sowie JavaScript- und Shell-Syntax geprüft. Der anschließend ergänzte Test für den Scrollstart neuer Dialoge ist ebenfalls bestanden.
- Isolierte laufende Demo im Browser: freies Verschieben und gespeicherte Desktopposition nach Neuladen; Dateimanager bei **390 und 320 Pixeln** mit einer Scrollfläche, oben bleibender Werkzeugleiste und Auswahlaktionen; Löschdialog mit Ja/Nein und Abbruch. Ordnerfavoriten bleiben nach Neuladen sichtbar und werden nach aktuellen Freigaberechten gefiltert. Unterordnersuche findet Dokumente/Budget.csv und öffnet die Vorschau mit dem vollständigen Dateipfad.
- Alle elf Bereiche der Systemsteuerung bei 390 Pixeln und zehn Bereiche bei 320 Pixeln ohne Überbreite geprüft. Benutzer, Gruppen, Sicherheit, Updates, Sicherungsassistent und Dienste wurden geöffnet.
- Immich über das tatsächliche Standardformular installiert: **4/4 Dienste** im Paketzentrum. Registerkarten, Diagnose, Einstellungen und dienstbezogene Protokolle bedient. Mobile Paketdialoge scrollen allein und starten am oberen Rand.
- VM heruntergefahren und zusätzliche 16-GiB-Festplatte angelegt. Hardware- und Netzwerkregister bedient. Ausgeschaltet: CPU/RAM und I/O null; Gesamtkapazität beider Laufwerke 48 GiB.
- Vier tatsächliche Demo-Screenshots sind in der README enthalten. Beispieldaten liegen ausschließlich in der isolierten Demo.

## Prüfung in GitHub Actions

Der [Release-Workflow für 0.5.0-alpha.1](https://github.com/ra5on/Titan/actions/runs/37204262616) ist erfolgreich abgeschlossen. Er hat alle 1.174 Pythonregressionen und die UI-Prüfungen erneut ausgeführt. Alle vier Pakete mit echten Docker-Containern haben ihre Abhängigkeiten, interne Verbindungen, Ports und Neustarts bestanden. Nextcloud/Euro-Office hat zusätzlich den lokalen Titan-Dokumentabruf, echte DOCX/ODT-Konvertierung, signiertes Rückschreiben im Originalformat, erhaltene Dateirechte und die Abweisung ungültiger Speicheranfragen bestanden.

Der signierte Debian-A/B-Build hat in einer Wegwerf-VM Boot, HTTPS, UEFI und authentifizierte VNC-Verbindungen bestanden. Auch SMB-Rechte mit mehreren Benutzern, CPU/RAM, Docker-Lifecycle, eigene Netzwerke, Mehrcontainer-Verwaltung und VM-Lifecycle sind geprüft. Der vollständige A/B-Test hat das Update von der veröffentlichten 0.4.6-Basis, das Wachstum des Datenbereichs, erhaltene Benutzerkonten/Freigaberechte/Testdateien nach Neustart, manuellen Rollback und automatischen Rückfall nach einem absichtlich defekten Kandidaten bestanden. Die Installation startet das NAS nicht ungefragt neu.

Die [normale CI](https://github.com/ra5on/Titan/actions/runs/37204262391) und die [Debian-Integrationsvorschau](https://github.com/ra5on/Titan/actions/runs/37204262384) für denselben Release-Commit sind ebenfalls erfolgreich. Das [veröffentlichte Release](https://github.com/ra5on/Titan/releases/tag/v0.5.0-alpha.1) enthält das signierte RAUC-Systemupdate, Manifest, Prüfsummen sowie `runtime-test.json` und `ab-test.json` als maschinenlesbare Nachweise. Ein neues IMG/ISO wird mit dieser Version nicht veröffentlicht; das bestehende Testimage aktualisiert über den Alpha-Kanal.

## Noch auf dem NAS zu prüfen

Echte USB/GPU-Geräte, SMART/ZFS-Wartung, SMTP-Zustellung, SMB mit getrennten Clientkonten, interaktive Office-Bedienung, echte Mobilbrowser und längerer Betrieb. Die Demo ersetzt diese Prüfungen nicht. [Beta-Checkliste](BETA.md).
