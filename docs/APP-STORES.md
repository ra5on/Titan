# Titan AppStore und Geräteauswahl

Titan verwendet seine eigene Docker-Verwaltung für lokale Container und zusammengehörige Compose-Stacks. Der BigBear-Katalog wird auf einem neu eingerichteten NAS automatisch im Hintergrund geladen und lokal gespeichert. Der Verwaltungsdienst und der Desktop warten nicht auf den Download. Im AppStore erscheinen Ladezustand, Verbindungsfehler sowie die Anzahl kompatibler Vorlagen und Vorlagen mit zusätzlichem Einrichtungsbedarf. Eigene Titan-App-Pakete werden nicht mehr angeboten.

Ein vorhandener Katalog ist nach einem Neustart sofort aus dem lokalen Cache verfügbar. Eine ausdrückliche Deaktivierung oder Entfernung bleibt erhalten. Nach einem Verbindungsfehler werden höchstens drei automatische Versuche pro 24 Stunden durchgeführt; die ersten beiden Wiederholungen erfolgen nach einer beziehungsweise fünf Minuten. **Katalog aktualisieren** bleibt für einen gezielten erneuten Versuch verfügbar. Entwicklungs- und Demo-Instanzen laden keinen externen Katalog beim Start.

Einzelne Downloads wiederholen vorübergehende Serverfehler, ausdrückliche Rate-Limits oder unterbrochene Verbindungen höchstens zweimal mit kurzen Wartezeiten. Fehler zeigen beispielsweise den HTTP-Code; Antwortinhalte und Adressen mit möglichen Zugangsdaten werden nicht ausgegeben. Ungültige Vorlagen, Weiterleitungen und Zertifikatsfehler werden dadurch nicht freigegeben.

## BigBear

Der Import verarbeitet `compose.yaml`/`compose.yml` und `metadata.json` aus einer festgelegten Git-Version des BigBear-Dockge-Katalogs. Ein begrenztes Archiv vermeidet hunderte Einzelabrufe und gemischte Versionen. Bis zu 1000 Vorlagen, 16 Dienste pro App und acht private Bridge-Netze pro Stack sind zulässig. Getrennte Netze, interne Netze und DNS-Aliase bleiben getrennt; lokale Netzwerknamen werden pro Titan-Stack isoliert. Externe Netze, IPAM und besondere Netzwerktreiber werden weiterhin nicht automatisch eingerichtet.

Die Docker-Abnahmetests in GitHub verwenden eine ausdrücklich festgelegte BigBear-Commit-ID (`--bigbear-revision`). Dadurch benötigen Testläufe keine anonyme GitHub-API-Abfrage für den aktuellen Branch und prüfen dieselbe Vorlage reproduzierbar. Archivgröße, Parser und Rezeptvalidierung bleiben identisch; der automatische Katalog auf dem NAS ermittelt weiterhin den aktuellen Stand.

Übliche Speichergrößen wie `512MiB` oder `1gb`, zusammengesetzte Zeitangaben wie `1m30s`, Healthchecks als Text sowie numerische Container-Benutzer und `root` werden übersetzt. Unterstützte Schutzoptionen (`read_only`, `init`, `cap_drop`, `no-new-privileges`), temporäre Dateisysteme, Startbedingungen, Stoppsignale und interne Ports bleiben erhalten. Kleine statische Portbereiche werden begrenzt auf einzelne zuordnungsfähige Ports erweitert. Bindeadressen wie `127.0.0.1` bleiben lokal und werden nicht zu einer Freigabe im gesamten Netzwerk erweitert. Dienste ohne Weboberfläche können als Hintergrunddienste installiert werden; sie erhalten keinen erfundenen Webport oder Öffnen-Link.

Nicht unterstützte Vorlagen werden mit einem konkreten Grund und gegebenenfalls benötigten Hostpfaden, Geräten oder Berechtigungen aufgelistet. YAML-Aliase, beliebige privilegierte Container, zusätzliche Fähigkeiten und Docker-Socket-Zugriff werden nicht pauschal freigegeben. Auch ein Administrator erhält diese Rechte nicht stillschweigend durch eine fremde App-Vorlage. Eine als kompatibel importierte Vorlage ist noch keine auf jeder Hardware getestete Anwendung. Es wird keine Dockge- oder Dockhand-Anwendung benötigt.

Vor der Installation: Speicherbereich per Dropdown, gegebenenfalls Webport, weitere Ports und benötigte Zugangsdaten wählen. Mehrere Dienste erhalten die privaten Netzsegmente ihrer Vorlage; ohne besondere Zuordnung ein gemeinsames privates Netz. Datenbank-Passwörter werden in korrespondierenden Diensten gemeinsam eingestellt; veröffentlichte Standardpasswörter werden nicht übernommen. Vorgaben aus Vorlagen werden angezeigt, ersetzen aber nicht die Prüfung auf Portkonflikte und RAM-Reserve.

Installierte Vorlagen werden separat eingefroren und nach einem Agent-Neustart wiederhergestellt. Katalogaktualisierung oder Deaktivierung verändert keine installierte App. Im Paketzentrum sind alle Dienste, Start/Stop/Neustart, Protokolle und Einstellungen verfügbar. Deinstallation entfernt Container, behält aber Daten. Eine Sicherung stoppt die Dienste und enthält die Konfiguration mit internen Datenbanken; separate Nutzdaten zusätzlich sichern.

Ältere gespeicherte Vorlagen erhalten beim Laden korrigierte Passwort-Metadaten, etwa für `BASIC_AUTH_PASS`. Gespeicherte Zugangsdaten werden dadurch nicht geändert; persönliche Werte erscheinen nicht als normale App-Einstellung. Neue Installationen fragen benötigte Passwörter ab.

Neue Katalogdaten und installierte Rezepte werden versioniert gespeichert. Bei einem System-Rollback erhalten ältere Titan-Versionen nur App-Einträge und Rezepte, die ihr Parser versteht. Neu eingeführte Hintergrunddienste, Netzsegmente oder Schutzoptionen bleiben für die ältere Oberfläche ausgeblendet; ihre Container und Daten werden dabei nicht gelöscht. Diese Anwendungen sind nach Rückkehr zur neuen Version wieder verwaltbar. Start-/Stopp- und Deinstallationsänderungen kompatibler Apps während eines Rollbacks werden beim erneuten Wechsel berücksichtigt. Diese Metadatenprüfung ersetzt keinen vollständigen Rollback-Laufzeittest mit den veröffentlichten Images.

Die Katalogvorlagen und deren Logos werden nicht mit Titan ausgeliefert. Eine ausdrückliche kommerzielle Weitergabefreigabe für den BigBear-Katalog wurde noch nicht verifiziert. Vor kommerzieller Auslieferung die Rechte am Katalog und an den einzelnen Anwendungen klären. Die technische Importprüfung bestätigt keine uneingeschränkte Lizenz oder Funktionsfähigkeit sämtlicher Apps.

Bereits installierte frühere Pakete bleiben über Docker verwaltbar. Ihre Kompatibilitätsdefinitionen bleiben für Start, Stop, Sicherung und Deinstallation erhalten; Container und Nutzdaten werden durch die Katalogbereinigung nicht gelöscht.

## Eine App installieren

1. Im Hauptmenü **App Store** öffnen und die App wählen. Suche, Kategorien und A–Z/Z–A helfen beim Finden.
2. Hinweise zum ersten Login lesen. Je nach App legst du den Zugang beim Installieren fest oder richtest ihn beim ersten Öffnen ein. Nicht bestätigte Zugangsdaten werden nicht als garantiertes Standardpasswort ausgegeben.
3. Vorgaben prüfen: Webport, weitere Ports, Datenbereich und Netzwerk. Bridge mit veröffentlichtem Webport ist der einfache Standard. Ein vorhandenes eigenes Netzwerk oder Host-Netzwerk ist gezielt auswählbar. Unter **Netzwerk anpassen → Eigenes Bridge-Netz erstellen** genügt ein Name; Titan wählt ein freies privates IPv4-Subnetz. Nach erfolgreichem Anlegen wird das neue Netz direkt ausgewählt. Subnetz, Gateway und rein interne Kommunikation sind optional unter den erweiterten Einstellungen einstellbar.
4. Bei Bedarf tatsächlich erkannte Geräte auswählen. Ohne Auswahl bekommt die App keinen Gerätezugriff.
5. Installieren. Unter **Docker** den Container anklicken, um App öffnen, Einstellungen, Stoppen, Neustarten und Logs direkt zu erreichen.

Mehrere Dienste einer App laufen in ihren isolierten privaten App-Netzen. Zugangsdaten werden separat mit privaten Dateirechten gespeichert und nicht in der Containerübersicht ausgegeben. Die Vorlagen geben keine beliebigen Hostpfade, den Docker-Socket oder privilegierten Containerzugriff frei. Lokale App-Bildsymbole benötigen keine externen Logo-Abfragen.

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
