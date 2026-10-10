# Titan 0.8.0 · Alpha

Vorabversion mit neuer Oberfläche. Sie erscheint im Alpha-Kanal; Installationen
im Stable-Kanal erhalten sie nicht als Update.

## Neu

- Neue Startseite ohne Fensterverwaltung: installierte Apps als Symbole, drei
  Live-Kacheln für CPU, RAM und Speicher, feste Navigation am unteren Rand.
- App Store mit Empfehlung, Kategorien, Suche und einer Detailseite, die die
  echten Installationsschritte des Systemdienstes anzeigt.
- Dateimanager mit Upload-Fortschritt, Abbrechen, Download, Umbenennen und
  Papierkorb.
- Virtuelle Maschinen: Start, Herunterfahren, Neustart, Konsole, neue VM und
  ISO-Upload.
- Einstellungen für System, Speicher, Freigaben (anlegen und entfernen),
  Benutzer und Updates.

## Unverändert

Agent-API, Datenbankschema und alle Serverfunktionen bleiben wie in 0.7.0. Die
bisherige Oberfläche ist unter `/classic` erreichbar. Dort liegen weiterhin
Rechte einzelner Benutzer, Sicherungen, Docker-Ansicht, Terminal, Fotos und die
erweiterte VM-Verwaltung.

## Grenzen

- Automatisch geprüft sind Startseite, App-Aktionen, App Store, VM-Anlage,
  ISO-Upload, Freigaben, Einstellungen und der Dateimanager im Browser gegen die Demo.
- Noch nicht auf einem echten System geprüft: Anmeldung und Ersteinrichtung in
  der neuen Oberfläche sowie eine vollständige App-Installation.
- ZFS-Umstellung auf Btrfs und der Wegfall des manuellen Rollbacks sind geplant
  und in dieser Version noch nicht enthalten.
