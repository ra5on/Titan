# Titan auf Debian 13 – erstes Proxmox-Testimage

**Entwicklungsvorschau, nur in einer separaten VM mit Testdaten verwenden.**
Das Image enthält Debian 13 und Titan samt Docker/Compose, QEMU/libvirt, noVNC,
Samba und ext4/XFS-Werkzeugen. Die Benutzeroberfläche meldet „DEBIAN · PREVIEW“.

**Systemupdates, A/B-Rollback und die Übernahme einer bestehenden uCore-Installation
sind noch nicht verfügbar.** Der spätere A/B-Unterbau kann eine Neuinstallation
verlangen. Dieses Image wird nicht über den normalen Titan-Update-Kanal verteilt.
ZFS ist in dieser ersten Debian-Vorschau noch nicht eingerichtet.

## Proxmox

1. `.img.xz` und `SHA256SUMS` herunterladen, Prüfsumme vergleichen und mit
   `unxz titan-debian-preview-20261002-amd64.img.xz` entpacken.
2. Eine neue VM erstellen: **q35, OVMF (UEFI), EFI-Disk ohne vorinstallierte
   Secure-Boot-Schlüssel, CPU host, 4 vCPU, 4–8 GB RAM, VirtIO-Netzwerkkarte** an
   deiner LAN-Bridge. Für VMs im NAS muss Nested-Virtualisierung verfügbar sein.
3. Das entpackte Image als Festplatte importieren. Beispiel auf dem Proxmox-Host
   (VM-ID und Speicher anpassen):

   ```sh
   qm disk import 120 titan-debian-preview-20261002-amd64.img local-lvm
   ```

4. In der VM-Hardware die importierte „Unused Disk“ als SCSI-Laufwerk einbinden,
   VirtIO-SCSI-Controller verwenden und diese Disk in der Boot-Reihenfolge aktivieren.
   Die Disk hat zunächst 16 GB; vor dem ersten Start nach Bedarf auf 32 GB oder mehr
   vergrößern. Der Debian-Starthelfer erweitert die ext4-Systempartition.
5. VM starten. Die Adresse kommt automatisch per DHCP; QEMU Guest Agent ist enthalten.
   Die Proxmox-Konsole zeigt die IP. **Kein Cloud-init-Laufwerk erforderlich.**
6. `https://<IP>:5000` öffnen und das erste Administratorkonto selbst anlegen.
   Das lokale HTTPS-Zertifikat ist selbst ausgestellt. Es gibt kein vorgegebenes
   Kennwort und keinen aktivierten SSH-Zugang.

## Testumfang und Grenzen

Die Veröffentlichung setzt einen echten UEFI-Erststart mit erreichbarem HTTPS und
initialer Einrichtung voraus. Der Laufzeitbericht `runtime-test.json` nennt jeden
geprüften bzw. übersprungenen Punkt. Er umfasst Einrichtung/Login, CPU/RAM,
Komponenten, SMB und Docker; VM-Start wird nur bei vorhandenem Nested-KVM geprüft.
Ein installiertes Gastbetriebssystem, physische Datenträger, Langzeitbetrieb und
Update-/Rollback-Zyklen sind damit nicht nachgewiesen.

Die Basis ist ein festgelegtes offizielles Debian-Generic-Image. Dessen SHA512 wurde
über HTTPS aus der offiziellen Prüfsummenliste übernommen und ist im Quellcode
festgelegt. Dieses Debian-Verzeichnis veröffentlicht keine separate Signatur;
wir behaupten daher keine Debian-GPG-Verifikation. Titan signiert seine eigenen
Prüfsummen mit dem bestehenden Release-Schlüssel.

Bitte zuerst Oberfläche, Freigaben, App-Installation und anschließend eine Test-VM
prüfen. Bei Problemen sind der genaue Fehler und die Proxmox-VM-Einstellungen hilfreich.
