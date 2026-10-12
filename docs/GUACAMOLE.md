# Browser- und VM-Sitzungen

Das optionale Plugin **Browser und VM-Sitzungen** im App Store stellt Apache
Guacamole 1.6.0 und einen Chromium-Browser auf dem NAS bereit. Die Funktion ist
zunächst **Beta**; der Titan-Releasekanal bleibt Stable. Die Installation lädt
Container und baut das Browserimage lokal aus dem mitgelieferten Rezept.

Nach der Installation öffnen die App-Kacheln ihre Sitzung innerhalb von Titan.
Tailscale öffnet seine externe Kontoverwaltung in diesem Browser. VMs verwenden
Guacamole mit ihrer vorhandenen lokalen VNC-Konsole; die **Startkonsole** lässt
sich weiterhin auswählen. Es ist keine zusätzliche Guacamole-Anmeldung nötig.
Anmeldungen innerhalb einer App oder eines Gastbetriebssystems bleiben nötig.
RDP-Gastkonfiguration ist noch nicht Teil dieses Ausbaus.

## Lokal und über Cloudflare

HTML, Guacamole-Client, Dateitransfer und WebSocket verwenden dieselbe Origin wie
Titan. Der vorhandene Tunnel mit Ziel `http://127.0.0.1:5102` genügt; einzelne
App-Adressen müssen für diese Sitzungen nicht veröffentlicht werden. Das
Endgerät braucht keinen direkten Zugriff auf die Docker-Ports oder VM-Adressen.
Cloudflare Access oder andere vorgeschaltete Regeln müssen Titans WebSocket
ebenfalls zulassen. Ein echter Kunden-Tunnel wird durch CI nicht geprüft.

## Sitzungen und Grenzen

- Sitzungen gehören zu genau einer Titan-Anmeldung; andere Benutzer und andere
  Anmeldungen desselben Benutzers können ihre IDs nicht übernehmen.
- Fensterwechsel und kurzzeitige Verbindungsabbrüche erhalten den Browser.
  Ohne Verbindung endet eine Sitzung nach 15 Minuten, spätestens nach acht
  Stunden. Abmelden, Rechteentzug oder **Sitzung beenden** beendet sie ebenfalls.
- Browserprofile, Cookies und Downloads sind flüchtig. Sie werden beim Beenden
  gelöscht. Vorher benötigte Dateien über **Dateien** herunterladen.
- **Dateien** überträgt einzelne Dateien bis 256 MB in den Downloads-Ordner der
  Browsersitzung und zurück. Dort können Apps sie im Dateidialog auswählen.
  Gleichnamige Uploads erhalten einen Zeitpräfix. Der gesamte temporäre
  Browserordner ist auf 512 MB begrenzt.
- Text-Zwischenablage ist in beiden Richtungen verfügbar. Ton, Mikrofon, Kamera,
  USB-Weitergabe und direkte VM-Dateiübertragung sind nicht enthalten.
- Das Bild wird proportional an den verfügbaren Fensterraum angepasst, auch
  bei einer Änderung der Dockgröße. Die Gastauflösung wird nicht erzwungen.
- Maximal vier Sitzungen je Anmeldung, acht insgesamt. Jeder Browser ist auf
  1,5 GB RAM, zwei CPUs und 256 Prozesse begrenzt. Video und Spiele sind kein
  Leistungsziel dieser ersten Fassung.

## Zugriffsschutz und Betrieb

Titan bestimmt Ziele anhand installierter Apps bzw. verwalteter VM-IDs. Die API
akzeptiert keine freien Zielhosts, Ports oder guacd-Verbindungsparameter.
Mutationen benötigen CSRF; WebSockets benötigen die Titan-Sitzung und eine
erlaubte Origin. Laufende Verbindungen prüfen die Anmeldung regelmäßig erneut.
Interne VNC-Passwörter und guacd-Verbindungs-IDs gelangen nicht an den Client.

Guacd bindet ausschließlich an Host-Loopback. Browserports werden ausschließlich
auf Loopback veröffentlicht und zusätzlich mit individuellen VNC-Passwörtern
geschützt. Browser laufen ohne Docker-Socket und ohne NAS-Dateimounts als
unprivilegierter Benutzer, mit schreibgeschütztem Root-Dateisystem und ohne
Linux-Capabilities. Ein begrenztes Seccomp-Profil erlaubt die User-Namespace-
Aufrufe für Chromiums Sandbox; `--no-sandbox` wird nicht eingesetzt. Hosts,
die unprivilegierte User-Namespaces sperren, benötigen eine geeignete lokale
Sandbox-Konfiguration. Titan schaltet Host-Sicherheitsregeln nicht pauschal ab.

Die Browser erreichen das Netz ihrer App und dessen erreichbare Dienste. Die
Berechtigung „Apps“ umfasst deshalb auch diesen Netzwerkzugriff; sie ist keine
Beschränkung auf eine einzelne Website. Dienste sollten ihre eigene Anmeldung
behalten. Normale Browserupdates gehören zum Plugin-Update: **Aktualisieren**
baut ein neues Image; bestehende Sitzungen verwenden bis zu ihrem Ende das alte.
Der Build verwendet keinen Cache für die Paketinstallation und bezieht dabei
die aktuellen Debian-Paketupdates. Das entstandene Image wird per ID fixiert.

## Lizenzen und Nachweise

Der unveränderte JavaScript-Client stammt aus dem geprüften Apache-Quellarchiv
1.6.0; `scripts/vendor-guacamole.py` prüft dessen SHA256. Lizenz, NOTICE und
Herkunft liegen in `titan/web/vendor/guacamole/`. Das guacd-Image und Debian-
Basisimage sind mit Digest festgelegt. Das Seccomp-Profil stammt aus Playwright
v1.55.1; Herkunft und Apache-Lizenz liegen im Browserrezept. Chromium, Xvfb,
Openbox, x11vnc und weitere Debian-Pakete behalten ihre jeweiligen Lizenzen.
Die Apache-Lizenz ersetzt diese Bedingungen nicht. Die Dockerimages werden
beim Nutzer bezogen bzw. gebaut und nicht im Titan-Systemimage gebündelt.

Die CI prüft Authentifizierung, CSRF, Sitzungsbesitz, Rechteentzug, Protokoll-
Framing und Datei-Pfadgrenzen. Ein eigener Linux-Lauf startet echtes guacd und
Chromium und prüft Bildübertragung, Tastatureingabe, Dateitransfer,
Wiederverbinden und Logout. Dieselbe Prüfung läuft über HTTPS/WSS und Titans
erzeugte Tunnelroute mit einem lokalen Ersatz für Cloudflares TLS-Endpunkt.
Dieser Nachweis ersetzt keine Abnahme auf NAS-Hardware und am eigenen Tunnel.
