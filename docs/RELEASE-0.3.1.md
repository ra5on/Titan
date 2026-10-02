> Historical predecessor release notes; this is not a Titan release.

# Titan v0.3.1 · Alpha · uCore

Docker verwendet die SELinux-Einstellung aus der Fedora-Dienstdatei. Die zusätzliche gleiche Option in `daemon.json` wurde entfernt, weil Docker doppelte Optionen ablehnt. Der Image-Build prüft jetzt die tatsächlichen Startparameter mit `dockerd --validate`, ohne den Daemon zu starten.

Startfehler von Docker und den Titan-Diensten erscheinen auch in der lokalen beziehungsweise Proxmox-Konsole. Eine begrenzte Statusprüfung zeigt nach dem Boot Dienstzustände, Listener, aktive Firewallzonen und lokale HTTP-Ergebnisse, ohne Konfiguration, Zugangsdaten oder Sitzungsantworten auszugeben. Der Image-Test hält HTTPS-Transportfehler fest und veröffentlicht Prüfprotokolle bereits vor der Downloadkomprimierung.

Die moderne Oberfläche, Metriken, Datei-, App-, Benutzer-, Freigabe- und VM-Verwaltung aus v0.3.0 bleiben enthalten. Das System bleibt Alpha. Maßgeblich sind der tatsächliche Boot- und Laufzeitteststatus im signierten Manifest und die separaten NAS-/Proxmox-Prüfungen.

[Installation](https://github.com/ra5on/Titan/blob/main/docs/INSTALL.md) · [Testplan](https://github.com/ra5on/Titan/blob/main/docs/TESTING.md)
