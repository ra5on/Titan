# Titan 0.5.3 Alpha · Eigenbau mit BigBear

Neues Debian-Image mit Titan-Desktop, Dateimanager, SMB-Freigaben, Speicherverwaltung, KVM/libvirt und Docker-Stacks.

Im AppStore den BigBear-Katalog aktivieren. Vorlagen übernehmen Ports und Abhängigkeiten; Speicher, Zugangsdaten, Netzwerk und erkannte Geräte lassen sich vor der Installation wählen. Eigene Titan-App-Angebote werden nicht mehr bereitgestellt. Bestehende Installationen behalten ihre Daten und bleiben verwaltbar.

Das Image enthält zwei Systempartitionen für signierte Updates und Rollback. Für diese erste Veröffentlichung werden Installation, Update, Rollback und Fehlerfallback auf einer separaten Testkopie dieses Builds geprüft. Eine Migration von früheren veröffentlichten Images wird damit nicht zugesichert.

Das komprimierte `.img.xz` entpacken und das `.img` auf den gewünschten Datenträger schreiben bzw. als virtuelle Festplatte importieren. Beim Schreiben werden die bisherigen Daten auf dem Ziel überschrieben. Der Datenbereich kann den verbleibenden Speicher nutzen; die Systempartitionen bleiben separat. Das entpackte Image ist 48 GiB groß. Für den Start UEFI verwenden (in Proxmox OVMF). Für Docker-Stacks 8 GiB RAM empfehlen. Für eine VM mindestens 64 GiB virtuelle Festplatte vorsehen und diese vor dem Start passend vergrößern.

Nach dem Start die NAS-Adresse auf Port 5000 öffnen und ein Administratorkonto einrichten. Checksummen, signierter Update-Bundle und Prüfberichte liegen dem Release bei.

**Alpha: zunächst mit Testdaten verwenden.** Nested KVM, Geräte-Passthrough und die Bedienung auf deiner Hardware bleiben Teil der praktischen Abnahme.
