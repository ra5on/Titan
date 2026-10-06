# Titan 0.5.2 Alpha · Einheitliche Verwaltung

Titan erhält zusammenhängende Arbeitsflächen für Dateien, virtuelle Maschinen, Docker und Speicher. Die Anordnung orientiert sich am Bedienprinzip von Synology DSM: klare Bereiche, eine Auswahl mit zugehörigen Details und sichtbare Aktionen. Titan bleibt bis zur Abnahme auf einem echten NAS **Alpha**.

Das vollständige Systemupdate **0.5.2-alpha.1** aktualisiert bestehende Installationen über **Systemsteuerung → Updates & Rollback → Alpha → Jetzt prüfen**. Die Veröffentlichung setzt bestandene App-, Gast- und signierte Update-/Rollback-Prüfungen voraus. Ein neues Installationsimage ist nicht Teil dieser Version.

## Was sich ändert

- **Dateimanager:** Die Ortsspalte kann links oder rechts stehen. Ihre Breite lässt sich mit dem Griff zwischen 160 und 360 Pixeln ziehen; die persönliche Anordnung bleibt gespeichert. Passende Symbole kennzeichnen Orte und Dateitypen. Mobil öffnet die Ortsspalte als Schublade, damit die Dateiliste den verfügbaren Platz nutzt.
- **Virtuelle Maschinen:** VM-Auswahl und Details bilden eine gemeinsame Arbeitsfläche. Übersicht, Hardware, Netzwerk und Sicherungen gehören zur ausgewählten Maschine. Die integrierte Konsole nutzt eine eigene volle Ansicht statt eines halben scrollenden Fensters; Schnellaktionen bleiben gut erreichbar.
- **Docker:** Der Container Manager trennt Übersicht, Projekte, Container, Images, Netzwerke und Volumes. Projekte gruppieren zusammengehörige App-Dienste und Stacks. Auswahl, Status und Aktionen stehen zusammen; Container- und Paketaktionen behalten ihren jeweiligen Umfang.
- **Eigene Docker-Netze:** Für ein neues Bridge-Netz genügt ein Name. Titan ermittelt ein freies privates IPv4-Subnetz anhand vorhandener Docker-Netze und Host-Routen. Subnetz, Gateway und rein interne Kommunikation können unter den erweiterten Einstellungen gesetzt werden. Die Liste zeigt Adressen, verbundene Container und zugeordnete App-Pakete. Nur ungenutzte eigene Netze sind mit Ja/Nein entfernbar; Systemnetze und verwendete Netze bleiben geschützt.
- **Speicher:** Der Speicher-Manager erhält Übersicht, Speicherbereiche, HDD/SSD und Wartung. Systemkapazität und tatsächlich eingerichtete Datenbereiche sind sichtbar. Nicht verbundene Volumes bleiben zur Verwaltung verfügbar, ohne erfundene Belegungswerte. ZFS-Datenbereiche stehen unter ihrem Pool und werden in der Gesamtübersicht nicht als zusätzliche Kapazität gezählt. SMART zeigt verständliche Zustandswerte; technische Rohdaten bleiben optional.
- **Gemeinsame Oberfläche:** Helle, kompakte Bedienelemente, einheitliche Abstände und passende Skalierung verbinden die Verwaltungsbereiche. Bestehende Aktionen für Benutzer, Systemsteuerung, Dienste, Updates, Datensicherung und Meldungen bleiben erhalten.

## Grenzen und Abnahme

Eigene Netze sind in dieser Oberfläche Bridge-Netze mit IPv4-Konfiguration. Macvlan-, Overlay- und IPv6-Netze werden nicht neu eingerichtet. Ein Netzwerkwechsel bestehender Container wird hier nicht automatisch vorgenommen. Auch ein gestoppter Container oder ein installiertes App-Paket kann ein Netz noch verwenden; diese Zuordnung muss zuerst aufgelöst werden.

Laufwerkszustand und Temperatur erscheinen nur, wenn Hardware und Controller Werte liefern. Virtuelle Laufwerke können keine SMART-Daten bereitstellen. Vorhandene Schutzprüfungen für Speichererstellung, Systemvergrößerung und RAM-Budgets bleiben aktiv. Die neue Oberfläche ersetzt weder eine unabhängige Datensicherung noch Lasttests auf dem eigenen NAS.

Vor einer Beta-Freigabe die Seitenleiste auf Desktop und Mobilgeräten bedienen, eine VM samt integrierter Konsole testen, ein eigenes Docker-Netz erstellen und nach Auflösen aller Zuordnungen entfernen sowie Speicherbereiche, SMART und Wartung prüfen. Die tatsächliche Browserprüfung und die signierten GitHub-/Gastprüfungen sind im [Prüfnachweis](QA-0.5.2.md) getrennt dokumentiert.

[Beta-Abnahme](BETA.md) · [Docker](DOCKER-WORKBENCH.md) · [AppStore und Netzwerke](APP-STORES.md)
