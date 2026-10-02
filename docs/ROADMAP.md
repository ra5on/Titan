# Roadmap

## Aktuell: Alpha auf uCore-HCI

Titan besitzt ein vollständiges x86_64-Systemimage mit HTTPS auf Port 5000, vorinstallierten NAS-/Docker-/VM-Komponenten und signierten atomaren Systemupdates. Das öffentlich geprüfte [v0.4.1 IMG](https://github.com/ra5on/Titan/releases/download/v0.4.1/titan-0.4.1-x86_64.img.xz) enthält uCore und Titan vollständig und bleibt der letzte Installationsdownload. Weitere Entwicklungsversionen kommen über den signierten Update-Kanal. Ein neues Installations-IMG veröffentlichen wir später ausdrücklich; es ist kein Pflichtdownload pro Update. Die signierten ISO-Dateien von v0.4.0 bleiben als Archiv erhalten; neue ISO-Builds und die Aufteilung von Downloads entfallen.

## Bisher umgesetzt

- Responsive Oberfläche mit persönlicher Kachelanordnung, Verwaltung nach Aufgaben und Suche.
- Echte CPU-/RAM-Metriken, Sensorkennzeichnung, laufende Uhr, Diagramme und sichtbare Aufträge.
- Speicherziele über Laufwerks-/Freigabenauswahl und Ordnerbrowser; Dienste als Liste mit Details und Steuerung.
- Dateimanager, Benutzer-/Freigabenverwaltung, Webterminal, Backups und Meldungen.
- Vorlagenbasierte Docker-Apps und VM-Verwaltung mit Disk-/Image-/CPU-Auswahl und Browserkonsole.
- Signierte OCI-Systemupdates mit expliziten Boot-/Laufzeitnachweisen; fehlende Nachweise blockieren ein Update. Installations-IMG und laufende Updates werden getrennt veröffentlicht.

## App Store in v0.4.1

Der Katalog enthält **42 kuratierte App-Vorlagen**. Die App-Details erklären den ersten Zugang: bekanntes Anfangskonto, selbst gewählte Zugangsdaten, Einrichtungsassistent oder ein beim Start erzeugtes Passwort. Individuelle gespeicherte Passwörter werden dabei nicht öffentlich angezeigt. Herkunft und Einrichtungshinweise gehören direkt zur App; für den ersten Login soll kein Suchen im Internet nötig sein.

Die Anzahl der Vorlagen ist kein Nachweis, dass alle Apps bereits auf echter NAS-Hardware getestet wurden. Portbelegung, Datenpfade, benötigte Einstellungen und erster Zugriff werden je App geprüft und dokumentiert.

## Als Nächstes: Update und Rückkehr absichern

Zuerst prüfen wir ein echtes signiertes Update auf dem separaten Testsystem: Vorbereiten, manueller Neustart, Anmeldung und Erhalt von Benutzern, Freigaben, Apps und VM-Daten. Danach folgt die Rückkehr zur vorherigen Systemversion samt erneutem Datenvergleich. Die aktuelle Rollback-Steuerung erfolgt über `bootc rollback`; eine verständliche Bedienung mit Status und Bestätigung in der Weboberfläche ist der nächste Ausbau.

## Nächstes Ziel: erste Beta

Die Beta-Freigabe folgt den Nachweisen im [Beta-Plan](BETA.md): IMG-Erststart, echte VM samt Gastbetriebssystem und Browserbedienung, App-Betrieb, Benutzer/SMB-Rechte, Ext4/XFS/ZFS, Backup mit tatsächlicher Wiederherstellung und signiertes Update mit Neustart/Rollback. Zusätzlich müssen Metriken stimmen, Desktop und Mobilgeräte bedienbar sein und ein Dauerlauf ohne kritische Fehler gelingen.

Offene oder übersprungene Hardwareprüfungen werden sichtbar dokumentiert. Ein erfolgreicher CI-Lauf oder mehr App-Kacheln genügt für sich allein nicht zur Beta.

## Danach

- Weitere getestete Apps und Vorschauen für zusätzliche Dateiformate.
- Geführte Übernahme vorhandener Daten und Konfigurationen.
- Erweiterte Hardwareunterstützung, USV und externe Benachrichtigungen.

Diese Erweiterungen blockieren die erste Beta nur, wenn sie für einen vereinbarten Kernablauf notwendig sind. Die bestehenden Kernfunktionen und ihr Betriebsnachweis haben Vorrang.
