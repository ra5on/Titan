# Ext4, XFS und ZFS

Titan verwendet **Ext4 als Vorauswahl** für ein neues einzelnes Datenlaufwerk. XFS bleibt auswählbar, ZFS bietet weiterhin Pools und Datasets. Die Werkzeuge für alle drei Dateisysteme sind im Systemimage enthalten. Das Dateisystem des bereits installierten uCore-Systemlaufwerks wird nicht geändert.

Ext4 ist hier die einfache Allround-Vorgabe. Seine Linux-Werkzeuge unterstützen beispielsweise das Vergrößern und das Verkleinern eines ausgehängten Dateisystems. Das ist ein Grund für die Auswahl; es ist keine Behauptung, dass jedes Ext4-System zuverlässiger als jedes XFS-System wäre. Hintergrund: [Linux-Ext4-Dokumentation](https://www.kernel.org/doc/html/latest/filesystems/ext4/overview.html), [resize2fs im e2fsprogs-Projekt](https://github.com/tytso/e2fsprogs/blob/master/resize/resize2fs.8.in) und [Linux-XFS-Dokumentation](https://docs.kernel.org/admin-guide/xfs.html).

## XFS-Systemdisk erweitern

Ab v0.4.3 nutzt die letzte XFS-Systempartition des unveränderten Titan-GPT-Layouts beim Start den freien Endbereich ihrer Systemdisk. Eine später in Proxmox vergrößerte Systemdisk kann auch unter **Speicher → Systemplatte → Kapazität erweitern** übernommen werden. Boot-/EFI-Bereiche bleiben separat. LUKS, LVM, RAID, Multipath und weitere Datenpartitionen auf derselben Systemdisk sind von dieser automatischen Erweiterung ausgeschlossen. [Installation und Erweiterung](INSTALL.md#ganze-systemdisk-nutzen-und-später-erweitern).

Die Größenänderung der Systemdisk ist getrennt von der nachfolgenden Verwaltung zusätzlicher Ext4-/XFS-Datenvolumes.

## Datenlaufwerk in der Oberfläche einrichten

Unter Speicher ein Volume erstellen, ein geeignetes leeres Datenlaufwerk und Ext4 oder XFS wählen. Laufwerksadresse und Volumename müssen ausdrücklich bestätigt werden. Titan lehnt bereits partitionierte, gemountete oder mit Signaturen belegte Laufwerke ab. Formatieren gehört nicht zur automatischen Installation.

Ein neues Volume wird unter `/var/srv/titan/volumes/NAME` eingehängt. Der Neustart verwendet seine Dateisystem-UUID. Die Oberfläche zeigt Dateisystem, Mountstatus und Kapazität. Eine SMB-Freigabe kann einen eigenen Unterordner auf dem eingehängten Volume verwenden; der Dateimanager verwendet dieselben Benutzerrechte.

Der zugrunde liegende leere Mountpunkt ist ohne Nutzerzugriff eingerichtet. Fehlt ein Volume, werden betroffene Zugriffe abgewiesen; Daten sollen nicht unbemerkt auf das Systemlaufwerk geschrieben werden. Erneutes Einhängen verwendet ausschließlich ein bereits von Titan verwaltetes Volume.

## Umfang und Grenzen

Ext4-/XFS-Volumes sind einzelne Laufwerke. RAID, Übernahme bestehender Dateisysteme, Größenänderungen und automatische Dateisystemreparaturen sind noch nicht Teil dieser Oberfläche. ZFS-Snapshots und -Datasets gelten für ZFS; normale Ext4-/XFS-Volumes erhalten dadurch keine Snapshots. Für alle Dateisysteme unabhängige Backups einplanen.

Der Konfigurationsrestore bleibt auf denselben Host begrenzt: vorhandene Volume-Zuordnungen und Mounts müssen noch gültig sein. Er formatiert oder importiert keine Laufwerke und schreibt keine gespeicherten Mountbefehle aus einer Sicherung zurück. Die Wiederherstellung auf neuer Hardware benötigt einen eigenen Wiederherstellungsablauf.
