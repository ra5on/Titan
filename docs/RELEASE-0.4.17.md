# Titan 0.4.17 – Desktop statt Übersicht

Die Startfläche besteht aus Hintergrund und frei gewählten Verknüpfungen. Die bisherige Kachelübersicht, Desktop-Uhr und beschrifteten System-Schaltflächen entfallen.

- Hauptmenü: Werkzeuge und installierte Apps suchen, öffnen und mit „Zum Desktop hinzufügen“ ablegen. Eine entfernte Verknüpfung deinstalliert keine App.
- Icons frei auf dem Raster verschieben. Zum Gruppieren ein Icon kurz über einem anderen halten; alternativ einen Ordner über das Desktop-Kontextmenü erstellen und Verknüpfungen über „In Ordner“ zuordnen. Ordner lassen sich umbenennen und auflösen. Tastatur: Alt + Pfeiltasten verschiebt, Entf entfernt die Verknüpfung.
- Verknüpfungen, Ordner, Positionen und Widget-Auswahl werden pro Konto auf dem NAS gespeichert. Auch ein absichtlich leerer Desktop bleibt leer. Auf schmalen Bildschirmen werden Positionen innerhalb der sichtbaren Breite angeordnet.
- App-Webzugänge öffnen separat mit `noopener`/`noreferrer`. Gestoppte Apps und Apps ohne Webzugang zeigen einen Hinweis; „App verwalten“ führt zur Docker-Verwaltung.
- Titan-Werkzeuge laufen in eigenen Fenstern mit beibehaltenem Inhalt. Fensterpositionen, Hintergrund und Taskleisten-Auswahl bleiben pro Konto in diesem Browser gespeichert. Der neue Desktop beginnt einmal mit geschlossenen Fenstern; danach wird die Sitzung wiederhergestellt.
- Das Statuswidget unten rechts kann ausgeblendet, eingeklappt und konfiguriert werden: CPU, belegter RAM inklusive Cache, Systemstatus, Meldungen und laufende Aktivitäten. Bei fehlenden Messwerten erscheint keine erfundene Auslastung. Detailverläufe liegen im separaten Ressourcenmonitor.
- Im Benutzermenü stehen persönliche Einstellungen, Abmelden sowie für Administratoren Neustart und Herunterfahren mit Ja/Nein-Bestätigung bereit.

## Bereinigung und Kompatibilität

Der alte Dashboard-Editor, die vorherige Launcher-Anordnung, der doppelte Fenstercontroller, deren CSS-Regeln und die nicht mehr benötigte SortableJS-Abhängigkeit wurden entfernt. Die bisherige Dashboard-API und gespeicherten Einstellungen bleiben für ältere Clients und einen Rollback erhalten. Beim Löschen eines Kontos werden auch dessen Desktop-Einstellungen entfernt.

Die Backend-, Ressourcen- und Fensterprüfungen wurden um die neue Speicherung, Ordner, URL-Prüfung und Widget-Semantik ergänzt. Die lokale Demo wurde bei 320 und 390 Pixeln sowie am Desktop geprüft. Das ersetzt keinen Test des kompletten Systemupdates auf dem NAS.

## Installation

Nach erfolgreicher Veröffentlichung des signierten Systempakets: **Systemsteuerung → Updates & Rollback → Alpha → Jetzt prüfen**. Ein neues Image ist für bestehende Installationen nicht erforderlich.
