# Titan installieren

Titan **0.7.0 Horizon** ist im Stable-Kanal veröffentlicht. Das Debian-A/B-Image ist
für eine neue AMD64/UEFI-Installation vorgesehen. [Prüfumfang und Grenzen](VERIFY-0.7.0.md).

[IMG herunterladen](https://github.com/ra5on/Titan/releases/download/v0.7.0/titan-0.7.0-amd64.img.xz) · [Prüfsummen und Testberichte](https://github.com/ra5on/Titan/releases/tag/v0.7.0)

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
gewählten Update-Kanal (0.7.0: Stable). Bestehende andere NAS-Systeme werden nicht automatisch
konvertiert; das Image nicht über deren Datenplatten schreiben.
