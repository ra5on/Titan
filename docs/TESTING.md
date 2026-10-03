# Debian-Testplan

## Automatisierte Prüfungen

- `python3 -m unittest discover -s tests -v`: APIs, Rechte, Dateiverwaltung, Signaturen, Debian-Profile und A/B-Updategrenzen.
- `node tests/<suite>.cjs`: UI-Verhalten und Darstellung.
- Shell- und JavaScript-Syntaxprüfung in CI.
- Debian-Image-Workflow: echter QEMU-Start und Laufzeitprüfung von HTTPS, Anmeldung, Metriken, SMB, Docker und VM-Komponenten.
- A/B-Integration: Update auf den Kandidaten, Neustart, Gesundheitsbestätigung, Rollback, unveränderte persistente Daten sowie Vergrößerung der Systemdisk und fehlgeschlagener Start mit Rückfall.

Laufzeitberichte gehören zur tatsächlich getesteten Version. Ein nicht verfügbarer Hardwaretest wird als übersprungen dokumentiert. Er darf nicht als erfolgreicher Betriebsnachweis gelten.

## Manuelle Prüfung

Siehe [Proxmox-Test](PROXMOX-TEST.md). Zusätzlich sind echte Windows-/macOS-SMB-Clients, physische NAS-Laufwerke und längere App-/VM-Betriebszeiten zu prüfen. RAM-Werte im Gast müssen gegen `/proc/meminfo` verglichen werden; die Host-Speicherbelegung einer VM ist eine andere Messgröße.
