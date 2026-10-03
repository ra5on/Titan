# Plan für die erste Beta

**Titan bleibt Alpha. Die erste Beta ist unser nächstes Entwicklungsziel.** Ein Beta-Label wird erst gesetzt, wenn die Kernabläufe auf einem separaten Proxmox-/NAS-Testsystem bestätigt sind. Mehr App-Vorlagen oder bestandene Mock-Tests allein reichen dafür nicht.

## Ausgangsstand

[Proxmox-Test](PROXMOX-TEST.md): Update, Neustart, Rollback und Erhalt der Nutzdaten auf der aktuellen Debian-Version prüfen.

[Proxmox-Test](PROXMOX-TEST.md): Update, Neustart, Rollback und Erhalt der Nutzdaten auf der aktuellen Debian-Version prüfen.

[Proxmox-Test](PROXMOX-TEST.md): Update, Neustart, Rollback und Erhalt der Nutzdaten auf der aktuellen Debian-Version prüfen.

[Proxmox-Test](PROXMOX-TEST.md): Update, Neustart, Rollback und Erhalt der Nutzdaten auf der aktuellen Debian-Version prüfen.

v0.4.4 hat am **2. Oktober 2026** im [Actions-Lauf 36998515941](https://github.com/ra5on/Titan/actions/runs/36998515941) den Image-Erststart und alle **zehn Laufzeitprüfungen** bestanden. Der geprüfte Source-Stand ist [a228b96fff5f](https://github.com/ra5on/Titan/commit/a228b96fff5f137b04419982feedba6ab38a5331); der [öffentliche Laufzeitbericht](https://github.com/ra5on/Titan/releases/download/v0.4.4/runtime-test.json) enthält die tatsächlichen Ergebnisse. SMB mit unterschiedlichen Benutzerrechten, Docker-App und eigenes Bridge-Netz, VMs mit verfügbarem KVM und Browserkonsolen-Verbindung, CPU/RAM sowie Systemdisk-Erweiterung sind auf diesem Stand erneut bestanden. Die virtuelle Systemdisk wurde von 32 auf 36 GiB vergrößert; Partition und XFS wuchsen jeweils um genau 4 GiB; UUIDs, Partitionsanfang, Testdatei-SHA256 und originales Raw-Image blieben erhalten. Die öffentlichen Manifest-/Prüfsummensignaturen und Asset-Digests wurden nach Veröffentlichung unabhängig geprüft. Der tatsächliche Titan-Updater erkennt v0.4.4 vom simulierten installierten v0.4.3-Stand als verfügbares signiertes Alpha-Update; es wurde dabei kein Update installiert oder Neustart ausgelöst.

Die direkte Textbearbeitung, gespeicherte Menü-Auswahl und unabhängigen Scrollbereiche wurden zusätzlich bei Desktop-, Tablet- und Handybreite in einer isolierten Demo geprüft. Titan bleibt Alpha; die bisher offenen manuellen Betriebsnachweise bleiben erforderlich.

## Bereits belegt und noch offen

| Bereich | Vorhandener Nachweis | Vor der Beta noch zu bestätigen |
| --- | --- | --- |
| Systemstart und Anmeldung | v0.4.4 startet im entbehrlichen QEMU-Gast; HTTPS, Ersteinrichtung und Login bestanden | Installations-IMG in Proxmox; vollständiger Neustart und erneute Anmeldung |
| Docker | v0.4.4: 42 Katalogvorlagen/Anmeldehinweise über die API geprüft. Heimdall im Standardnetz und in einer eigenen Bridge mit fester IPv4 installiert; tatsächliche IP, Gateway und LAN-Endpunkt geprüft, Webseite jeweils vor/nach Stoppen und Starten mit HTTP 200 erreichbar; Test-App/-Netz entfernt | Standard, Bridge/Fest-IP und Host in Proxmox prüfen; alle angebotenen Vorlagen installieren, ersten Zugang und Persistenz prüfen; Update und Sicherung erproben |
| VMs und Konsole | v0.4.4 mit KVM: VM-Anlage/Start/Ausschalten/Entfernen, noVNC-Dateien und authentifizierter WebSocket-/RFB-3.8-Aufbau bestanden. Direkten Image-Pfad als zweite VM kopiert/gestartet; Quellmetadaten unverändert | Ein echtes Gastbetriebssystem installieren; Browserbild, Tastatur/Maus, Neustart und Autostart prüfen; Quelldatei beim Import zusätzlich per Inhaltsvergleich kontrollieren |
| Benutzer, SMB und Dateien | v0.4.4: neuer Administrator als eigener SMB-Benutzer sowie Leser/unberechtigtes Konto mit `smbclient` vom externen Runner geprüft. Schreiben/Lesen und Dateiinhalt, Schreibverweigerung, Verbindungsverweigerung und ausgeblendete private Freigabe bestanden; Testdatei/-freigabe/-konten entfernt. Isolierte Dateiaktionstests vorhanden | Separate Windows-/macOS-/Linux-Clients, Sperren/Löschen aktiver Konten, Rechte nach NAS-Neustart und Dateimanageraktionen prüfen |
| Ext4, XFS und ZFS | Werkzeuge im Image; isolierte Verwaltungs-/Fehlerfalltests vorhanden | Neue Testvolumes, Datenpersistenz nach Neustart, Ausfall eines Mounts, ZFS-Snapshot und Wiederherstellung |
| Systemdisk-Erweiterung | v0.4.4: Echter Image-Gast startet mit 32 GiB; Online-Erweiterung auf 36 GiB vergrößert Partition und XFS um 4 GiB. Partitionsanfang/UUIDs und Testdatei-SHA256 erhalten; Wiederholung wirkungslos; originales Raw-Image unverändert | Unterstützte Systemdisk in Proxmox vor/nach Start vergrößern; reale Partition-/XFS-Kapazität, Testdatei-SHA256 und App-/SMB-Zugriff nach Neustart bestätigen |
| Backup und Restore | Isolierte Archiv-/Validierungs-/Wiederherstellungsprüfungen vorhanden | Echte Dateien mit Inhaltsvergleich, NAS-Konfiguration und ausgeschaltete VM sichern und wiederherstellen |
| Systemupdate und Rollback | Signierte Manifeste, feste OCI-Digests und Staging-Regeln getestet. v0.4.4-Gast: live gelesener Erststartstatus ohne vorherige Rollback-Version; falsche Rollback-/Neustartbestätigungen mit HTTP 400 und unverändertem Zustand zurückgewiesen | Neueres signiertes Image über die Weboberfläche vorbereiten, kontrolliert neu starten und zur vorherigen OS-Version zurückkehren; Daten danach prüfen |
| Metriken und Bedienung | v0.4.4: reale CPU-Intervall-/RAM-Werte im Image-Gast geprüft; keine Temperatursensoren in dieser VM vorhanden. Desktop-/Mobil-UI-Prüfungen vorhanden | Werte gegen Testsystem vergleichen; vorhandene Sensoren, Browserdiagramme, Uhr, Dienste und Aufträge im Betrieb kontrollieren |
| Dauerbetrieb und Hardware | Kein vollständiger dokumentierter Dauerlauf als Beta-Nachweis vorhanden | Mindestens 24 Stunden Testbetrieb; reale Laufwerke/Sensoren auf passender Hardware prüfen |

**Offen** bedeutet, dass hier noch kein vollständiger Betriebsnachweis dokumentiert ist. Es bedeutet nicht, dass eine Funktion zwangsläufig defekt ist. Ein Test ohne Nested-KVM bleibt beim VM-Nachweis **übersprungen** und zählt dort nicht als bestanden.

## Reihenfolge der Freigabeprüfungen

1. **Update, Neustart und Rollback:** Auf einem separaten Proxmox-System das geprüfte Installations-IMG verwenden beziehungsweise das vorhandene Testsystem fortführen. Ein neueres signiertes Alpha-Update vorbereiten, laufenden Betrieb ohne automatischen Neustart bestätigen, über den Titan-Neustartdialog kontrolliert neu starten und über die Rollback-Bedienung zur vorherigen OS-Version zurückkehren. UID/GID, Daten, Datenbank und Freigaben nach beiden Starts prüfen. Die installierte Startversion braucht dafür erst ein späteres signiertes Update. Daten unter `/var` werden durch einen OS-Rollback nicht zurückgesetzt. Keine vorhandenen produktiven NAS-Daten verwenden.
2. **Apps und Dienste:** Installationsdialoge, Standard-/Bridge-/Host-Auswahl, feste Container-IP, tatsächliche Zugriffsadressen, Speicherauswahl, echte App-Seiten und erste Anmeldung prüfen. Netz/IP müssen nach App- und NAS-Neustart erhalten bleiben; belegte oder überlappende Netze müssen verständlich blockiert werden. Anfangspasswörter ändern; Stoppen/Starten, Neustart und Dienstaufträge kontrollieren. Alle für die Beta angebotenen Vorlagen brauchen einen eigenen einfachen Installations-/Zugriffsnachweis. Umfangreiche App-Funktionen wie externe Anbieter und kostenpflichtige Konten werden separat ausgewiesen.
3. **SMB und Speicher:** Mindestens zwei Benutzer mit unterschiedlichen Rechten, separater SMB-Client und neue Ext4-/XFS-/ZFS-Testlaufwerke. Nach Neustart müssen Daten und Rechte erhalten bleiben. Die Systemdisk ab v0.4.3 in Proxmox vor/nach Start vergrößern; automatische und manuelle Erweiterung, Dateiinhalt und Zugriffe nach einem weiteren Neustart prüfen.
4. **Echte VM:** Gastbetriebssystem aus einem Installationsimage einrichten und über die Browserkonsole bedienen. Disk-/CPU-Auswahl, Autostart und persistente Gastdaten prüfen.
5. **Wiederherstellung:** Testdateien, NAS-Konfiguration und ausgeschaltete VM sichern und tatsächlich wiederherstellen. Inhalt/Hashes beziehungsweise Gaststart überprüfen. Ein erzeugtes Archiv allein genügt nicht.
6. **Erststart und Persistenz:** Auf einer neuen entbehrlichen Systemdisk den letzten Installationsdownload prüfen: DHCP, HTTPS auf Port 5000 und Ersteinrichtung. Danach über den Update-Kanal auf den konkreten Kandidaten wechseln und Anmeldung, Speicherzuordnung, Apps und Dienste nach erneutem Neustart prüfen.
7. **Dauerlauf und Bedienung:** Mindestens 24 Stunden Betrieb mit Apps und VM. Desktop/Mobilgerät, Metriken, Temperaturverfügbarkeit, Ordnerauswahl, Dienste, Aufträge und Fehleranzeigen prüfen.

Details und Testbedingungen stehen im [Testplan](TESTING.md). Virtuelle Datenlaufwerke eignen sich für Speicher-/SMB-Abläufe. SMART, reale Temperaturen und P-/E-Kern-Erkennung brauchen passende physische Hardware; solche Einschränkungen müssen im Beta-Bericht sichtbar bleiben.

## Wann wir Beta veröffentlichen

- Der konkrete signierte OCI-Kandidat besteht die Source-/UI-Prüfungen und seinen eigenen Start-/Laufzeittest auf der internen CI-Testdisk; ein öffentliches Installations-IMG ist dafür nicht erforderlich.
- Die oben genannten Kernabläufe haben dokumentierte reale Ergebnisse. Kritische Fehler bei Start, Zugriff, Datenrechten, Wiederherstellung oder Update/Rollback sind behoben.
- Der App Store erklärt die ersten Zugänge korrekt, verwendete Ports und benötigte Einstellungen sind verständlich, und die für Beta angebotenen Apps haben eigene Installations-/Zugriffsnachweise.
- Häufige Abläufe funktionieren über Auswahllisten und Ordnerbrowser; fehlende Hardware oder Berechtigungen erscheinen als verständliche Zustände.
- Versionsnummer, Entwicklungsstand und Release-Notizen stimmen überein. Verbleibende Einschränkungen werden mit Testumgebung und fehlendem Nachweis genannt.

## Testbericht

Pro Ergebnis verwenden wir folgende Angaben:

```text
Titan-Version / OCI-Digest:
Datum / Tester:
Proxmox-Version oder NAS-Hardware:
CPU / Nested-KVM / RAM / Laufwerke / Netzwerk:
App-Version oder Gastbetriebssystem:
Prüfung und erwartetes Ergebnis:
Beobachtung und Nachweis:
Status: bestanden | fehlgeschlagen | übersprungen | offen
Offene Fehler / reproduzierbare Schritte:
```

Keine echten Passwörter, API-Schlüssel oder persönlichen Dateien veröffentlichen. Der Bericht muss Source-Tests, automatische Gasttests, manuelle Proxmox-Tests und physische Hardwaretests auseinanderhalten. Die Ergebnisse entscheiden über die Beta-Freigabe.


v0.4.5 hat am **2. Oktober 2026** im [Actions-Lauf 37034137762](https://github.com/ra5on/Titan/actions/runs/37034137762) den Image-Erststart und alle **zehn Laufzeitprüfungen** bestanden. Der geprüfte Source-Stand ist [67e5fab51b7a](https://github.com/ra5on/Titan/commit/67e5fab51b7afdad3dd4782c93b6596a43caf3e1); der [öffentliche Laufzeitbericht](https://github.com/ra5on/Titan/releases/download/v0.4.5/runtime-test.json) dokumentiert die tatsächlichen Ergebnisse. Geprüft wurden Administrator-Ersteinrichtung, App-Katalog/Anmeldung, Update-Zustand, CPU/RAM, Systemdisk-Erweiterung, SMB mit mehreren Benutzerrechten, installierte Komponenten, Docker-App mit Standard- und eigenem Bridge-Netz sowie VM-Lebenszyklus und authentifizierte Browserkonsolen-Verbindung mit RFB 3.8. Die Systemdisk wuchs von 32 auf 36 GiB; Partition und XFS wuchsen um genau 4 GiB, während Partitionsanfang, UUIDs, Testdatei-SHA256 und originales Raw-Image erhalten blieben. Wiederholungen waren wirkungslos. Die öffentlichen Manifest-/Prüfsummensignaturen und sämtliche Asset-Digests wurden unabhängig überprüft. Der tatsächliche Titan-Updater erkennt v0.4.5 vom simulierten installierten v0.4.4-Stand als verfügbares signiertes Alpha-Update; dabei wurde weder ein Update installiert noch ein Neustart ausgelöst.

Die VM-Prüfung bestätigt Definition, Start, Stop, Laufwerksimage-Kopie und Browserkonsolen-Verbindung. Ein installiertes Gastbetriebssystem, grafische Eingabe und der vollständige OS-Update-/Neustart-/Rollback-Zyklus bleiben manuell zu prüfen; die neue Oberfläche allein begründet keine Beta-Freigabe.
