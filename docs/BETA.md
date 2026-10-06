# Titan · Testplan vor der ersten Beta

**Titan 0.5.3 bleibt Alpha.** Der Benutzer entscheidet nach dem eigenen Test, ob die Beta freigegeben werden kann. Ein grüner Build allein bestätigt keine Beta-Reife.

## Testumgebung

Bestehende Titan-Installation über **Alpha → Systemsteuerung → Updates & Rollback** aktualisieren. Für eine neue Installation das [0.4.6-Testimage](TITAN-IMAGE.md) importieren und anschließend aktualisieren. Zusätzliche virtuelle Datenplatten, ein separates Sicherungsziel und zwei normale Testkonten verwenden. Für echte Gäste Nested-KVM in Proxmox einschalten. Nur entbehrliche Testdaten verwenden.

## Zehn Abnahmebereiche

| Bereich | Auf dem NAS prüfen | Erwartetes Ergebnis |
| --- | --- | --- |
| Desktop und mobile Ansicht | Verknüpfungen verschieben, hinzufügen, entfernen; mehrere Fenster öffnen und verkleinern; Browser neu laden; Handy hochkant und quer | Docker ist als Verknüpfung verfügbar, Symbolgrößen und App-Deinstallation sind verständlich; Positionen bleiben gespeichert; keine seitlich verrutschte Seite; Aktionen und Dialoge bleiben erreichbar |
| Dateimanager | Ortsspalte links/rechts, Breite ziehen, ausblenden und erneut öffnen; NAS-Dateien als Start, Favoriten, Suche über Unterordner und Filter; Text jeder Endung bearbeiten; kopieren, verschieben, umbenennen, Papierkorb und Wiederherstellung | Persönliche Seitenbreite/-position bleibt nach Neuladen erhalten; mobile Ortsschublade verdeckt die Liste nur während der Auswahl; richtige Fundorte und Rechte; keine verlorenen Änderungen; Löschen mit Ja/Nein; obere Aktionen bleiben beim Scrollen sichtbar |
| Benutzer und Gruppen | Gruppenbeitritt/-austritt, Lesen/Schreiben/kein Zugriff, ausdrückliche Benutzerrechte, Konto sperren/löschen, privater persönlicher Ordner; echten SMB-Client verwenden | Wirksame Rechte stimmen in Web und SMB überein; gesperrtes Konto verliert Zugang; privater Ordner bleibt privat |
| Speicher und Quoten | Übersicht/Speicherbereiche/HDD-SSD/Wartung und Auswahl einzelner Bereiche; Systemplatte vergrößern; Ext4/XFS-Volume oder ZFS-Pool einrichten, Standardspeicher ändern und neue Apps/VMs/Freigaben dort anlegen; SMART-Test und ZFS-Wartungsplan; Snapshot klonen; ZFS-Benutzerlimit erreichen | Systemspeicher und aktive Datenbereiche erscheinen; ZFS-Datasets zählen nicht zusätzlich als Poolkapazität; Offline-Volumes bleiben verbindbar; nur vorhandener Speicher/Messwerte erscheinen; Systemdaten erhalten; keine fremden Snapshots entfernt; tatsächliche Schreibbegrenzung; bestehende Daten unverändert; offline/voll kein automatischer Speicherwechsel |
| App-Pakete und Office | Eigenes Docker-Bridge-Netz nur mit Namen erstellen, auswählen und Adressen prüfen; Entfernen mit verbundenem sowie gestopptem Container versuchen, danach Zuordnung lösen und mit Ja/Nein entfernen; alle vier Pakete installieren, neu starten, Paket und einzelnen Dienst stoppen, deinstallieren und mit erhaltenen Daten erneut installieren; Nextcloud-Desktopzugang und RAM-Vorprüfung vor dem Download prüfen; Port ändern, Logs/Diagnose/Reparatur prüfen; DOCX/XLSX/ODT aus einer Freigabe öffnen, ändern, schließen und erneut öffnen | Automatisches Subnetz ohne Überschneidung; belegte, fremde und eingebaute Netze geschützt; Projekte und Dienstaktionen bleiben eindeutig; Abhängigkeiten bereit; Daten nach Neustart erhalten; Dokumentänderung in Originaldatei gespeichert; Leser kann nicht schreiben; gleichzeitige Fremdänderung wird erkannt |
| Virtuelle Maschinen | Maschinenliste/Detailbereich bei breitem und schmalem Fenster, Zurück-Navigation; ISO und IMG/QCOW2, BIOS/UEFI, CPU-Auswahl, integrierte Konsole, mehrere Disks/NICs, Gastagent; kalten Snapshot/Klon und externes Mehrdisk-Archiv erstellen/wiederherstellen | Details nutzen die Arbeitsfläche, mobil eine Ebene und Konsole in voller Ansicht; Gast startet und Konsole verbindet automatisch; gestoppte VM zeigt keinen laufenden RAM-Verbrauch; Sicherung enthält alle Laufwerke und passende Bootdaten |
| Datensicherung | Assistent und Zeitplan; externe Platte abziehen; verschiedene Versionen ansehen; einzelne Datei und Ordner wiederherstellen; normalen Backup-Benutzer testen | Unverfügbare Ziele melden Fehler; kein Schreiben auf die Systemplatte; Restore in neuem Ordner mit Zielrechten; fremde Quellen und Konfigurationsdaten bleiben unzugänglich |
| Sicherheit | Anmeldeschutz einstellen, Fehlversuche/Sperrzeit/Neustart und manuelles Entsperren testen; OS-Dateien als Webadministrator lesen/ändern versuchen, NAS-Daten weiterhin bearbeiten; Zwei-Faktor-Anmeldung einrichten, falschen/gleichen Code erneut versuchen, Wiederherstellungscode verwenden, Sitzung widerrufen; Konfigurationsbackup wiederherstellen | Konfigurierte Sperre wirksam und persistent; Systemdateien gesperrt, Daten zugänglich; Codes nur einmal gültig; zweite Sitzung verliert Zugang; Konten und Regeln bleiben konsistent; Wiederherstellungscodes danach erneuern |
| Ressourcen und Meldungen | Dateiübertragung, CPU-/RAM-Last, VM-/App-Stop; Alarm auslösen und bestätigen; eigenen SMTP-TLS/STARTTLS-Server konfigurieren, Testnachricht empfangen | Verlauf zeigt reale Veränderungen und passende Einheiten; fehlende Sensoren erzeugen keine erfundenen Werte; Meldung führt zum richtigen Bereich; Mail kommt an |
| Updates und Dauerbetrieb | Prüfen, installieren, neu starten, Rollback und erneut aktualisieren; 24 Stunden mit Apps/VMs; Strom-/Gastreset nur in entbehrlicher Testumgebung | Vorheriger bootfähiger Stand verfügbar; Nutzdaten, Benutzer und Rechte erhalten; keine dauerhaft fehlernden Dienste oder Ressourcenlecks |

## Bekannte Grenzen

Kalte VM-Snapshots enthalten Laufwerke und Konfiguration, keinen RAM-Zustand. ZFS-Quoten werden tatsächlich gesetzt; Ext4/XFS ohne eingerichtetes Quota-Backend bieten kein Benutzerlimit. Netzwerksicherungsziele müssen bereits sicher eingebunden sein. Externe App-Nutzdaten sind nicht automatisch Teil einer Paket-Konfigurations-/Datenbanksicherung. Office-Dokumente sind auf 16 MiB begrenzt; alte DOC/XLS/PPT-Dateien werden im integrierten Editor nur angezeigt.

Systemstände vor 0.5.0 kennen die neue Zwei-Faktor-Prüfung nicht. Der Rollback-Dialog erklärt diesen Wechsel; nach Rückkehr auf eine ältere Version sind für diese Zeit nur die dort unterstützten Anmeldeprüfungen aktiv. Das ist ausdrücklich mit in den Testbericht aufzunehmen.

Systemstände vor 0.5.3 enthalten den konfigurierbaren Anmeldeschutz und die neue
NAS-Datengrenze nicht. Auch ein reiner Debian-Wartungsstand besitzt die
Schutzfunktionen seines eingefrorenen Titan-Anwendungsstands. Der Rollback-Dialog
nennt diesen Sicherheitswechsel; die vorherigen Nutzdaten werden dadurch nicht
zurückgesetzt.

## Ergebnis festhalten

```text
Titan-Version und Datum:
Proxmox-Version oder NAS-Hardware:
CPU / Nested-KVM / RAM / System- und Datenplatten:
Browser / Handy / SMB-Client / App- oder Gastversion:
Prüfung und erwartetes Ergebnis:
Beobachtung und reproduzierbare Schritte:
Status: bestanden | fehlgeschlagen | übersprungen | offen
Nachweis: Screenshot / Protokoll ohne Zugangsdaten
```

Beta-Freigabe erst nach bestandenen Kernabläufen und ohne offene Fehler mit Datenverlust, unberechtigtem Zugriff, defektem Update/Rollback oder nicht nutzbarer mobiler Oberfläche. Physische Hardwarefunktionen dürfen nur mit konkret genanntem Teststand als geprüft gelten.
