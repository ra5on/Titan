# Titan Apps und vorhandene Docker-Anwendungen

Ab Titan 0.5.8 bietet **Apps** eigene Docker-Compose-Anwendungen an. Die erste freigegebene App ist **Cloudflare Tunnel**. Der Katalog steht lokal bereit; Titan lädt beim Start keinen BigBear-Katalog und bietet keinen Import externer Stores an.

Bereits installierte Anwendungen und ihre gespeicherten Compose-Rezepte bleiben erhalten. Die Umstellung entfernt weder Container noch Konfiguration, Datenbanken oder Nutzdaten. Unter **Weitere installierte Apps → Verwalten** und unter **Docker** lassen sich diese Anwendungen weiter bedienen. Das bisherige Cloudflared-Web wird nicht für neue Installationen angeboten.

## Cloudflare Tunnel installieren

1. **Apps → Cloudflare Tunnel** öffnen. Ein Administrator kann die Installation starten.
2. Den Tunnel-Token aus der Connector-Einrichtung des Cloudflare-Kontos einfügen. Nur den Token verwenden, keinen Installationsbefehl oder Verwaltungs-API-Token. Eine öffentliche Titan-Adresse ist optional.
3. **Installieren & verbinden** wählen. Die Ansicht zeigt die tatsächlich ausgeführten Schritte: Docker prüfen, private Dateien und Compose erstellen, Image laden, Container erstellen und starten, Cloudflare-Verbindung prüfen, lokalen Zugang einrichten und öffentlichen Zugang prüfen.
4. Den öffentlichen Hostnamen in Cloudflare auf die angezeigte **Service URL** richten. Die HTTPS-Adresse anschließend in Titan unter **Öffentliche Route** mit **Adresse speichern & prüfen** übernehmen.

Ein zusätzliches Verwaltungspasswort wird nicht benötigt. Die Titan-Anmeldung schützt weiterhin die Weboberfläche. Der Connector verwendet das Host-Netz und das lokale HTTP-Ziel `http://127.0.0.1:5102`. Damit wird keine wechselnde Docker-Container-IP als Ziel verwendet.

Die Installation läuft auf dem NAS weiter, wenn das Fenster geschlossen wird. Nach erneutem Öffnen erscheinen der gespeicherte Verlauf und der aktuelle Laufzeitstatus. Ein fehlgeschlagener oder durch einen Dienstneustart unterbrochener Auftrag lässt sich mit **Einrichtung fortsetzen** erneut prüfen; private Wiederaufnahme-Eingaben werden nicht an den Browser zurückgegeben. Nach erfolgreichem Abschluss oder ausdrücklicher Deinstallation werden diese vorübergehenden Eingaben entfernt.

**Mit Cloudflare verbunden** bestätigt den Connector, **Öffentlicher Zugang geprüft** bestätigt zusätzlich die öffentliche Titan-Adresse. Ohne öffentliche Route können die ersten Schritte abgeschlossen sein, während die öffentliche Prüfung aussteht. Ein gestarteter Container oder abgeschlossener früherer Auftrag genügt nicht als Bereitschaftsnachweis.

Der Token wird privat gespeichert und nie wieder im Formular angezeigt. **Token ändern oder erneut verbinden** ersetzt ihn ausdrücklich. Details zu Route, Datenschutz und Diagnose: [Fernzugriff mit Cloudflare Tunnel](REMOTE-ACCESS.md).

## Vorhandene Apps verwalten

Docker zeigt zusammengehörige Dienste eines verwalteten Compose-Pakets gemeinsam an. Details enthalten Status, tatsächlich gemessene Ressourcen, Protokolle und verfügbare Aktionen. Start, Stop und Neustart verwenden weiterhin das gespeicherte Rezept einer vorhandenen App; es wird nicht durch einen neuen Katalog ersetzt.

Deinstallation entfernt die verwalteten Container, behält aber die App-Konfiguration und Nutzdaten. App-Sicherungen stoppen alle beteiligten Dienste für einen konsistenten Dateistand. Separate Nutzdaten müssen ausdrücklich ausgewählt werden. Grenzen und Wiederherstellung: [App-Sicherungen](BACKUPS.md).

Gespeicherte Rezepte früherer externer Apps werden für die Verwaltung und ältere Systemstände aufbewahrt. Ihre Verfügbarkeit ist keine Freigabe für neue Installationen aus diesen Quellen. Persönliche Zugangsdaten erscheinen weiterhin nicht als normale öffentliche App-Einstellung.

## Netzwerk und Geräte vorhandener Anwendungen

Unter **Docker → Netzwerke** zeigt Titan vorhandene, eigene und von Apps verwendete Netze mit ihren Containerzuordnungen an. Ein eigenes Bridge-Netz lässt sich nur entfernen, wenn es weder von einem Container noch einem installierten App-Paket verwendet wird. Ein gestopptes Paket gibt seine Netzwerkzuordnung nicht automatisch frei.

Titan prüft private Subnetze gegen vorhandene Docker-Netze und Host-Routen. Interne Netze sind nur für Anwendungen geeignet, deren benötigte Verbindungen dadurch weiterhin möglich sind. Zusätzliche Macvlan-, Overlay- oder IPv6-Netze werden darüber nicht automatisch eingerichtet.

Die Geräteauswahl zeigt tatsächlich erkannte USB-, Grafik- und Beschleunigergeräte mit ihren Linux-Pfaden. Nach erneutem Anstecken seine Zuordnung prüfen. Ein fehlendes oder neu zugeordnetes Gerät verhindert einen neuen App-Start, bis die Auswahl korrigiert wurde; Stoppen und Entfernen bleiben möglich.

- Intel-/AMD-Grafik benötigt ein Rendergerät mit aktivem Treiber. AMD-Compute kann zusätzlich `/dev/kfd` benötigen.
- NVIDIA benötigt einen passenden Treiber und eine einsatzbereite NVIDIA Container Runtime.
- NPUs werden über vorhandene `/dev/accel/accel*`-Geräte erkannt.

Die Auswahl installiert keine Treiber und garantiert keine Unterstützung im Container-Image. In Proxmox muss die Hardware zuerst der Titan-VM zugewiesen werden. Physische Geräte werden von den automatisierten QEMU-Tests nicht abgenommen.

**App-Einstellungen → Geräte ändern** setzt eine gestoppte App voraus. Titan erstellt die verwalteten Container mit der neuen Zuordnung; gespeicherte Daten bleiben erhalten. Bei einem Fehler versucht Titan die vorherige Konfiguration wiederherzustellen. Einen gemeldeten Wiederherstellungsfehler über Status und Logs prüfen.

Für unterstützte manuell mit Titan erstellte Container bietet **Einstellungen & Geräte** eine neue Containerkonfiguration mit demselben Datenvolume an. Der vorherige Container bleibt zunächst gestoppt als Sicherung erhalten. Das gemeinsam genutzte Volume ist kein unabhängiges Backup.

## System-Rollback

Ein Betriebssystem-Rollback setzt App-Daten oder Geräteeinstellungen nicht zurück. Ältere Titan-Versionen sehen nur Rezepte, die sie verstehen; neuere Einträge und ihre Daten werden dabei nicht gelöscht. Vor einem Wechsel unabhängige Sicherungen behalten. Die Kompatibilitätsprüfung ersetzt keinen praktischen Rollback-Test mit den veröffentlichten Images.
