# Titan installieren

Das erste Titan-Debian-A/B-Image ist eine **Alpha für eine neue Test-VM**.

[IMG herunterladen](https://github.com/ra5on/Titan/releases/download/v0.4.6-alpha.1/titan-0.4.6-alpha.1-amd64.img.xz) · [Prüfsummen und Testberichte](https://github.com/ra5on/Titan/releases/tag/v0.4.6-alpha.1)

Die Datei entpacken und als Systemplatte einer neuen Proxmox-VM importieren:
x86-64, UEFI/OVMF ohne Secure Boot, mindestens 4 GB RAM, 2 CPUs und 48 GiB Platte.
Größere Platten erweitern beim Start den Datenbereich. Anschließend
`https://<NAS-IP>:5000` öffnen und den Administrator selbst einrichten.

[Ausführliche Anleitung](TITAN-IMAGE.md) · [Updates und Rollback](UPDATES.md)

Nach dieser Neuinstallation kommen weitere kompatible Versionen über den
Alpha-Update-Kanal. Bestehende RaNAS-/uCore-Systeme werden nicht automatisch
konvertiert; das Image nicht über deren Datenplatten schreiben.
