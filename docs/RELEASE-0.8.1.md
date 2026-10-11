# Titan 0.8.1 · Stable

Stabile Veröffentlichung mit der neuen Oberfläche und Korrekturen für Speicher,
Freigaben, Uploads, virtuelle Maschinen und Fernzugriff. Neue Titan-Releases und
automatische Debian-Wartungsupdates erscheinen ausschließlich als Stable.
Vorhandene Alpha-/Beta-Releases bleiben historische Downloads.

## Änderungen

- Der bereits verfügbare interne Speicher wird auch angezeigt, wenn eine
  Erweiterung nicht möglich ist. Als Standard für neue Daten auswählbar.
- Die Erweiterung der Installationsplatte verwendet die tatsächliche ext4-
  Datenpartition des Debian-A/B-Layouts. Betriebssystem- und Bootpartitionen
  bleiben erhalten; unsichere oder abweichende Layouts werden abgewiesen.
- Freigaben erlauben Namen wie „Meine Dateien“ und „Fotos für Jörg“, auch im
  SMB-Netzwerk. Interne Pfade und Berechtigungen verwenden eine getrennte stabile
  Kennung. „Öffnen“ führt direkt zur ausgewählten Freigabe.
- Datei-Uploads verwenden 8-MiB-Blöcke statt 2 MiB und bereinigen alte Uploads
  nur beim Beginn eines Transfers. Das reduziert Prozessstarts, Journalprüfungen
  und Synchronisationsaufrufe. Leere Dateien lassen sich ebenfalls hochladen.
  Die tatsächliche Geschwindigkeit hängt von NAS, Datenträger und Netzwerk ab.
- Das Dock hat keinen horizontalen Scrollbalken. Symbole passen sich der
  Bildschirmbreite an; auf sehr schmalen Bildschirmen sind mehrere Reihen möglich.
  VNC- und App-Fenster berücksichtigen die gemessene Dockhöhe einschließlich
  Größenänderungen. Listen lassen sich vollständig oberhalb des Docks anzeigen.
- VM-Einstellungen direkt über „Bearbeiten“: Anzeigename, CPU/RAM, Host-CPU-
  Zuordnung, Firmware, Bootreihenfolge, Autostart, ISO, Laufwerke, Netzwerkkarten,
  USB/PCI und Gastagent. Hardwareänderungen verlangen eine ausgeschaltete VM.
  Laufwerke lassen sich vergrößern; die Gastpartitionen sind anschließend im
  Gastsystem zu erweitern. Zusätzliche Laufwerke können getrennt werden, ihre
  Image-Dateien bleiben erhalten. Ein Verschieben bestehender VM-Laufwerke ist
  in dieser Oberfläche noch nicht enthalten.
- Fernzugriff zeigt die ermittelte HTTP-Zieladresse mit Port 5102 und prüft den
  Tunnel direkt. Eine leere öffentliche Antwort wird als fehlerhafte Route
  erklärt. Die öffentliche Verbindung bleibt HTTPS.

## Einzelne Funktionen mit Beta-Status

USB-Automount, laufender Abgleich, Btrfs-Spiegel mit Laufwerkstausch, optionale
NVIDIA-Treiberinstallation sowie USB-/PCI-Durchreichung sind noch nicht umfassend
auf physischer Hardware erprobt. Diese Funktionen bleiben als Beta gekennzeichnet;
das Release selbst ist Stable. Ihre bisherigen Grenzen gelten weiterhin.

## Installation und Updates

Für eine neue Installation das komprimierte AMD64-Image aus diesem Release
entpacken und als Systemplatte verwenden; siehe [Installationsanleitung](INSTALL.md).
Bestehende Debian-A/B-Installationen verwenden das signierte Systemupdate über
Einstellungen → Updates. Für die neuen VM- und Speicherfunktionen das vollständige
Systemupdate verwenden, da sich neben der Oberfläche auch der Systemdienst ändert.

Die Veröffentlichung enthält Prüfsummen, signierte Metadaten, das RAUC-Update
und die Protokolle der automatischen Boot-/Update-/Rollback-Prüfungen. Ein Release
erscheint erst nach erfolgreichem Abschluss dieser Prüfungen.

## Eigenständige Umsetzung

Titan verwendet seine eigene Python-/React-Architektur. TitanOS dient als
funktionale Referenz; für diese Änderungen wurde kein UmbrelOS-/TitanOS-Code
oder Artwork übernommen. Die bestehenden Hinweise zu Titan und seinen
unabhängig lizenzierten Drittkomponenten stehen in `LICENSE` und `NOTICE`.
