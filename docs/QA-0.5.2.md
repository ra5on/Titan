# Prüfnachweis · Titan 0.5.2 Alpha

Stand: 4. Oktober 2026. Implementierung, lokale Regressionen, Browserprüfung, GitHub-CI, Debian-Integration und alle vier echten App-Pakettests sind bestanden. Der signierte Systembuild, die echte NAS-Gastprüfung sowie Update, Rollback und Rückfall von der veröffentlichten Basis sind bestanden. **[0.5.2-alpha.1 ist veröffentlicht](https://github.com/ra5on/Titan/releases/tag/v0.5.2-alpha.1).** Titan bleibt bis zur Abnahme auf dem eigenen NAS Alpha.

## Lokale Prüfungen

- Die vollständige Python-Suite hat lokal vor der zusätzlichen Änderung am Live-Smoke-Test 1.286 Tests erfolgreich ausgeführt, mit einem bewusst übersprungenen Test. Die GitHub-CI des endgültigen Quellstands hat anschließend die Suite mit 1.290 Tests erfolgreich ausgeführt; ein Test wurde bewusst übersprungen. Sie umfasst API- und Berechtigungsprüfungen, Docker-Verwaltung, RAM-Budgets, VM-Funktionen und Speicheroperationen.
- Alle 43 JavaScript-Verhaltenssuiten und die JavaScript-Syntax sind nach den letzten Layoutkorrekturen erneut erfolgreich geprüft. Darunter: gespeicherte Dateimanager-Seitenleiste, VM-Auswahl und Details, Docker-Bereiche und Netzwerkaktionen sowie Speicherübersicht, Bereichsauswahl und mobile Dropdowns.
- Nach der zusätzlichen Live-Smoke-Änderung sind die 86 gezielten Smoke-Test-Regressionen erfolgreich. Der anschließende NAS-Gastlauf hat auch die erweiterte Netzwerkprüfung tatsächlich ausgeführt und bestanden.
- Die Speicher-Tests sichern insbesondere zu: Nur gemessene aktive Bereiche liefern Übersichtskapazität; ZFS-Datasets werden nicht zum Pool addiert. Offline-Volumes bleiben mit der Verbinden-Aktion sichtbar. SMART wird über die echte API angefragt. Navigation, Tastaturwechsel, Ja/Nein-Bestätigung und Aufräumen geschlossener Ansichten sind geprüft.
- Netzwerk-Regressionen prüfen automatische Subnetzwahl, Überschneidungen, Namenskonflikte, Auftragsabschluss sowie Schutz vor Entfernen verwendeter, fremder oder eingebauter Netze.

## Tatsächliche Browserbedienung

Die isolierte Demo verwendet simulierte Container, Laufwerke und Ressourcen. Die Prüfung bestätigt Bedienung und Layout; reale Operationen werden getrennt im Release-Gast getestet.

- Dateimanager: Seitenleiste tatsächlich mit der Maus von 208 auf 308 Pixel gezogen, nach Neuladen erhalten, rechts platziert, ausgeblendet und erneut geöffnet. Standardbreite per Doppelklick. Eigene SVG-Ortssymbole sind sichtbar. Die mobile Schublade öffnet und schließt; nach Scrollen durch 45 Testdateien bleiben Werkzeugleiste und Auswahlaktionen einschließlich Löschen erreichbar. Dokumentbreite 390 Pixel.
- VMs: Desktop-Aufteilung mit 148 Pixel breiter Navigation, Maschinenliste und Details. Hardware, Zurück zur Liste und erneute Auswahl bedient. Mobil bei 390 Pixel werden Liste und Details einzeln angezeigt. Der Konsolenbereich verwendet bei 1366 Pixel die volle Breite und 706 Pixel Inhaltshöhe; echte VNC ist in der Demo absichtlich deaktiviert.
- Docker: Projekte und Netzwerke bedient. Ein Wegwerf-Bridge-Netz ausschließlich mit Namen erstellt; Subnetz/Gateway erscheinen nach abgeschlossenem Auftrag. Löschen zunächst mit Nein abgebrochen, danach mit Ja bestätigt und tatsächliches Verschwinden aus dem Inventar geprüft. Systemnetz bleibt geschützt. Mobile Dokumentbreite 390 Pixel.
- Speicher: Übersicht, Speicherbereiche, HDD/SSD und Wartung geöffnet, SMART-Zustand über den Dialog gelesen. Nach Beseitigung einer alten CSS-Kollision nutzt der Inhalt bei 1366 Pixeln die gesamten 1182 Pixel neben der Navigation und beginnt direkt unter der Werkzeugleiste. Mobil bei 320/390 Pixeln kein Dokumentüberlauf.
- Alle elf Bereiche der Systemsteuerung bei 320 und 390 Pixeln durchlaufen: Freigaben, Benutzer, Gruppen/Rechte, Allgemein, Sicherheit, Updates/Rollback, Systemzustand, Komponenten, Dienste, Datensicherung und Protokoll. Dokumentbreite entsprach jeweils der Bildschirmbreite. AppStore, installierte Apps und Ressourcenmonitor ebenfalls bei schmaler Breite geprüft.
- Historische VM-Regeln in den allgemeinen Stylesheets sind auf den früheren Docker-Manager beschränkt; die Speicheranwendung verwendet einen eigenen Inhaltsklassennamen. Betroffene UI-Suiten nach diesen Korrekturen erneut erfolgreich.
- Keine JavaScript-Konsolenwarnungen oder -fehler während der Browserprüfung. Neue Screenshots in der README zeigen ausschließlich die Demo.

## GitHub- und Release-Prüfungen

| Prüfung | Stand |
| --- | --- |
| Quellstand auf GitHub / normale CI | [f8468130](https://github.com/ra5on/Titan/commit/f84681309d10d3323ed248540d35f4a57a31254a) / [Bestanden](https://github.com/ra5on/Titan/actions/runs/37225830083) |
| Debian-Integration | [Bestanden](https://github.com/ra5on/Titan/actions/runs/37225830054) |
| Immich, AdGuard Home, Pi-hole, Nextcloud/Euro-Office mit echten Containern | Alle vier [bestanden](https://github.com/ra5on/Titan/actions/runs/37225830197) |
| Signierter Debian-A/B-Systembuild | [Bestanden](https://github.com/ra5on/Titan/actions/runs/37225830197) |
| NAS-Testgast: Boot, HTTPS, SMB, Docker-Netze, App-/Containeraktionen und VM-Konsole | [Bestanden](https://github.com/ra5on/Titan/releases/download/v0.5.2-alpha.1/runtime-test.json) |
| Update von veröffentlichter Basis, Aktivierung, manueller Rollback und automatischer Rückfall | [Bestanden](https://github.com/ra5on/Titan/releases/download/v0.5.2-alpha.1/ab-test.json) |
| Release-Assets und signiertes Updateangebot im Alpha-Kanal | Veröffentlicht und unabhängig verifiziert |

Die Pakettests dieser Version haben echte HTTP-/Auftrags-/Host-Aktionen, Dateiübersichten während der Installation, Einzelcontainer- und Paketstop/-start, Deinstallation mit erhaltenen Daten und erneute Installation bestanden. Dateiübersichten antworteten während der Installation in 0,041–0,052 Sekunden. Nextcloud mit sechs Diensten einschließlich Office hat zusätzlich Dokumentabruf, echte Engine-Konvertierung, signiertes Speichern, erhaltene Dateirechte, Ablehnung ungültiger Speicheranfragen und erhaltenes ODT-Format bestanden.

Der vollständige Release-Lauf [37225830197](https://github.com/ra5on/Titan/actions/runs/37225830197) ist erfolgreich abgeschlossen. Ergebnisse der vorherigen veröffentlichten Version stehen getrennt in [QA-0.5.1](QA-0.5.1.md).

## Veröffentlichte Nachweise und unabhängige Prüfung

Der öffentliche [Runtime-Nachweis](https://github.com/ra5on/Titan/releases/download/v0.5.2-alpha.1/runtime-test.json) enthält elf bestandene Prüfungen. Der darin übersprungene ältere Wachstumstest wird durch den separaten A/B-Test abgedeckt. Eigene Docker-Netze wurden tatsächlich über API, Auftrag und Host erzeugt: sowohl mit expliziter Adresse als auch ausschließlich mit Namen. Live-ID, privates Subnetz und Gateway, fehlende Überschneidung mit vorhandenen Netzen/Host-Routen sowie Entfernen sind bestanden. SMB hat getrennte Schreib-, Lese- und unberechtigte Konten geprüft. Die VM-Prüfung umfasst Start/Stop, UEFI-Wechsel, Namenswiederverwendung, Image-Kopie und authentifizierten VNC/RFB-Verbindungsaufbau.

Der öffentliche [A/B-Nachweis](https://github.com/ra5on/Titan/releases/download/v0.5.2-alpha.1/ab-test.json) enthält acht bestandene Prüfungen. Ausgangspunkt war das veröffentlichte **0.4.6-alpha.1**-Image. Proxmox-artige Datenplattenvergrößerung, signierte Vorbereitung ohne automatischen Neustart, Aktivierung, manueller Rollback, slotabhängige Werkseinstellungen und Rückfall nach einem absichtlich beschädigten Start sind bestanden. Benutzer, Freigaberechte und Testdateien blieben erhalten; Ausgangs- und Kandidatenimage wurden nicht verändert.

Nach der Veröffentlichung wurden unabhängig alle elf Release-Assets und der Tag geprüft. Tag und signiertes Manifest nennen exakt den getesteten Quellstand `f84681309d10d3323ed248540d35f4a57a31254a`. Die Ed25519-Signaturen von Manifest und Prüfsummenliste stimmen mit dem im Repository hinterlegten öffentlichen Schlüssel überein; alle acht signierten Dateiprüfsummen stimmen. Der 878.093.627 Byte große RAUC-Download hat in GitHub, signiertem Manifest und signierter Prüfsummenliste denselben SHA-256-Wert `0491f3fa69401d9731802a3ce3f508b707954ca4e35aed6b0a6127403cb0db25`. Die kleinen Assets wurden erneut öffentlich geladen; das große Bundle wurde anhand des GitHub-Asset-Digests geprüft und nicht ein zweites Mal heruntergeladen.

Die tatsächliche `debian_updates.check`-Logik wählt aus der öffentlich beobachteten Release-Liste 0.5.2 als neuestes Alpha-Angebot gegenüber 0.5.1 und bestätigt dessen Signatur. Dafür wurde ausschließlich ein gesunder NAS-Zustand ohne ausstehenden Neustart simuliert; es wurde kein NAS verändert. Der Kontenvertrag ist gegenüber dem ebenfalls signaturgeprüften 0.5.1-Manifest unverändert.

Die Gastprüfungen liefen in GitHub Actions und wurden für die unabhängige Assetprüfung nicht erneut lokal ausgeführt. Die VNC-Prüfung bestätigt Protokollverbindung und noVNC-Dateien; sie bootet kein installiertes Gastbetriebssystem und automatisiert nicht die Canvas-Ausgabe im Browser. Der allgemeine ältere Update-Hinweis im Runtime-Nachweis wird für diese Version durch den tatsächlich ausgeführten separaten A/B-Nachweis ergänzt.

## Abnahme auf dem eigenen NAS

Die Beta-Entscheidung benötigt den Test des Nutzers auf dem realen System. Besonders wichtig sind:

1. Auf dem 8-GiB-NAS die RAM-Anzeige und verfügbare Kapazität unter gleichzeitiger App- und VM-Nutzung beobachten. Nextcloud zunächst ohne Office verwenden; eine abgewiesene Installation darf Dateizugriffe nicht blockieren.
2. Netzwerk erstellen, in einem Container oder App-Paket auswählen und die Adresse prüfen. Entfernen muss bei vorhandenen Zuordnungen verhindert werden und nach deren Auflösung mit Ja/Nein funktionieren.
3. Eine VM starten, die Browserkonsole ohne zusätzliche Tastenkombination öffnen, stoppen und erneut öffnen. Unterschiedliche Gastauflösungen und Mobilgeräte testen.
4. Dateimanager-Seitenleiste ziehen, Seite wechseln, erneut öffnen und auf einem echten Mobilbrowser prüfen. Dateien und Ordner weiter erstellen, bearbeiten, kopieren, verschieben und bestätigt löschen.
5. Tatsächliche Laufwerke, Belegung und SMART-Werte mit dem Host vergleichen. Vergrößerung, Formatierung und Wiederherstellung nur mit geeigneten Testdaten und unabhängiger Sicherung prüfen.

Echte USB-/GPU-Geräte, SMB-Clients, längerer Lastbetrieb und Office-Bearbeitung bleiben Bestandteile der [Beta-Abnahme](BETA.md). Ein Betriebssystem-Rollback setzt Nutzdaten und App-Datenbanken nicht zurück.

## Grundlage für die Anordnung

Die Speicher-Navigation orientiert sich an der dokumentierten Aufteilung von DSM in Übersicht, Speicher und HDD/SSD; Titan ergänzt seine bestehenden Wartungsfunktionen und unterstützt weiterhin Ext4, XFS und ZFS. Quellen: [Synology Storage Manager](https://kb.synology.com/index.php/en-uk/DSM/help/DSM/StorageManager/StorageManager_desc?version=7), [Synology Speicherverwaltung](https://www.synology.com/de-de/dsm/7.4/software_spec/storage_management).
