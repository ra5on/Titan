> Historical predecessor release notes; this is not a Titan release.

# Titan v0.3.0 · Alpha · uCore

Titan wechselt auf ein eigenes uCore-HCI-Systemimage für x86_64. Dies ist eine frühe Alpha für einen separaten Testdatenträger; die vollständige NAS-Hardwareintegration ist noch zu prüfen.

- Neue responsive Oberfläche mit klaren Bereichen, verschiebbaren gespeicherten Kacheln und sichtbarer Auftragsseite.
- Echte CPU-Auslastung, RAM/Cache/Swap, Temperatursensoren und Verlaufsgrafik; fehlende Werte erscheinen als nicht verfügbar.
- Diagnosebericht zum Download ohne Zugangsdaten, Konfiguration oder Terminalprotokolle.
- Komplettes `.img`, für den Download als `.img.xz` komprimiert; zunächst kein ISO.
- Docker, Samba, ZFS, Ext4/XFS, QEMU/libvirt, noVNC und Websockify sind im Image enthalten.
- Erster Start mit der aktuellen IPv4-Adresse und HTTPS auf Port 5000; Administrator im Browser anlegen.
- Signierte vollständige Systemupdates mit Alpha/Beta/Stable und manueller Aktivierung durch Neustart.
- Modulare libvirt-Dienste, Fedora-QEMU-Konto und SELinux-Kontexte.
- Dateimanager erkennt schreibgeschützte Systemdateien und erlaubt weiterhin Lesen/Kopieren sowie Bearbeiten der veränderbaren Bereiche.

Installation benötigt einen separaten Systemdatenträger beziehungsweise eine geplante Neuinstallation. Vorhandene Daten vorher sichern; Konfigurationssicherungen anderer Systemgrundlagen nicht ungeprüft importieren.

Der Build prüft Python-/UI-Funktionen und die Container-Signatur und führt einen Erststart in QEMU mit HTTPS-Prüfung durch. **Der tatsächliche Boot-Teststatus steht in den Release-Hinweisen, im signierten Manifest und in `boot-test.json`; `runtime-test.json` dokumentiert Metriken und Docker-/VM-Prüfungen; `boot-console.log` enthält die Konsolenausgabe.** Ein Alpha-Testimage mit fehlgeschlagenem oder unvollständigem Start-/Laufzeittest benötigt einen manuellen Proxmox-Test, ist keine Beta-Freigabe und wird nicht als Systemupdate angeboten. Ein bestandener Erststart bestätigt noch nicht sämtliche ZFS-, Samba-, Docker- und KVM-Funktionen auf der NAS-Hardware. [Installation](INSTALL.md) · [Testplan](TESTING.md)
