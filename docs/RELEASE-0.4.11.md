# Titan 0.4.11-alpha.1 · Dateimanager, anpassbare Übersicht und App-Verbünde

Bestehende Debian-A/B-Installationen aktualisieren über **Einstellungen → Updates & Rollback → Alpha**. Dieses Release liefert ein signiertes Systemupdate; kein neues Installationsimage und kein erneuter Import in Proxmox erforderlich.

## Bedienung und Oberfläche

- Der Dateimanager beginnt für Administratoren bei **NAS-Dateien**. Systemdateien bleiben über „System /“ erreichbar. Textdateien jeder Endung bearbeiten, Dateien mit getrenntem Namen und Endung erstellen, Ordner anlegen, Vorschau, Mehrfachauswahl, Kopieren/Ausschneiden/Einfügen über verschiedene Ordner, Umbenennen, Sortierung, versteckte Dateien und Listen-/Symbolansicht.
- Lösch-, Deinstallations-, Rollback- und Neustartbestätigungen haben **Ja / Nein**. Namen, Pfade oder Bestätigungswörter müssen nicht mehr eingetippt werden. Serverseitige Zuordnungsprüfungen bleiben erhalten.
- Die Hauptübersicht nutzt die volle Breite. Kacheln verschieben, verbreitern, ausblenden und über Vorschläge wieder hinzufügen; Menü-Werkzeuge und Apps auswählen und in Ordnern gruppieren. Die Auswahl wird pro Benutzer gespeichert. Die rechte Statusspalte entfällt.
- **System** öffnet Neustart, Ausschalten, Updates und Einstellungen. Laufende VMs vorher herunterfahren.
- Durchgehende Größenanpassung der Verwaltungsfenster, kompakte mobile Ansichten, lokale Tabellen-Scrollbereiche, passende Dialogbreiten und größere Touch-Flächen. Animationen berücksichtigen reduzierte Bewegung.

## Virtuelle Maschinen und Docker

- VM-CPU, RAM, tatsächlich zugewiesene Laufwerksblöcke, Laufwerks-I/O und Netzwerkwerte werden alle fünf Sekunden aktualisiert. CPU-Auslastung bezieht sich auf die zugewiesenen vCPUs; Gast-RAM benötigt Balloon-Statistiken. Ohne diese zeigt Titan gesondert den Host-RAM der VM. Fehlende Messungen bleiben leer.
- VMs pausieren/fortsetzen und ausgeschaltete QCOW2-Laufwerke vergrößern. Danach Partition und Dateisystem **innerhalb des Gasts** erweitern. Bestehende CPU-Zuordnung, BIOS/UEFI, Image-Auswahl, Netzwerk, USB und integrierte Konsole bleiben verfügbar.
- Docker zeigt gemessene CPU-/RAM-Werte und kumulierte Laufwerks-I/O; bei Containerverbünden werden alle verifizierten Dienste summiert. Dies ist keine Messung des Platzverbrauchs innerhalb des Containers.
- Externe CasaOS-Vorlagen können bis zu **acht Container** enthalten. Titan übernimmt statische Kommandos, unterstützte Healthchecks, Abhängigkeiten, Netz-Aliase, Umgebungsoptionen und Ports in eine eigene verwaltete Konfiguration. Verbünde verwenden ein isoliertes App-Netz. Einzelcontainer können Standard, Bridge, eigenes Bridge-Netz oder Host verwenden. Host-Vorgaben bleiben erhalten.
- Nutzdaten-Mounts `/data`, `/media`, `/downloads`, `/files` oder `/storage` werden auf die gewählte Freigabe bzw. den eigenen App-Datenordner gelegt. Weitere Mounts erhalten private App-Verzeichnisse; fremde Hostpfade werden nicht übernommen.
- AppStore-Sortierung **A–Z / Z–A**. Nicht unterstützte Vorlagen bleiben mit Grund sichtbar. Privilegierte Container, Docker-Socket und beliebige Hostgeräte werden weiterhin nicht automatisch importiert.
- Vor der Installation erkannte USB-/serielle Geräte und GPU-Rendergeräte explizit auswählen. NVIDIA wird angeboten, wenn Treiber und NVIDIA-Container-Runtime bereits eingerichtet sind. Titan installiert diese Treiber nicht separat. Entfernte Geräte verhindern einen neuen Start, aber nicht das Stoppen oder Entfernen der App.

## Prüfung und Grenzen

Die Release-Pipeline prüft Python-/API-Regressionen, UI-Verhalten, den tatsächlichen Debian-Boot, HTTPS, Docker-Lebenszyklen einschließlich eines importierten Zwei-Container-Verbunds, VM-Konsole, VM-Messwerte, Laufwerksvergrößerung und Update/Rollback aus dem veröffentlichten 0.4.6-System. Testergebnisse liegen beim GitHub-Release. Physische USB-/GPU-Geräte und echte Gastbetriebssysteme benötigen weiterhin Tests auf passender Hardware; die QEMU-Prüfung ersetzt diese nicht.

**Weiterhin Alpha.** Die neuen Import- und Hardwarepfade brauchen Rückmeldungen aus unterschiedlichen Installationen vor einer Beta-Freigabe.
