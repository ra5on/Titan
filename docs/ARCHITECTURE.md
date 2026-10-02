# Architektur auf uCore-HCI

Titan ist ein abgeleitetes, startfähiges uCore-HCI-Image. Die Python-Webanwendung und statische Oberfläche liegen unter `/usr/lib/titan`. Es gibt keine zusätzlichen pip-Laufzeitabhängigkeiten und keinen npm-Build. Fedora-RPMs werden ausschließlich während des Image-Builds installiert. Im laufenden System werden vollständige signierte Images für den nächsten Start vorbereitet.

- `titan-proxy`: Caddy, HTTPS-Port 5000, eigenes unprivilegiertes Konto.
- `titan-web`: Python/SQLite, localhost-Port 5001, Konto `titan` und systemd-Härtung.
- `titan-agent`: lokaler root-Verwaltungsdienst für ausdrücklich autorisierte NAS-Aktionen.
- `titan-firstboot`: erzeugt die geräteeigene Konfiguration und bereitet persistente Pfade vor.

Die lokalen RPC-Berechtigungen, Administratorprüfung, CSRF-Schutz und Sitzungsbindung bleiben erhalten. Das Terminal ist eine explizit geöffnete root-Sitzung mit Zeitlimits. Dienst- und Dateiaktionen verwenden feste geprüfte Schnittstellen.

## Persistenz

`/usr` stammt aus dem schreibgeschützten Systemimage. `/etc` enthält veränderbare Konfiguration. `/var/lib/titan` enthält die Web-Datenbank, `/var/lib/titan-agent` Verwaltungsdaten und App-Konfiguration. Der neue NAS-Datenbereich ist `/var/srv/titan`. Libvirt verwendet `/var/lib/libvirt/images/titan` oder geprüfte verwaltete Datenvolumes. Benutzerkonten werden im veränderbaren `/etc` angelegt. Instance-Schlüssel und Kennwörter werden nicht im Download vorgegeben.

Der Administrator-Dateimanager kann Systemdateien lesen und aus dem Image kopieren. Änderungen auf schreibgeschützten Mounts werden verständlich abgelehnt; Änderungen an Systemprogrammen gehören in den nächsten Image-Build.

## Hostdienste und SELinux

Samba heißt `smb.service`. Libvirt verwendet modulare Sockets für QEMU, Netzwerk, Storage, Logging, Locks und weitere Treiber. Fedora-QEMU verwendet das Konto `qemu`. noVNC und Websockify sind bereits vorhanden. Dienste lassen sich reparieren, fehlende Systempakete erfordern ein korrigiertes Image.

SELinux bleibt aktiv. Die Titan-Dienste laufen aufgrund der gewollten Administratorfunktionen im unconfined-Service-Kontext; Web/Proxy behalten zusätzlich unprivilegierte Linux-Konten und systemd-Härtung. Eine eigene Dateikategorie `titan_share_t` erlaubt Samba und Containern den Zugriff auf verwaltete Freigaben. Linux-ACLs und die tatsächlich eingehängten Containerpfade begrenzen weiterhin einzelne Konten/Apps. Private App-Konfigurationen werden mit `:Z` gelabelt; gemeinsame NAS-Freigaben werden nicht privat umgelabelt. VM-Diskverzeichnisse erhalten den spezifischeren `virt_image_t`-Kontext; aktive Gastdateien werden nicht pauschal rekursiv umgelabelt.

## Auslieferung

Eine festgelegte uCore-Basis ergibt einen signierten OCI-Systemstand. Eine ebenfalls festgelegte Builder-Version erstellt daraus die interne Raw-Testdisk. Ein tatsächlicher QEMU-Erststart und Runtime-Test prüfen HTTPS, Ersteinrichtung, Metriken sowie App-/VM-Abläufe. Die beiden Ergebnisse stehen im signierten Release-Manifest und müssen vor jeder öffentlichen Veröffentlichung ausdrücklich `passed` sein, auch für Alpha. Fehlgeschlagene Teststände erhalten nur Actions-Diagnosen und werden nicht als Systemupdate angeboten.

Reguläre Releases liefern OCI-Systemupdates ohne Installations-IMG-Download. Nur bei ausdrücklicher Wahl von `installer_image` im manuell gestarteten Workflow wird die geprüfte Raw-Disk zusätzlich komprimiert, signiert und als `.img.xz` veröffentlicht. OS-Updates werden über bootc vorbereitet und erst nach einem manuellen Neustart aktiviert. Das bestehende Installationsimage bleibt für neue Systeme verfügbar; neue ISO-Builds entfallen.
