# Titan 0.4.13-alpha.1

Titan erweitert seine eigene Docker-Verwaltung um eine kompakte Containerübersicht und gemeinsame Aktionen. Die Oberfläche orientiert sich an üblichen Container-Managern; Dockhand-Code und -Assets werden nicht eingebunden. One-Click-Store-Erweiterungen bleiben zurückgestellt.

- **Desktop und Mobil:** kompakte Tabelle mit Name, Image, Status, Live-CPU/RAM, IP-Adressen, Ports und direkt sichtbaren Aktionen. Auf kleinen Bildschirmen erscheinen lesbare Karten. Suche, Statusfilter und A–Z/Z–A-Sortierung; Eingabefokus bleibt beim Aktualisieren erhalten.
- **Live-Übersicht:** Anzahl der Container, laufende und gestoppte Container, fehlerhafte Healthchecks und tatsächlicher Container-RAM. Gestoppte Container zählen mit 0 B; fehlende aktive Messwerte werden als unbekannt dargestellt.
- **Mehrfachauswahl:** bis zu 64 Container gemeinsam starten, stoppen oder neu starten. Stop/Neustart mit Ja/Nein-Bestätigung. Die vollständige Auswahl wird vor Änderungen geprüft. Titan-Apps mit mehreren Diensten werden nur einmal als App gesteuert; Teilfehler werden als fehlgeschlagener Auftrag samt Ergebnissen gemeldet.
- **Stacks:** vorhandene Compose-Projekte werden über ihre Docker-Metadaten gruppiert. Einzelne Dienste sind direkt erreichbar, Start/Stop/Neustart wirken auf die gesamte ausgewählte Gruppe. Fremde Compose-Dateien werden dabei nicht überschrieben oder ausgeführt.
- **Vorhandene Funktionen:** Container erstellen mit Ports, Netzwerk, Umgebungsvariablen, Datenvolume, Ressourcenlimits und erkannten USB/GPU-Geräten; Images, Netzwerke und Volumes verwalten; Details und Logs anzeigen. Gesamt-System-RAM, ausgeschaltete VM-Ressourcen, automatische VNC-Verbindung und anpassbare Dashboard-Kacheln aus 0.4.12 bleiben enthalten.

## Update und Rollback

Einstellungen → Update / Rollback → Alpha-Kanal. Das signierte Debian-A/B-Systemupdate enthält alle Änderungen; kein neuer IMG-Import erforderlich. Docker-Nutzdaten liegen weiterhin im persistenten Datenbereich.

## Prüfungen und Grenzen

Die Freigabe erfolgt erst nach Python-/UI-Regressionstests, echtem Debian-QEMU-Docker-Test (einschließlich Mehrfachaktionen und Compose-Gruppierung) und A/B-Update-/Rollback-Prüfung. Lokale Browserprüfung umfasst Desktop und 320-Pixel-Mobilansicht, Suche, gemeinsame Aktionen und Stack-Steuerung.

Weiterhin **Alpha**. Freie Compose-Bearbeitung, Registry-Anmeldungen, Container-Terminal und planbare Image-Updates sind noch offen. Physische USB/GPU-Geräte und echte Smartphones sind nicht im QEMU-Test verfügbar.
