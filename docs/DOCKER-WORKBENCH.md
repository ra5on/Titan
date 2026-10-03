# Docker direkt verwalten

Docker im Hauptmenü öffnet Titans eigene Verwaltung: Container, Images, Netzwerke und Volumes. Es wird keine fremde Docker-Oberfläche gestartet und keine Telemetrie eingebaut. Der Browser kommuniziert ausschließlich mit dem angemeldeten Titan-Backend; Docker hat keinen öffentlich freigegebenen API-Port.

1. Unter **Volumes** bei Bedarf ein lokales Datenvolume anlegen.
2. **Container erstellen**: Namen und Image, z. B. `nginx:stable`, eintragen. Bridge ist Standard; bei Host/Ohne Netzwerk die Portzuordnungen leer lassen. Eigene vorhandene Netze stehen in der Auswahl.
3. Ports zeilenweise als `8080:80/tcp`, Umgebung zeilenweise als `NAME=Wert` eintragen. Datenvolume aus der Liste wählen und das Ziel innerhalb des Containers setzen. USB/GPU werden ausschließlich nach erkannter, expliziter Auswahl durchgereicht.
4. Erstellen & starten. Aktionen zeigen ihren Status direkt im Bereich. Bei einem Startfehler bleibt ein erfolgreich angelegter Container zur Diagnose/erneuten Startauslösung erhalten.
5. Details & Logs zeigt Adressen, Ports, Neustartregel, Datenzuordnungen und letzte 150 Logzeilen. Umgebungsvariablen und deren Passwörter werden nicht in der Übersicht oder im Diagnose-JSON veröffentlicht.

Entfernen verwendet keine Force-/Prune-Aktionen. Erst stoppen; danach bleibt das Datenvolume erhalten. Ein Volume separat zu löschen entfernt dessen Daten endgültig und erfordert Ja/Nein-Bestätigung. Docker lehnt das Entfernen noch verwendeter Volumes und Images ab.

Vorlagen-Apps sind zusätzlich sichtbar. Ihre Aktionen werden an den bestehenden Titan-App-Manager weitergegeben; dessen Prüfung von Images, Netzwerk und Datenpfaden bleibt erhalten. Für einen Containerverbund wirkt die App-Aktion auf die gesamte zugehörige App.

RAM wird einschließlich Dateicache aus Linux-Cgroups gemessen. Wenn diese Messung nicht verfügbar ist, erscheint „—“. Gestoppte Container zeigen 0 B. Ein Docker-RAM-Limit ist eine Obergrenze, kein Verbrauchswert.

Die Oberfläche und der Backend-Code wurden selbst entwickelt. Dockhand diente zur Recherche von Funktionen: https://dockhand.pro/manual/ . Eine Einbettung ist zurückgestellt. Neue One-Click-/Fremdstore-Integrationen sind ebenfalls zurückgestellt; LinuxServer.io bleibt der vorhandene Standardkatalog.
