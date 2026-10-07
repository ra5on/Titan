# Titan installieren

Das Titan-Debian-A/B-Image ist eine **Alpha für eine neue Test-VM**.

[IMG herunterladen](https://github.com/ra5on/Titan/releases/download/v0.5.4-alpha.1/titan-0.5.4-alpha.1-amd64.img.xz) · [Prüfsummen und Testberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.4-alpha.1)

Die Datei entpacken und als Systemplatte einer neuen Proxmox-VM importieren:
x86-64, UEFI/OVMF ohne Secure Boot, 8 GiB RAM und 2 CPUs. Das entpackte Image ist
48 GiB groß; die virtuelle Festplatte vor dem ersten Start auf mindestens
64 GiB beziehungsweise die gewünschte Kapazität vergrößern. Titan erweitert beim
Start den Datenbereich. Anschließend `https://<NAS-IP>` öffnen und den
Administrator selbst einrichten.

Neuinstallationen verwenden HTTPS auf Port 443; HTTP auf Port 80 leitet
automatisch dorthin weiter. Das lokale TLS-Zertifikat ist selbstsigniert.
Bestehende Installationen behalten bei einem Update ihren bisherigen Port.
Unter **Systemsteuerung → Allgemein → Webzugriff** kannst du HTTP oder HTTPS
und die Ports ändern; HTTPS schaltet die HTTP-Weiterleitung automatisch ein.
Die neue Adresse innerhalb von **120 Sekunden** bestätigen, andernfalls wird
die bisherige Einstellung wiederhergestellt.

[Ausführliche Anleitung](TITAN-IMAGE.md) · [Updates und Rollback](UPDATES.md)

Nach dieser Neuinstallation kommen weitere kompatible Versionen über den
Alpha-Update-Kanal. Bestehende andere NAS-Systeme werden nicht automatisch
konvertiert; das Image nicht über deren Datenplatten schreiben.
