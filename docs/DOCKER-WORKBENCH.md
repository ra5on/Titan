# Docker direkt verwalten

Docker im Hauptmenü öffnet Titans eigene Verwaltung: Container, Images, Netzwerke und Volumes. Es wird keine fremde Docker-Oberfläche gestartet und keine Telemetrie eingebaut. Der Browser kommuniziert ausschließlich mit dem angemeldeten Titan-Backend; Docker hat keinen öffentlich freigegebenen API-Port.

1. Unter **Volumes** bei Bedarf ein lokales Datenvolume anlegen.
2. **Container erstellen**: Namen und Image, z. B. `nginx:stable`, eintragen. Bridge ist Standard; bei Host/Ohne Netzwerk die Portzuordnungen leer lassen. Eigene vorhandene Netze stehen in der Auswahl.
3. Ports zeilenweise als `8080:80/tcp`, Umgebung zeilenweise als `NAME=Wert` eintragen. Datenvolume aus der Liste wählen und das Ziel innerhalb des Containers setzen. USB/GPU/NPU werden ausschließlich nach erkannter, expliziter Auswahl durchgereicht.
4. Erstellen & starten. Aktionen zeigen ihren Status direkt im Bereich. Bei einem Startfehler bleibt ein erfolgreich angelegter Container zur Diagnose/erneuten Startauslösung erhalten.
5. Details & Logs zeigt Adressen, Ports, Neustartregel, Datenzuordnungen und letzte 150 Logzeilen. Umgebungsvariablen und deren Passwörter werden nicht in der Übersicht oder im Diagnose-JSON veröffentlicht.

Entfernen verwendet keine Force-/Prune-Aktionen. Erst stoppen; danach bleibt das Datenvolume erhalten. Ein Volume separat zu löschen entfernt dessen Daten endgültig und erfordert Ja/Nein-Bestätigung. Docker lehnt das Entfernen noch verwendeter Volumes und Images ab.

Vorlagen-Apps sind zusätzlich sichtbar. Ihre Aktionen werden an den bestehenden Titan-App-Manager weitergegeben; dessen Prüfung von Images, Netzwerk und Datenpfaden bleibt erhalten. Für einen Containerverbund wirkt die App-Aktion auf die gesamte zugehörige App.

RAM wird einschließlich Dateicache aus Linux-Cgroups gemessen. Wenn diese Messung nicht verfügbar ist, erscheint „—“. Gestoppte Container zeigen 0 B. Ein Docker-RAM-Limit ist eine Obergrenze, kein Verbrauchswert.

Die Oberfläche, Bildsymbole und der Backend-Code werden in Titan gepflegt. Der eigene [Titan AppStore](APP-STORES.md) ergänzt die freie Container-Erstellung um lokale Installationsvorlagen; externe AppStores oder Docker-Oberflächen werden nicht eingebettet.

## Kompakte Verwaltungsansicht

Auf dem Desktop zeigt die Container-Tabelle Namen, Image, Stack, Status, CPU/RAM, Adressen und direkte Aktionen. Mobil erscheint dieselbe Auswahl als kompakte Karten. Statusfilter und Namenssuche greifen gemeinsam; Suche und Cursor bleiben bei Hintergrundaktualisierungen erhalten. Die Live-Übersicht zeigt Containeranzahl, laufende/gestoppte Container, fehlerhafte Healthchecks und den gemessenen Gesamt-RAM. Fehlende aktive Messungen werden nicht als null Verbrauch ausgegeben.

Bis zu 64 Container können für Start/Stop/Neustart ausgewählt werden. Titan prüft die gesamte Auswahl zuerst und meldet Teilfehler ausdrücklich. Mehrere ausgewählte Container einer Titan-App lösen die vorhandene App-Aktion nur einmal aus. Vorhandene Compose-Projekte werden anhand ihrer Docker-Metadaten gruppiert; Stacks können gemeinsam gestartet, gestoppt und neu gestartet werden. Hierbei wird keine externe Compose-Datei ausgeführt oder überschrieben.


## Direktes Aktionsmenü und Geräte

Ein Klick auf den Container-Namen öffnet sein Aktionsmenü direkt neben der Übersicht, mobil darüber. Titan-Apps verwenden ihren tatsächlichen Webport für **App öffnen**. Einstellungen, Start/Stop/Neustart und Logs stehen zusammen; Entfernen liegt unter Weitere Aktionen und benötigt Ja/Nein.

Geräte ändern erfordert einen gestoppten Container. Für Vorlagen-Apps öffnet **App-Einstellungen** die gemeinsame App-Konfiguration. Manuelle Titan-Container bieten **Einstellungen & Geräte**: Titan bewahrt den alten Container gestoppt auf, erstellt eine lokale Kopie seiner beschreibbaren Dateischicht mit derselben Datenvolume-Zuordnung und startet die Kopie. Vorherige Sicherungen heißen `titan-previous-…`. Deren Entfernen löscht das weiterverwendete Volume nicht; dieses ist keine unabhängige Datensicherung. Nur unterstützte Konfigurationen werden übernommen, fremde Container bleiben bei diesem Umbau ausgeschlossen.
