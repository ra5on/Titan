# Titan AppStore und Geräteauswahl

Titan verwendet seine eigene Docker-Verwaltung für lokale Container und zusammengehörige Compose-Stacks. Unter **App Store → BigBear-Katalog → BigBear-Katalog laden** wird der externe Katalog ausdrücklich aktiviert. Unterstützte Vorlagen erscheinen danach neben vorhandenen Titan-Paketen.

## BigBear

Der Import verarbeitet `compose.yaml`/`compose.yml` und `metadata.json` aus einer festgelegten Git-Version des BigBear-Dockge-Katalogs. Downloads und YAML-Dokumente sind begrenzt; YAML-Aliase, externe Netze, privilegierte Container und Host-Systempfade werden nicht freigegeben. Nicht unterstützte Vorlagen werden im Katalogdialog mit Begründung aufgelistet. Es wird keine Dockge- oder Dockhand-Anwendung benötigt.

Vor der Installation: Speicherbereich per Dropdown, Webport, weitere Ports und benötigte Zugangsdaten wählen. Mehrere Dienste erhalten ein privates gemeinsames Netz. Datenbank-Passwörter werden in korrespondierenden Diensten gemeinsam eingestellt; veröffentlichte Standardpasswörter werden nicht übernommen. Vorgaben aus Vorlagen werden angezeigt, ersetzen aber nicht die Prüfung auf Portkonflikte und RAM-Reserve.

Installierte Vorlagen werden separat eingefroren und nach einem Agent-Neustart wiederhergestellt. Katalogaktualisierung oder Deaktivierung verändert keine installierte App. Im Paketzentrum sind alle Dienste, Start/Stop/Neustart, Protokolle und Einstellungen verfügbar. Deinstallation entfernt Container, behält aber Daten. Eine Sicherung stoppt die Dienste und enthält die Konfiguration mit internen Datenbanken; separate Nutzdaten zusätzlich sichern.

Die Katalogvorlagen und deren Logos werden nicht mit Titan ausgeliefert. Eine ausdrückliche kommerzielle Weitergabefreigabe für den BigBear-Katalog wurde noch nicht verifiziert. Vor kommerzieller Auslieferung die Rechte am Katalog und an den einzelnen Anwendungen klären. Die technische Importprüfung bestätigt keine uneingeschränkte Lizenz oder Funktionsfähigkeit sämtlicher Apps.

## Vorhandene Titan-Pakete

| Paket | Automatisch enthalten | Erste Anmeldung |
| --- | --- | --- |
| Immich | Immich Server 3.2.4, Machine Learning 3.2.4, PostgreSQL mit VectorChord, Valkey | Konto beim ersten Öffnen anlegen |
| AdGuard Home | AdGuard Home 0.107.79 mit persistenten Einstellungen | Konto im Assistenten anlegen; internen Webport 3000 beibehalten |
| Pi-hole | Pi-hole 2026.09.0 mit persistenten Einstellungen | Gewähltes Web-Passwort unter `/admin/` |
| Nextcloud mit optionalem Euro-Office | Nextcloud 35, PostgreSQL 17, Redis 7, Cron; optional Euro-Office 9.3.4-hotfix.1 und Nextcloud-Connector | Gewählter Nextcloud-Administrator und Passwort |

Datenbank- und Office-Schlüssel erzeugt Titan automatisch. Erneutes Starten und Wiederinstallation mit erhaltenen Daten behalten diese internen Schlüssel. Nextcloud richtet seinen Administrator nur bei einer neuen Datenbank ein; vorhandene Konten bleiben bestehen. Datenbanken sind ausschließlich im internen Paketnetz erreichbar.

Die Oberfläche lädt den BigBear-Katalog nach ausdrücklicher Aktivierung. Container-Images und der Nextcloud-Connector werden von ihren Herausgebern heruntergeladen. Ihre Lizenzen gelten unverändert. Die früheren Rezepte bleiben intern für bestehende Installationen und Rollback erhalten.

AdGuard und Pi-hole benötigen beide Port 53/TCP und UDP. Für den normalen Heimnetzbetrieb eines der Pakete wählen; auf derselben NAS-IP können sie nicht gleichzeitig diesen Port belegen. Alternative veröffentlichte Ports sind einstellbar, müssen aber auch von den DNS-Clients unterstützt werden.

Die Installation prüft das aktuelle RAM-Budget einschließlich laufender Apps, aktiver VMs und NAS-Reserve vor dem Download. Nextcloud enthält standardmäßig Datenbank, Cache und Hintergrundaufgaben; Office ist separat auswählbar und benötigt zusätzlichen RAM. Auf einem 8-GiB-NAS zunächst ohne Office testen. Die tatsächlichen Containergrenzen und das berechnete Budget zeigt der Installationsdialog. Datenbanken und Konfigurationen liegen lokal im geschützten App-Verzeichnis; der gewählte Datenbereich enthält die Nutzdaten. Bei Wahl einer Freigabe bekommt das Paket darin einen eigenen Unterordner `Titan-Apps/<Paketkennung>`. Die App-Sicherung stoppt alle laufenden Paketdienste vor dem Sichern der Konfiguration einschließlich Datenbank. Nutzdaten separat sichern.

### Dokumente bearbeiten

Mit gewähltem Office-Zusatz verbindet das Nextcloud-Paket Euro-Office automatisch und prüft die Verbindung. Danach öffnet Nextcloud unterstützte Dokumente direkt im Browser. Die NAS-Adresse wird im Installationsdialog vorausgefüllt; ändern, wenn die dort verwendete Adresse vom Endgerät nicht erreichbar ist. Standardmäßig sind Nextcloud und Office lokale HTTP-Dienste; für HTTPS-Zugriff beide über einen Reverse-Proxy bereitstellen und die öffentliche Office-Adresse in Nextcloud anpassen. Zertifikatsprüfungen werden nicht deaktiviert.

Nach Einrichtung des Office-Pakets bietet der Titan-Dateimanager die integrierte Dokumentbearbeitung unterstützter Dateien an. Der eigene Connector prüft Dateiberechtigungen, befristete Tokens, Bearbeitungssperren und Versionen vor dem Rückspeichern. Dokumentabruf, Konvertierung, signiertes Speichern und erhaltene Dateirechte werden im echten Pakettest geprüft; die interaktive Bearbeitung auf dem eigenen NAS bleibt Teil der Beta-Abnahme.

Quellen: [Immich Compose](https://docs.immich.app/install/docker-compose/), [AdGuard Docker](https://github.com/AdguardTeam/AdGuardHome/wiki/Docker), [Pi-hole Docker](https://docs.pi-hole.net/docker/), [Nextcloud Docker](https://github.com/nextcloud/docker), [Euro-Office Connector](https://github.com/Euro-Office/eurooffice-nextcloud).

## Eine App installieren

1. Im Hauptmenü **App Store** öffnen und die App wählen. Suche, Kategorien und A–Z/Z–A helfen beim Finden.
2. Hinweise zum ersten Login lesen. Je nach App legst du den Zugang beim Installieren fest oder richtest ihn beim ersten Öffnen ein. Nicht bestätigte Zugangsdaten werden nicht als garantiertes Standardpasswort ausgegeben.
3. Vorgaben prüfen: Webport, weitere Ports, Datenbereich und Netzwerk. Bridge mit veröffentlichtem Webport ist der einfache Standard. Ein vorhandenes eigenes Netzwerk oder Host-Netzwerk ist gezielt auswählbar. Unter **Netzwerk anpassen → Eigenes Bridge-Netz erstellen** genügt ein Name; Titan wählt ein freies privates IPv4-Subnetz. Nach erfolgreichem Anlegen wird das neue Netz direkt ausgewählt. Subnetz, Gateway und rein interne Kommunikation sind optional unter den erweiterten Einstellungen einstellbar.
4. Bei Bedarf tatsächlich erkannte Geräte auswählen. Ohne Auswahl bekommt die App keinen Gerätezugriff.
5. Installieren. Unter **Docker** den Container anklicken, um App öffnen, Einstellungen, Stoppen, Neustarten und Logs direkt zu erreichen.

Mehrere Dienste einer App laufen zusammen in ihrem isolierten Standardnetz. Zugangsdaten werden separat mit privaten Dateirechten gespeichert und nicht in der Containerübersicht ausgegeben. Die Vorlagen geben keine beliebigen Hostpfade, den Docker-Socket oder privilegierten Containerzugriff frei. Lokale App-Bildsymbole benötigen keine externen Logo-Abfragen.

## Netzwerk verwalten

Unter **Docker → Netzwerke** findest du eigene, eingebaute und von Apps verwendete Netze. Die Details zeigen die verbundenen Container und zugeordneten App-Pakete. Ein eigenes Bridge-Netz kann nur entfernt werden, wenn es von keinem Container und keinem installierten App-Paket mehr verwendet wird; die Bestätigung erfolgt mit Ja/Nein. Ein gestopptes App-Paket gibt seine Netzwerkzuordnung nicht automatisch frei. System- und App-Netze werden nicht über diese Löschaktion entfernt.

Titan prüft ein angegebenes oder automatisch gewähltes Subnetz gegen vorhandene Docker-Netze und Host-Routen. Eigene Macvlan-, Overlay- oder IPv6-Netze werden hier nicht angelegt. Ein internes Netz beschränkt normale externe Verbindungen; wähle es nur für Apps, deren benötigte Verbindungen damit weiterhin erreichbar sind.

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
