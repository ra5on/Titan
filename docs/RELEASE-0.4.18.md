# Titan 0.4.18 · App-Pakete, mobile Dateien und Benutzerverwaltung

## Dateimanager

Auf Mobilgeräten scrollen Orte, Werkzeugleiste und Dateiliste in einer gemeinsamen Fläche. Die automatische Detailspalte entfällt dort. Bei Auswahl bleiben Kopieren, Verschieben, Löschen, Umbenennen, Bearbeiten und Öffnen oben erreichbar. Suche und Ansicht sind aufklappbar. Rechte und Mehrfachauswahl bestimmen, welche Aktionen verfügbar sind. Löschen wird weiterhin mit Ja/Nein bestätigt. Desktop-Vorschau und Tastatursteuerung bleiben erhalten.

## AppStore

Vier Angebote ersetzen den bisherigen Katalog: Immich mit Datenbank, Valkey und Bilderkennung; AdGuard Home; Pi-hole; Nextcloud mit PostgreSQL, Redis, Hintergrundaufgaben und Euro-Office. Bestehende App-Installationen bleiben verwaltbar, Daten werden nicht entfernt. Neue Pakete verwenden eigene Kennungen, damit vorhandene Container ihre Konfiguration behalten.

Die Installation erzeugt interne Schlüssel einmalig, richtet Abhängigkeiten ein und wartet auf deren Bereitschaft. Ein Fehler bei der Office-Einrichtung bleibt als Fehler sichtbar; Starten versucht die Einrichtung erneut. Bei App-Sicherungen werden auch laufende Datenbankdienste gestoppt und anschließend nur die zuvor laufenden Dienste gestartet. Datenbanken bekommen keine öffentlichen Ports. AdGuard/Pi-hole-Portkonflikte werden vor dem Anlegen erkannt.

## Prüfung und Grenzen

Python- und JavaScript-Regressionstests prüfen insbesondere Geheimnisse, Wiederholungen, Portkonflikte, Rechte und erhaltene Altinstallationen. Browserprüfung bei 390 und 320 Pixel Breite mit 36 Dateien, Auswahlleiste und Ja/Nein-Abbruch. Desktopansicht wird separat geprüft. Dies ersetzt keinen Test auf einem echten iPhone mit Safari.

Ein neuer verpflichtender GitHub-Test startet jedes Paket auf einem separaten Docker-Runner, prüft HTTP-Erreichbarkeit und Neustart; beim Nextcloud-Paket zusätzlich Installation des Office-Connectors und Verbindungsprüfung. Erst nach grünen Pakettests beginnt der signierte Systembuild mit den bisherigen Boot-, Update- und Rollback-Prüfungen. Ein Push allein bestätigt noch keine Veröffentlichung.

Euro-Office arbeitet innerhalb Nextclouds. Die direkte Office-Bearbeitung beliebiger Dateien aus Titans Dateimanager ist noch nicht enthalten. Physische GPU-/USB-Beschleunigung wird von den Pakettests nicht geprüft. Titan bleibt Alpha.

## Benutzerverwaltung und Systemsteuerung

Die Benutzerverwaltung erhält eine auswählbare Liste mit Suche, Rollen-/Statusfilter und einer Detailansicht. Anzeigename und Beschreibung lassen sich speichern. Kontoeinstellungen und SMB-Freigaberechte sind getrennte Register: pro Ordner Lesen und Schreiben, Lesen oder kein Zugriff. Beim Ändern bleiben die Rechte anderer Konten erhalten. Konto- und Freigabenänderungen sind getrennte Aufträge; ein Fehler wird mit dem betroffenen Ordner angezeigt. Administratorrollen geben Verwaltungszugang, während SMB weiterhin die ausdrücklich eingetragenen Freigaberechte nutzt.

In der Systemsteuerung lassen sich häufige Bereiche als Favoriten merken und Symbole oder eine Liste mit Beschreibungen wählen. Diese Ansichtsoptionen werden im Browser pro Benutzer gespeichert. Auf Mobilgeräten dient die Bereichsauswahl als Navigation.

Der Systemtest für externe Compose-Importe ist an den kuratierten Katalog angepasst: Importantwort und installierte Rezeptmetadaten werden geprüft. Installation, HTTP-Erreichbarkeit, Metriken, Stapelsteuerung und Entfernen werden weiter mit echten Containern getestet.

Die Struktur orientiert sich an [Synologys Benutzerverwaltung](https://kb.synology.com/index.php/en-us/DSM/help/DSM/AdminCenter/file_user_desc?version=7) und dem [DSM-7.2-Leitfaden](https://global.download.synology.com/download/Document/Software/UserGuide/Os/DSM/7.2/enu/Syno_UsersGuide_NAServer_7_2_enu.pdf). Gruppen, Speicherquoten und delegierte Administratorrollen sind noch nicht enthalten.
