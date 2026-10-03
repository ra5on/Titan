# Titan AppStore und Geräteauswahl

Ab **0.4.14-alpha.1** pflegt Titan seine eigenen Installationsvorlagen. Der Katalog mit 73 Apps (42 eingerichtete Vorlagen und 31 gesperrte Vorlagen in Vorbereitung) liegt im System und wird zusammen mit Titan aktualisiert. Die Oberfläche fragt keine externen AppStore-Kataloge ab; Quellen hinzufügen, Quellenfilter und separate Store-Aktualisierung entfallen. Container-Images werden weiterhin von ihren jeweiligen Herausgebern geladen. Deren Dokumentation, Zugangshinweise und Lizenzen gelten weiterhin.

## Eine App installieren

1. Im Hauptmenü **App Store** öffnen und die App wählen. Suche, Kategorien und A–Z/Z–A helfen beim Finden.
2. Hinweise zum ersten Login lesen. Je nach App legst du den Zugang beim Installieren fest oder richtest ihn beim ersten Öffnen ein. Nicht bestätigte Zugangsdaten werden nicht als garantiertes Standardpasswort ausgegeben.
3. Vorgaben prüfen: Webport, weitere Ports, Datenbereich und Netzwerk. Bridge mit veröffentlichtem Webport ist der einfache Standard. Ein eigenes Netzwerk oder Host-Netzwerk ist gezielt auswählbar.
4. Bei Bedarf tatsächlich erkannte Geräte auswählen. Ohne Auswahl bekommt die App keinen Gerätezugriff.
5. Installieren. Unter **Docker** den Container anklicken, um App öffnen, Einstellungen, Stoppen, Neustarten und Logs direkt zu erreichen.

Mehrere Dienste einer App laufen zusammen in ihrem isolierten Standardnetz. Zugangsdaten werden separat mit privaten Dateirechten gespeichert und nicht in der Containerübersicht ausgegeben. Die Vorlagen geben keine beliebigen Hostpfade, den Docker-Socket oder privilegierten Containerzugriff frei. Lokale App-Bildsymbole benötigen keine externen Logo-Abfragen.

## USB, Grafik und NPU

Die Auswahl zeigt Hersteller, Modell und verfügbare Seriennummer sowie den tatsächlichen Linux-Gerätepfad. Nach erneutem Anstecken eines USB-Geräts seine Zuordnung überprüfen. Ein fehlendes oder neu zugeordnetes Gerät verhindert einen neuen App-Start, bis die Auswahl korrigiert wurde; Stoppen und Entfernen bleiben möglich.

- Intel-/AMD-Grafik erscheint, wenn ein Rendergerät mit aktivem Kernel-Treiber vorhanden ist. AMD-Compute kann zusätzlich `/dev/kfd` benötigen.
- NVIDIA-GPUs werden mit ihrer konkreten Kennung angeboten, wenn Treiber und NVIDIA Container Runtime einsatzbereit sind.
- NPUs erscheinen über tatsächlich vorhandene `/dev/accel/accel*`-Geräte. Mehrere Geräte sind gemeinsam wählbar, beispielsweise Intel-Grafik und NPU.

Die App selbst benötigt passende Beschleunigungssoftware. Die Geräteauswahl installiert keine GPU-/NPU-Treiber und garantiert keine Unterstützung durch jedes Container-Image. In Proxmox muss die Hardware zuerst der Titan-VM zugewiesen werden. Physische Geräte stehen den automatisierten QEMU-Tests nicht zur Verfügung.

## Geräte nachträglich ändern

**App-Einstellungen → Geräte ändern**: App zuerst stoppen, Geräte auswählen und speichern. Titan legt die verwalteten Container mit der neuen Zuordnung an; gespeicherte App-Daten bleiben erhalten. Anschließend die App starten. Schlägt die Neuanlage fehl, wird die vorherige Konfiguration wiederhergestellt; ein gemeldeter Wiederherstellungsfehler muss über Status und Logs geprüft werden.

Bei manuell mit Titan erstellten Containern bietet das Aktionsmenü **Einstellungen & Geräte**. Für unterstützte Konfigurationen erstellt Titan eine lokale Kopie der beschreibbaren Dateischicht, verwendet dasselbe Datenvolume und startet den neuen Container. Der vorherige Container bleibt gestoppt als Sicherung erhalten. Erst nach erfolgreicher Prüfung kann er unter Weitere Aktionen entfernt werden. Das gemeinsame Datenvolume ist kein unabhängiges Backup. Fremde Container und individuell komplexere Konfigurationen werden nicht automatisch umgebaut.

## Vorhandene Apps und Rollback

Bereits installierte Anwendungen aus älteren externen Quellen bleiben zur Verwaltung verfügbar. Neue externe Stores können nicht mehr über die Oberfläche hinzugefügt oder aktualisiert werden. Bestehende Quellendaten werden für diese Kompatibilität und ältere Systemstände aufbewahrt.

Ein Betriebssystem-Rollback setzt App-Daten oder neue Geräteeinstellungen nicht zurück. Insbesondere ältere Versionen können neue NPU-Zuordnungen nicht vollständig bearbeiten. Vor dem Wechsel Hardware-Konfigurationen prüfen und unabhängige Sicherungen behalten.
