# Titan 0.4.14-alpha.1

Titan vereinfacht das Dashboard, den AppStore sowie Speicher- und Systemupdates. Der eigene AppStore enthält lokal gepflegte Installationsvorlagen für 73 Apps. Container-Images stammen weiterhin von ihren jeweiligen Herausgebern; externe AppStore-Kataloge und Dockhand werden nicht eingebunden.

- **Anpassbare Oberfläche:** Kachelinhalte fließen mit ihrer Breite, Systemressourcen zeigen kompakte Live-Werte und aufklappbare RAM-Details. Kein festes Inhaltsfenster mit abgeschnittenen Werten. Mobile Ansichten bleiben innerhalb des Bildschirms; komponenteninterne Tabellen/Tabs können weiterhin horizontal scrollen. Lokale App-Bildsymbole, Hover- und Öffnungseffekte respektieren reduzierte Bewegung.
- **Container-Aktionen:** Klick auf den Namen öffnet ein direktes Aktionsmenü neben der Übersicht, auf dem Handy darüber. App öffnen, Einstellungen, Start/Stop/Neustart, Logs und weitere Aktionen sind zusammen erreichbar. Bei Titan-Apps wird der tatsächliche Webport statt eines beliebigen veröffentlichten TCP-Ports benutzt.
- **Eigener AppStore:** Vorlagen werden gemeinsam mit Titan aktualisiert, ohne externe Katalogabfrage. Bereits installierte ältere Store-Apps bleiben verwaltbar; fremde Quellen können nicht mehr neu über die Oberfläche hinzugefügt werden. Port, Netzwerk, Datenbereich, Zugang und Geräte lassen sich vor Installation einstellen.
- **Erkannte Geräte:** USB-Hersteller, Modell und verfügbare Seriennummer; tatsächliche Grafik-/Compute-Geräte, NVIDIA mit betriebsbereiter Runtime sowie NPU-Geräte unter /dev/accel. Mehrfachauswahl erlaubt zum Beispiel Intel-Grafik plus NPU. Die App muss diese Beschleunigung unterstützen; nicht vorhandene Treiber werden nicht vorgetäuscht.
- **Geräte bearbeiten:** Gestoppte Titan-Apps können ihre Gerätezuordnung ändern und werden anschließend gezielt gestartet. Bei Titan-eigenen manuellen Containern mit unterstützter Konfiguration bleibt ein gestoppter Backup-Container erhalten; eine lokale Kopie einschließlich beschreibbarer Dateischicht nutzt dasselbe Datenvolume. Fremde oder individuell komplexer konfigurierte Container werden nicht automatisch umgebaut.
- **Updates und Rollback:** Jetzt prüfen, Update installieren und Neu starten & aktivieren stehen zusammen als drei Schritte. Unpassende Schritte bleiben deaktiviert. Kanal und automatische Suche liegen in aufklappbaren Einstellungen; Rollback bleibt direkt darunter erreichbar.
- **Speicher:** Systemplatte mit Belegt/Frei wird zuerst gezeigt. Tatsächlich eingerichtete Ext4-, XFS-Volumes und ZFS-Pools erscheinen gemeinsam als Datenbereiche. Ein Assistent führt zur Dateisystem- und Laufwerkswahl. Leere Zusatzbereiche liefern keine erfundenen Metriken; technische Angaben sind aufklappbar. ZFS-Pools bleiben echte Laufwerksverbünde und werden nicht als bloße Formatierung eines Volumes behandelt.

## Update

Einstellungen → Update / Rollback → Alpha-Kanal → Jetzt prüfen → Update installieren → Neu starten & aktivieren. Das signierte Debian-A/B-Systemupdate ersetzt keinen persistenten App-Datenbereich. Ein neuer IMG-Import ist nicht nötig.

## Prüfung und Grenzen

Freigabe erst nach Regressionen und echtem Debian-QEMU-Test mit Docker-Neuanlage samt Backup, App-Gerätewechsel, VM/UEFI/VNC, Speichererweiterung sowie signiertem A/B-Update und Rollback. Responsive Browserprüfung umfasst 320 Pixel und Desktop. Physische USB-, GPU- und NPU-Geräte und echte Smartphones stehen dem QEMU-Test nicht zur Verfügung. Weiterhin Alpha; Treiberinstallation und freie Compose-Bearbeitung bleiben separate Aufgaben.
