# Titan 0.5.4 Alpha

Dieses Debian-Image verbessert die Docker-Verwaltung, den App-Katalog und die Bedienung auf kleinen Bildschirmen. **Titan bleibt Alpha: zunächst in einer separaten Test-VM und mit Testdaten verwenden.** Eine Beta-Freigabe oder vollständige Funktionsprüfung aller Katalog-Apps ist damit nicht verbunden.

## Neu und verbessert

- Kompaktere Weboberfläche für Mobilgeräte und Desktop: besser genutzter Fensterplatz, aufgeräumter AppStore, Dateimanager und Systemeinstellungen.
- BigBear wird beim ersten Start automatisch im Hintergrund geladen und lokal gespeichert. Beim geprüften Katalogstand sind **371 von 463 Vorlagen importierbar**; **92 Vorlagen** werden mit konkretem Grund nicht zur Installation angeboten. Importierbar bedeutet nicht, dass jede Anwendung vollständig im Betrieb getestet wurde. Installierte Stacks behalten ihre gespeicherte Vorlage.
- Docker unterscheidet zwischen einem laufenden Container und einer tatsächlich erreichbaren Weboberfläche. Startzustand und Fehler werden angezeigt; Stoppen und Deinstallieren bleiben auch für beschädigte Pakete möglich. App-Daten bleiben bei der Deinstallation erhalten. Benötigte Host-Ports erhalten verwaltete Firewallregeln für erkannte private LAN-Netze.
- Administratoren können einen zeitlich begrenzten Root-Modus für Systemdateien und Terminal aktivieren. Er verlangt die erneute Anmeldung mit Passwort und gegebenenfalls dem zweiten Faktor; die Freigabe endet automatisch.
- Neue Installationen verwenden **HTTPS auf Port 443**. HTTP auf Port 80 leitet automatisch dorthin weiter. Unter **Systemsteuerung → Allgemein → Webzugriff** lassen sich Protokoll und Ports ändern. Die neue Adresse muss innerhalb von **120 Sekunden** bestätigt werden; andernfalls stellt Titan die vorherige Einstellung wieder her. Updates behalten bestehende Webports, beispielsweise Port 5000.

## Neues Image installieren

Die `.img.xz` entpacken und das enthaltene `.img` auf den gewünschten Datenträger schreiben oder als VM-Festplatte importieren. **Das Schreiben überschreibt vorhandene Daten auf dem Ziel.**

Für Proxmox: **UEFI/OVMF**, Secure Boot deaktiviert, **8 GiB RAM** und mindestens **64 GiB virtuelle Festplatte** verwenden. Das entpackte Image ist **48 GiB** groß; die virtuelle Platte **vor dem ersten Start** entsprechend vergrößern. Titan erweitert seinen Datenbereich auf den verfügbaren Platz. Für virtuelle Maschinen innerhalb von Titan muss verschachtelte Virtualisierung verfügbar sein.

Nach dem Start `https://<NAS-IP>` öffnen; der Standardport ist 443. Das lokale Zertifikat ist selbstsigniert. Den Administrator direkt im eigenen Netz einrichten; es gibt kein vorgegebenes Kennwort.

## Bestehendes Titan aktualisieren

Unter **Updates & Rollback** den **Alpha-Kanal** auswählen, nach Updates suchen und das signierte **RAUC-Systemupdate** installieren. Titan prüft die Signatur und schreibt den inaktiven Systembereich; anschließend den Neustart ausdrücklich bestätigen. Das Update umfasst Titan und die Debian-Systempakete. Ein vorhandener bestätigter Systemstand kann über das Rollback-Menü ausgewählt werden.

Ein System-Rollback setzt gemeinsame App-Daten nicht zurück. Ältere Titan-Versionen zeigen neu eingeführte Stack-Funktionen gegebenenfalls nicht an. Unabhängige Sicherungen behalten. Änderungen am gemeinsamen EFI-/GRUB-Bereich oder Partitionslayout benötigen weiterhin ein neues Installationsimage.

Prüfsummen, signiertes Updatepaket und verfügbare Prüfberichte gehören zu den Release-Dateien. Geräte-Passthrough, verschachtelte Virtualisierung und die Bedienung auf der eigenen Hardware bleiben Teil der praktischen Abnahme.
