# Debian-Testplan

## Automatisierte Prüfungen

- `python3 -m unittest discover -s tests -v`: APIs, Rechte, Dateiverwaltung, Signaturen, Debian-Profile und A/B-Updategrenzen.
- `node tests/<suite>.cjs`: UI-Verhalten und Darstellung.
- Shell- und JavaScript-Syntaxprüfung in CI.
- Debian-Image-Workflow: echter QEMU-Start und Laufzeitprüfung von HTTPS, Anmeldung, Metriken, SMB, Docker und VM-Komponenten.
- A/B-Integration: Update auf den Kandidaten, Neustart, Gesundheitsbestätigung, Rollback, unveränderte persistente Daten sowie Vergrößerung der Systemdisk und fehlgeschlagener Start mit Rückfall.

Der Nextcloud-Lauf des Image-App-Gates aktiviert zusätzlich `--app-backup-smoke`.
Auf dem ausschließlich dafür bestätigten GitHub-Runner wird ein separater
Ext4-Loopdatenträger eingehängt und über die normalen HTTP-APIs als Sicherungsziel
ausgewählt. Der Test sichert die laufende App samt ausdrücklich ausgewählten
Nutzdaten, verändert einen echten Nextcloud-Datenbankwert und Dateimarker,
stellt das gestoppte Paket wieder her und prüft Zugangsdaten, Unix-Rechte,
Recovery-Ordner sowie den erneuten Datenbank- und HTTP-Zugang. Die normale
Zielvalidierung und der GitHub-Runner-Schutz werden dafür nicht abgeschaltet.
Zusätzlich verändert der Test den echten Nextcloud-Lizenzlink
`dist/1404-1404.js.map.license` und seine reguläre Zieldatei. Nach dem Restore
müssen relativer Linktext, Link-Eigentümer, Zielinhalt und Zielrechte dem
gesicherten Stand entsprechen. App-Archive erlauben nur vorhandene relative
Linkziele innerhalb desselben Konfigurations- beziehungsweise Nutzdatenbaums;
absolute, aus dem Baum führende und verwaiste Links, Schleifen, Hardlinks und
Spezialdateien bleiben gesperrt. Adversarialtests prüfen Linkketten mit `..`,
Links als Archiv-Eltern in beiden Eintragsreihenfolgen sowie die unveränderte
Sperre für Freigaben und NAS-Konfigurationsdateien.
Nur ein erfolgreicher tatsächlicher Workflow-Lauf ist der Betriebsnachweis.

Laufzeitberichte gehören zur tatsächlich getesteten Version. Ein nicht verfügbarer Hardwaretest wird als übersprungen dokumentiert. Er darf nicht als erfolgreicher Betriebsnachweis gelten.

## Manuelle Prüfung

Siehe [Proxmox-Test](PROXMOX-TEST.md). Zusätzlich sind echte Windows-/macOS-SMB-Clients, physische NAS-Laufwerke und längere App-/VM-Betriebszeiten zu prüfen. RAM-Werte im Gast müssen gegen `/proc/meminfo` verglichen werden; die Host-Speicherbelegung einer VM ist eine andere Messgröße.
