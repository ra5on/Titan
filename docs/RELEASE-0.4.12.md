# Titan 0.4.12-alpha.1

Diese Version konzentriert sich auf direkt nutzbare Docker-Verwaltung, konsistente Ressourcenanzeigen und mobile Bedienung. Dockhand wird nicht eingebettet; dessen Code, Assets und Lizenz werden nicht übernommen. One-Click-Store-Erweiterungen sind zurückgestellt.

- **Docker:** eigene Verwaltung aller lokalen Container, einschließlich manuell oder außerhalb des Stores erstellter Container. Images laden/entfernen, Datenvolumes erstellen/entfernen, Container mit Image, Ports, Bridge/Host/eigenem Netzwerk, Umgebungsvariablen, Datenvolume, CPU-/RAM-Limits, Neustartregel und erkannten USB-/GPU-Geräten anlegen. Start, Stop, Neustart, Details, Logs und Live-Ressourcen direkt erreichbar. Benutzte Images/Volumes und laufende Container werden nicht zwangsweise entfernt. Vorlagen-Apps behalten die vorhandene Konfigurationsprüfung.
- **RAM:** alle Systemanzeigen verwenden `MemTotal − MemFree`, einschließlich Cache. Anwendungsbedarf und verfügbarer RAM bleiben separat. Docker-RAM wird aus `memory.current` gemessen, statt den vom Docker-CLI abgezogenen Cache zu verschweigen. Nicht messbare Werte bleiben unbekannt. VM-RAM zeigt gemessenen Host-RSS; ausgeschaltete VMs zeigen 0 B, unabhängig von alten Balloon-Werten oder konfigurierter RAM-Größe. Pausierte VMs belegen weiterhin RAM.
- **Konsole:** automatischer Bereitschaftstest, automatisches Wiederverbinden, Bildschirm automatisch mit einer kurz gedrückten und wieder freigegebenen Umschalttaste wecken; keine Tastenkombination für den Verbindungsaufbau. Zusätzliche Buttons „Verbinden“ und „Bildschirm wecken“. Anmeldung bleibt erforderlich; Abmelden beendet den Zugang.
- **Oberfläche:** echte animierte Ziehgesten mit lokal eingebundenem SortableJS, Vorschau und automatischem Scrollen. Kachelbreite und Höhe direkt am Griff ändern und je Konto speichern. Auf Mobilgeräten einspaltige Kacheln, kompakte Manager-Navigation und durchgehender Seiten-Scrollbereich. Dateimanager mit nutzbarer Suchzeile, kompakter Werkzeugleiste und passender Aktionsspalte.
- **Stores:** LinuxServer.io bleibt Standard. CasaOS und weitere Community-Stores werden nicht mehr vorgeschlagen. Ein zuvor gespeicherter offizieller CasaOS-Store wird ausgeblendet/deaktiviert; bereits installierte Anwendungen und Daten bleiben erhalten. Eigene bereits importierte Kataloge bleiben zur Verwaltung vorhandener Apps lesbar.

## Update und Rollback

In Einstellungen → Update / Rollback den Alpha-Kanal wählen und auf diese Version aktualisieren. Das signierte Debian-A/B-Systemupdate enthält die Änderungen; kein erneuter IMG-Import ist nötig. Docker-Volumes und Container liegen im persistenten Datenbereich und überleben ein Systemrollback. Ältere Titan-Versionen zeigen neu manuell angelegte Container eventuell noch nicht an; der Docker-Dienst und dessen Neustartregeln bleiben wirksam.

## Prüfungen und Grenzen

Veröffentlichung erfolgt nach Python-/UI-Regressionstests, echtem Debian-QEMU-Runtime-Test einschließlich manuellem Docker-Container mit Datenvolume, gemessenem Gesamt-RAM und Stop/Start/Löschung sowie A/B-Update-/Rollback-Prüfung. Browserkonsole-Transport wird im Runtime-Test geprüft; automatisches Verbinden/Wecken/Wiederverbinden wird zusätzlich als Browser-Controller getestet.

Die Docker-Verwaltung ist eine eigene erste Ausbaustufe, kein vollständiger Dockhand-Nachbau: freie Compose-Stack-Bearbeitung, Registry-Anmeldungen, Container-Terminal und planbare Container-Image-Updates sind noch nicht enthalten. Physische USB-/GPU-Geräte und echte Smartphone-Hardware sind nicht im QEMU-Test verfügbar. Deshalb weiterhin **Alpha**, keine Beta-Freigabe.
