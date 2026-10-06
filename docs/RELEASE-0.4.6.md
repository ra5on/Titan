> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.6 · Alpha · Hauptmenü und anpassbare Appfenster

Die globale linke Seitenleiste entfällt vollständig. Titan wird über das übersichtliche Hauptmenü und beschriftete Schaltflächen für Hauptmenü, Meldungen, Aufträge und Konto bedient.

Alle Apps verwenden einen gemeinsamen Fensterrahmen mit begrenzten Standardmaßen, eigenem Scrollbereich, Maximieren, Wiederherstellen und Schließen. Auf breiten Desktops lässt sich die Größe rechts unten verändern. Die Maximierungswahl bleibt pro Benutzer und App gespeichert. Manuell veränderte Fenstergrößen bleiben während der Sitzung auch bei Ordnerwechseln und Inhaltsaktualisierungen erhalten. Auf kleinen Bildschirmen verwenden die Apps automatisch den verfügbaren Platz; frühere Desktopgrößen können das nicht verhindern.

App- und Einstellungs-Kacheln erhalten ein gleichmäßiges Raster. Mehr Bildschirmbreite erzeugt zusätzliche Spalten. Docker- und VM-Manager passen ihre Navigation und Inhaltsaufteilung auch an manuell verkleinerte Fenster an. Dateibefehle bleiben beim Scrollen stehen. App Store, Einstellungen, Speicher, Freigaben, Benutzer, Backups, Dienste, Meldungen, Updates, Aufträge, Protokoll und Terminal verwenden denselben Rahmen.

Die isolierte Browserprüfung umfasst alle 16 Verwaltungsseiten sowie das Hauptmenü auf schmalen Mobilgeräten und großen Desktops, zusätzliche Tablet-/Querformatprüfungen, manuelles Verkleinern bis 640 px, Maximieren/Wiederherstellen, VM-CPU-Auswahl, Docker-Details und Dateibearbeitung. 973 Python-Tests bestanden (ein historischer ISO-Fixture übersprungen), 25 Node-Testsuiten und die Syntax der 17 Browser-JS-Dateien waren erfolgreich. Die Veröffentlichung setzt zusätzlich die bestehenden Start-, Laufzeit- und Signaturprüfungen voraus.

**Installation über den Alpha-Update-Kanal:** Nach Updates suchen, v0.4.6 vorbereiten, den Neustart ausdrücklich ausführen und danach die Browserseite neu laden. Ein neues Installations-IMG ist nicht erforderlich.

**Titan bleibt Alpha.** Der manuelle Proxmox-/Hardwaretest und der vollständige OS-Update-/Neustart-/Rollback-Zyklus bleiben Voraussetzungen für die Beta.
