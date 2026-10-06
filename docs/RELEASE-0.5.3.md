# Titan 0.5.3 Alpha · Gemeinsamer Datenspeicher und Anmeldeschutz

Titan verwendet eine gemeinsame Speicherauswahl für Dateien, Apps, Docker,
virtuelle Maschinen, Freigaben und Sicherungen. Die Dialoge folgen der bestehenden
Systemsteuerung und dem Speicher-Manager: Bereich auswählen, Einstellungen
prüfen, Aktion bestätigen. Titan bleibt bis zur Abnahme auf dem eigenen NAS
**Alpha**.

## Speicher wählen

- **Interner Speicher** bezeichnet den Datenbereich auf der Installations-SSD.
  Die beiden Betriebssystempartitionen gehören nicht zur Dateiauswahl.
- Verwaltete **Ext4-/XFS-Volumes** und **ZFS-Pools** erscheinen mit ihrem Namen,
  Dateisystem und verfügbarer Kapazität. Technische Pfade sind keine Voraussetzung
  für die normale Einrichtung. ZFS-Werkzeuge und das zum ausgelieferten Kernel
  gebaute Modul gehören zum Systemupdate. Der ZFS-Cache ist zunächst auf maximal
  1 GiB begrenzt; das ersetzt nicht die RAM-Vorprüfung für Apps und VMs.
- Unter **Speicher → Einstellungen → Standardspeicher** den Ort für neue Daten
  wählen. Die Auswahl gilt für neue Apps, manuelle Container, Freigaben und
  VM-Laufwerke. Bestehende Installationen bleiben an ihrem bisherigen Ort.
- Neue App-Pakete legen auch Konfiguration, Datenbanken und Cache auf dem
  ausgewählten Speicher ab. Die zugehörigen Verwaltungsmetadaten bleiben im
  geschützten Titan-Bereich. Sicherungen berücksichtigen die ausgelagerte
  App-Konfiguration.
- Offline-, ausgetauschte oder volle Speicher werden ausdrücklich angezeigt.
  Titan wechselt nicht automatisch auf die interne SSD. Ein voller, weiterhin
  verbundener Speicher bleibt zum Durchsehen und Löschen zugänglich.
- Sicherungsziele verwenden einen eigenen Bereich auf einem geeigneten,
  von den Quellen getrennten Datenträger. Derselbe Datenträger ist keine
  unabhängige Sicherung.

## Systemdateien schützen

Der Dateimanager zeigt NAS-Daten und freigegebene persönliche Ordner. Auch
Webadministratoren können darüber keine Betriebssystemdateien lesen oder
bearbeiten. Alte Favoriten auf Systempfade werden nicht wieder geöffnet.
Geprüfte Einhängepunkte und Datenträgerkennungen verhindern Zugriffe auf einen
leeren Ersatzordner nach dem Ausfall eines Volumes oder Pools.

Das Web-Terminal läuft als eingeschränktes Dienstkonto mit unterbundener
Privilegienerhöhung. Neue eigene Dienste laufen ohne Rootrechte und erhalten
Schreibzugriff nur auf ihren geprüften Datenordner. Ältere eigene Rootdienste werden vor dem Start der Verwaltung deaktiviert
und angehalten. Ihre Unit-Dateien und Daten bleiben erhalten; Start und Autostart
bleiben über die Oberfläche gesperrt. Dies beschränkt die
Titan-Verwaltung, ersetzt jedoch keine Kontrolle über einen separat eingerichteten
Root-/SSH-Zugang. Der laufende Systembereich wird mit diesem Update nicht als
vollständig schreibgeschütztes Dateisystem umgebaut.

## Anmeldeschutz

Unter **Systemsteuerung → Sicherheitszentrum → Anmeldeschutz** Anzahl der
Fehlversuche, Beobachtungszeitraum und Sperrdauer einstellen. Standard sind
fünf Fehlversuche innerhalb von fünf Minuten und eine Sperre für 15 Minuten.
IP-Schutz und Schutz eines Kontos von einer bestimmten Clientadresse lassen
sich getrennt aktivieren. Fehler bei Passwort und zweitem Faktor zählen mit.

Sperren überstehen einen Dienstneustart, laufen automatisch aus und können von
einem angemeldeten Administrator aufgehoben werden. Die Anmeldung zeigt die
verbleibende Wartezeit. Ein gesperrter Zugriff verlängert die bestehende Sperre
nicht bei jedem neuen Versuch.

## Debian-Pflege im gemeinsamen Updateweg

**Updates & Rollback** bietet einen gemeinsamen Ablauf: **Jetzt prüfen → Update
installieren → Neu starten und aktivieren**. Ein Angebot kennzeichnet, ob es
Titan-Funktionen oder Debian-Systempflege enthält. Ein globaler Zeitplan steuert
die automatische Prüfung und Vorbereitung; ein Neustart bleibt bestätigt.

Ein täglicher GitHub-Lauf prüft offizielle Debian-Paketquellen gegen die signierte
Paketliste veröffentlichter Systemstände. Für Debian-Pflege wird derselbe
Titan-Anwendungsstand eingefroren, ein neues vollständiges A/B-System gebaut und
mit Paket-, Laufzeit-, Update- und Rollback-Prüfungen abgesichert. Erst danach
wird das signierte Update veröffentlicht. Das NAS selbst führt kein getrenntes
Live-APT-Upgrade aus. Ein Rollback stellt auch den damaligen Sicherheitsstand
wieder her; Nutzdaten und Datenbanken werden nicht zurückgesetzt.

## Prüfen auf deinem NAS

Nach dem Update einen zusätzlichen Testdatenträger als Volume oder Pool
einrichten, zum Standard wählen und dort eine Freigabe, App und VM anlegen.
Vorhandene Daten müssen unverändert bleiben. Anschließend einen getrennten
Datenträger als Sicherungsziel wählen. Ausfalltests ausschließlich mit
Wegwerfdaten durchführen. Anmeldeschutz mit einer zweiten angemeldeten
Administratorsitzung testen, damit eine Sperre direkt aufgehoben werden kann.

Ein neues Installations-IMG ist nicht Teil dieser Version. Der tatsächliche
Veröffentlichungs- und Prüfnachweis steht in [QA-0.5.3](QA-0.5.3.md).

[Speicherverwaltung](STORAGE.md) · [Anmeldeschutz](IDENTITY-SECURITY.md) ·
[Updates und Rollback](UPDATES.md) · [Beta-Abnahme](BETA.md)
