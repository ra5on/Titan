# Prüfnachweis · Titan 0.5.1 Alpha

Stand: 4. Oktober 2026. Lokale Prüfungen, GitHub-CI, Debian-Integration, alle vier echten App-Pakettests sowie Boot und vollständiger Update-/Rollback-Test sind bestanden. Das [signierte Systemupdate 0.5.1-alpha.1](https://github.com/ra5on/Titan/releases/tag/v0.5.1-alpha.1) ist veröffentlicht. Diese Version bleibt bis zur Abnahme auf einem echten NAS Alpha.

## Lokale Prüfungen

- 1.276 Python-Tests erfolgreich, ein bewusst übersprungener Test. Enthalten sind echte lokale HTTP-Anfragen, Rollen-/CSRF-Grenzen, parallele Prozesssperren, beschädigte Paketkonfigurationen, Container-Identität, Datenbeibehaltung, Start-/Installationsbudgets und aktive VM-Reservierungen.
- Alle 39 JavaScript-Verhaltenssuiten erfolgreich. Die tatsächlichen Aktionshandler warten auf Auftragsabschluss; Fehler, Teilfehler, unterbrochene Abfragen und Zeitüberschreitungen werden sichtbar behandelt.
- Syntax geprüft: 19 Shellskripte, 40 JavaScript-Module und 81 kompilierte Python-Module.
- 21 Tests zur Dateierstellung einschließlich gültiger DOCX/XLSX/ODT/ODS-Dateien, geschützter Systempfade, Symlinks und vorhandener Dateien. Zusätzlich sechs Leseprüfungen mit python-docx und openpyxl.

## Tatsächliche Browserbedienung

Die isolierte Demo nutzt simulierte Container und Ressourcen; sie ist keine Prüfung des eigenen NAS.

- Docker-Paket über die Oberfläche gestoppt und erneut gestartet; der Dienststatus änderte sich erst nach dem tatsächlichen Demo-Auftragsabschluss. Gruppen- und Dienstaktionen besitzen getrennte Schaltflächen. Ergebnisse verdrängen die Arbeitsfläche nicht durch eine zusätzliche große Aktivitätsanzeige.
- Installierte App zum Desktop hinzugefügt und über das Desktop-Menü mit Ja/Nein deinstalliert. Die Verknüpfung verschwand nach erfolgreichem Abschluss; Entfernen einer Verknüpfung bleibt eine eigene Aktion.
- Word-Datei über Dateityp-Auswahl angelegt; der Dateimanager zeigt die echte DOCX-Datei und das verständliche W-Symbol.
- Nextcloud-Formular mit vier Standarddiensten und optionalem Office bedient. Im simulierten 8-GiB-Budget verhindert die Vorprüfung eine Installation mit Office und zeigt den benötigten RAM vor dem Download.
- VM-Details in voller Desktop-Arbeitsfläche und bei 320/390 Pixel Breite bedient. Docker bei 390 Pixel geprüft; Dokumentbreite entspricht der Bildschirmbreite. Screenshotnachweise sind in der README enthalten.
- Keine JavaScript-Konsolenfehler während dieser Browserprüfung.

## Release-Prüfungen auf GitHub

Die [normale CI](https://github.com/ra5on/Titan/actions/runs/37215103204) und die [Debian-Integration](https://github.com/ra5on/Titan/actions/runs/37215103199) für den veröffentlichten Quellcommit `d47a6005` sind erfolgreich abgeschlossen.

Alle vier Paketschritte im [erfolgreichen Release-Workflow](https://github.com/ra5on/Titan/actions/runs/37215103371) haben Immich, AdGuard Home, Pi-hole und Nextcloud/Euro-Office mit echten Containern über den produktiven HTTP-, Auftrags- und Host-Pfad erfolgreich geprüft. Dateiübersichten während der Installation, einzelne Dienste, Paketstop/-start, Deinstallation mit erhaltenen Daten und erneute Installation sind bestanden. Die Dateiübersicht antwortete dabei in ungefähr 0,05 Sekunden. Nextcloud mit sechs Diensten einschließlich Office hat zusätzlich Dokumentabruf, Konvertierung, signiertes Speichern, erhaltene Dateirechte und die Abweisung ungültiger Speicheranfragen bestanden. Ein früherer Prüfweg, der die Host-Validierung umging, wurde ersetzt. Ein vorübergehendes Download-Limit der Immich-Registry wurde durch einen gezielten Wiederholungsdurchlauf überwunden.

Der [erste Systemlauf](https://github.com/ra5on/Titan/actions/runs/37212657203) hat Boot, HTTPS, Administrator-Einrichtung, SMB, einzelne Docker-Apps, eigene Netzwerke, native Docker-Verwaltung und den VM-Lifecycle bestanden. Der importierte Teststack wurde vom RAM-Schutz abgelehnt: Er erbte zweimal 1 GiB Containerlimit und erforderte mit den Reserven volle 3 GiB, die der 3-GiB-Gast nach Kernelbedarf nicht bereitstellen konnte. Die beiden Wegwerf-Testdienste erhalten jetzt ausdrücklich jeweils 512 MiB, wie der bereits erfolgreiche native Test. Neue Regressionen prüfen echten Store-Import, Compose-Limits und frisch gelesene RAM-Messwerte; zu wenig RAM oder zusätzliche laufende Container werden weiterhin abgelehnt. Die produktive RAM-Prüfung wurde nicht abgeschwächt.

RAM-Fehler erhalten im Prüfbericht eine geschlossene Fehlerkategorie. Bei einer fehlgeschlagenen Stack-Installation werden außerdem die Details des betroffenen Teststacks abgefragt; die Diagnose eines zuvor entfernten Einzelcontainers wird nicht mehr fälschlich angehängt.

Der korrigierte signierte Debian-A/B-Build hat Boot, HTTPS, UEFI, authentifizierte VNC-Verbindungen, den Mehrcontainer-Lifecycle und die native Docker-Verwaltung bestanden. Der vollständige Test von der veröffentlichten 0.4.6-Basis prüft Plattenvergrößerung, Vorbereitung des signierten Updates ohne sofortigen Neustart, Aktivierung der neuen Version, manuellen Rollback und Rückfall nach einem absichtlich beschädigten Teststart mit Reset. Benutzerkonten, Freigaberechte, Testdateien und lokale Einstellungen bleiben erhalten; die Ausgangsimages wurden nicht verändert. Alle elf Release-Assets sind hochgeladen, einschließlich des signierten RAUC-Bundles sowie [Laufzeitnachweis](https://github.com/ra5on/Titan/releases/download/v0.5.1-alpha.1/runtime-test.json) und [A/B-Nachweis](https://github.com/ra5on/Titan/releases/download/v0.5.1-alpha.1/ab-test.json). Es ist ein Update für bestehende Installationen; das bisherige IMG bleibt die Installationsbasis.

## Abnahme auf dem eigenen NAS

Auf dem 8-GiB-System Nextcloud zunächst ohne Office testen: Dateimanager während Installation benutzen, Desktop-App öffnen, Paket und einzelne Dienste stoppen, deinstallieren und mit erhaltenen Daten erneut installieren. Das gemeinsame Budget mit laufenden VMs prüfen. Bestehende unbegrenzte Docker-Container müssen vor weiteren Starts ein RAM-Limit erhalten oder gestoppt werden.

Echte Mobilbrowser, längerer Lastbetrieb, USB-/GPU-Geräte, SMB-Clients und tatsächliche Office-Bearbeitung bleiben Teil der [Beta-Abnahme](BETA.md). Die RAM-Prüfung reduziert Überbuchung; außerhalb Titans gestartete Prozesse können weiterhin zusätzliche Last verursachen.
