# Webcontainer und Updatevertrag

Ab der Neuinstallationsbasis 0.6.1 startet `titan-web.service` einen Docker-Container. Der Root-Controller `/usr/share/titan/web-container.py` verwaltet dessen Lebenszyklus. Der eigentliche HTTP-Prozess läuft mit UID/GID des Hostkontos `titan`, bindet ausschließlich `127.0.0.1:5001` im Hostnetz und besitzt keinen Docker-Socket. Caddy übernimmt HTTPS. `/run/titan`, `/etc/titan` und Host-Image-Metadaten werden schreibgeschützt eingebunden. Nur `/var/lib/titan` und ein temporäres `/tmp` sind beschreibbar.

Die Hostnetz-Anbindung erhält die bestehenden lokalen Agent-, VNC- und Office-Verbindungen. Sie ist keine Netzwerkisolation; die privilegierte Steuerung erfolgt weiterhin über den lokalen Titan-Agenten. Die neue Basis setzt Protokoll 1 und Datenvertrag 1 voraus.

## Installation und Betrieb

Das Installationsimage enthält `web-image.tar` und die zugehörige unveränderliche Docker-Image-ID. Systemd lädt das Archiv vor dem ersten Webstart. Ein NAS benötigt deshalb keinen Internetzugang, um die Oberfläche erstmals zu öffnen.

Die persistente Auswahl liegt unter `/var/lib/titan-web/selection.json`. Der Updater hält einen exklusiven Lock, startet den Wechsel in einer eigenen systemd-Unit und prüft `/api/health`. Diese Prüfung umfasst Webversion, Datenbankzugriff und Agentenprotokoll. Bei Fehlschlag wird die vorige Auswahl gestartet; bei unterbrochenem Wechsel wird sie beim nächsten Start wiederhergestellt. Vorhandene Docker-Images der aktuellen und vorherigen Webversion dürfen nicht extern gelöscht werden.

## Updates

**Systemsteuerung → Updates & Rollback → Weboberfläche → Jetzt prüfen** liest signierte GitHub-Release-Manifeste. Das Containerarchiv wird nur nach Prüfung von Signatur, Prüfsumme, Größe und kompatibler Image-ID geladen. Der Webwechsel benötigt keinen NAS-Neustart. Nach dem Gesundheitscheck lädt die Oberfläche neu. Downloads, laufende Browseruploads und interaktive Konsolen können dabei unterbrochen werden; vorher abschließen.

Für Diagnose auf dem Host:

```sh
sudo python3 /usr/share/titan/web-container.py status
sudo journalctl -u titan-web -u titan-web-switch
```

Für einen manuellen Rückfall:

```sh
sudo systemd-run --unit=titan-web-switch --collect /usr/bin/python3 /usr/share/titan/web-container.py rollback
```

Der Controller unterstützt außerdem einen expliziten GHCR-Digest mit Versionsangabe für Administratoren. Die normale Oberfläche verwendet ausschließlich signierte Release-Artefakte; sie fordert keinen Registry-Zugang an.

## Unabhängige Veröffentlichung

Der Workflow **Titan Web container** baut, testet und veröffentlicht Webversionen unabhängig vom NAS-Image. GitHub-Tags `web-v0.6.1` kennzeichnen den Webkanal; in Titan erscheint die Version als `0.6.1`. Die Systemupdate-Suche ignoriert diesen eigenen Namensraum. Das signierte Manifest und das Containerarchiv werden direkt an die Webveröffentlichung angehängt. Dadurch benötigt eine reine Oberflächenkorrektur keinen erneuten Betriebssystem-Build. Bereits veröffentlichte Webversionen werden nicht ersetzt.

## Grenzen des Vertrags

Ein gesundes HTTP-Frontend beweist keine korrekte Funktion jeder NAS-Aktion. Daher bleiben reale QEMU-/NAS-Prüfungen erforderlich. Web-Rollback ist kein Datenbank-Restore. Neue Versionen müssen das vorherige Datenformat weiterhin unterstützen. Änderungen am Host-Agenten, Kernel oder Speicherbackend gehören in ein Systemupdate. Ein OS-Rollback und ein Web-Rollback sind getrennte Vorgänge.
