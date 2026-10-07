# Titan installieren

Das erste Titan-Debian-A/B-Image ist eine **Alpha für eine neue Test-VM**.

[IMG herunterladen](https://github.com/ra5on/Titan/releases/download/v0.5.3-alpha.1/titan-0.5.3-alpha.1-amd64.img.xz) · [Prüfsummen und Testberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.3-alpha.1)

Die Datei entpacken und als Systemplatte einer neuen Proxmox-VM importieren:
x86-64, UEFI/OVMF ohne Secure Boot, 8 GiB RAM, 2 CPUs und mindestens 64 GiB Platte.
Größere Platten erweitern beim Start den Datenbereich. Anschließend
`https://<NAS-IP>:5000` öffnen und den Administrator selbst einrichten.

Diese Adresse gilt für das oben verlinkte veröffentlichte Image. Neue Builds
verwenden `https://<NAS-IP>` auf Port 443; HTTP auf Port 80 leitet automatisch
dorthin weiter. Bestehende Installationen behalten ihren bisherigen Port.
Unter **Systemsteuerung → Allgemein → Webzugriff** kannst du HTTP oder HTTPS
und die Ports ändern; HTTPS schaltet die HTTP-Weiterleitung automatisch ein.

[Ausführliche Anleitung](TITAN-IMAGE.md) · [Updates und Rollback](UPDATES.md)

Nach dieser Neuinstallation kommen weitere kompatible Versionen über den
Alpha-Update-Kanal. Bestehende anderes NAS-Systeme werden nicht automatisch
konvertiert; das Image nicht über deren Datenplatten schreiben.
