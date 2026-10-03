# Titan auf Debian 13: A/B-Alpha

Titan verwendet Debian 13 (trixie), amd64, mit eigenen signierten Systempaketen.
Ubuntu ist eine mögliche spätere Plattform, derzeit aber nicht unterstützt.
Die Installation erfolgt als neues Image, nicht als Umstellung eines laufenden
anderes NAS-Systems.

## Umgesetzt

- Debian-System mit Docker/Compose, QEMU/libvirt, noVNC, Samba, ext4/XFS und AppArmor.
- UEFI-Image mit zwei festen Systembereichen und separatem persistentem Datenbereich.
- Signierte Update-Manifeste und RAUC-Pakete; Installation in den inaktiven Bereich,
  ausdrücklich bestätigter Neustart, Startprüfung und Rollback-Dropdown.
- Persistente NAS-Konten, Freigaben, ACLs, Einstellungen sowie App-/VM-Daten.
- Overlay für lokale `/etc`-Änderungen; unveränderte Vorgaben folgen dem Systemstand.
- Signierter Vertrag für System-UIDs/-GIDs; abweichende Konten oder Datenschemata
  werden vor einem Update abgelehnt.
- Vergrößerung des Datenbereichs bei größeren Proxmox-Platten.

Der Freigabelauf prüft Boot/HTTPS, Einrichtung, Metriken, SMB-Zugriffsrechte,
Docker-Netze und VM-Domänen samt Browserkonsole. Der A/B-Test prüft echtes Schreiben,
Neustart, Rollback, Rückfall nach defektem Teststart und erhaltene Konten/ACLs/Dateien.
Für die erste Veröffentlichung wird eine synthetische ältere Versionskennung
verwendet; das ersetzt noch keinen Test zwischen zwei weiterentwickelten Releases.

## Vor der Beta weiter prüfen

- Updates zwischen tatsächlich veröffentlichten Versionen und längerer Proxmox-Betrieb.
- Installierte VM-Gastbetriebssysteme, weitere Datenträger und Hardwarekonfigurationen.
- Unterbrochene Schreibvorgänge, volle Datenträger und Wiederherstellung nach Stromausfall.
- Export/Import älterer Installationen mit Kennwörtern, IDs, ACLs, Volumes und App-Daten.
- Wartung des gemeinsamen EFI-/GRUB-Startbereichs; dieser wird im Alpha-Updater
  noch nicht erneuert. Änderungen daran benötigen derzeit ein neues Image.

ZFS, Secure Boot, BIOS-Start und ARM sind in dieser Alpha nicht freigegeben.
Der aktuelle Stand ist keine Beta und keine Freigabe für produktive Daten.

## Interner Debian-Paketbaustein

`python3 scripts/build-debian-package.py` erzeugt das Entwicklungspaket, das der
Image-Build verwendet. Dieses `.deb` allein ist kein A/B-Installer und aktiviert
keine Dienste. Nicht auf einem vorhandenen NAS installieren. Der vollständige
Build läuft im isolierten GitHub-Workflow `Titan Debian A/B image`.

[Image-Anleitung](TITAN-IMAGE.md) · [Updates und Rollback](UPDATES.md)
