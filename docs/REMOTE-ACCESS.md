# Fernzugriff mit Cloudflare Tunnel

Unter **Systemsteuerung → Allgemein → Cloudflare Tunnel** lässt sich eine zusätzliche öffentliche HTTPS-Adresse für Titan einrichten. Die lokale NAS-Adresse bleibt erreichbar.

## Direkt mit einem Tunnel-Token verbinden

1. Im Cloudflare-Konto einen Tunnel anlegen oder einen vorhandenen Tunnel öffnen. Den **Tunnel-Token** aus der Connector-Einrichtung kopieren; nur den Token, keinen Installationsbefehl oder Verwaltungs-API-Token.
2. Den Token in Titan einfügen. Eine bereits eingerichtete öffentliche Titan-Adresse kann optional angegeben werden.
3. **Tunnel einrichten** wählen. Titan installiert Docker bei Bedarf, installiert den eigenen Connector **Cloudflare Tunnel**, startet ihn und prüft die Verbindung zu Cloudflare. Es gibt kein zusätzliches Cloudflared-Verwaltungspasswort.
4. Falls die öffentliche Route fehlt, den Hostnamen im Cloudflare-Konto auf **HTTP → `http://127.0.0.1:5102`** richten. Die öffentliche HTTPS-Adresse in Titan ergänzen und prüfen. Erst eine erfolgreiche öffentliche Prüfung wird als **Geprüft** angezeigt.

Der verwaltete Connector läuft im Host-Netz. Das vermeidet das Docker-Bridge-Problem bei der lokalen Titan-Verbindung; der Titan-Tunnelzugang und Cloudflared-Prüfport bleiben auf Loopback begrenzt. Portweiterleitungen am Router sind für diesen Connector nicht erforderlich. Ausgehende Cloudflare-Verbindungen müssen möglich sein.

Der Token wird als privates App-Geheimnis und in einer atomar ersetzten Datei mit Modus **0600** gespeichert. Der Container bindet das geschützte Verzeichnis nur lesbar ein; Tokenwerte stehen weder in Compose-Befehlen noch Container-Umgebungsvariablen, Jobmeldungen oder HTTP-Statusantworten. Titan zeigt den gespeicherten Token nicht wieder an. Mit erneutem Einfügen lässt er sich ersetzen. Bei fehlgeschlagener Einrichtung bleiben die bisherigen lokalen Webeinstellungen erhalten; bei einer gescheiterten Token-Erneuerung wird der vorherige Connector-Zustand wiederhergestellt, soweit die beteiligten Dienste erreichbar sind.

Die Einrichtung läuft als Hintergrundauftrag. Das Fenster darf geschlossen werden; beim erneuten Öffnen wird der aktuelle Fortschritt angezeigt. **Verbunden** bestätigt die Connector-Verbindung zu Cloudflare. Die öffentliche Route und Anmeldung sind eine weitere Prüfung. Ein Tunnel-Token kann die öffentliche Route nicht selbst anlegen; Titan zeigt deshalb genau den verbleibenden Schritt statt einen falschen Erfolg.

## Vorhandene Connectoren

Unter **Erweiterte Einstellungen und vorhandene Connectoren** können bestehende Cloudflared-Web- oder selbst verwaltete Connectoren weiterverwendet werden. Deren Token und Konten werden von der neuen Einrichtung nicht verändert. Bei neuen Cloudflared-Web-Installationen bleibt das dortige Verwaltungspasswort optional und unabhängig von Titan-Anmeldung und Tunnel-Token.

Wenn ein bisheriger Connector denselben Cloudflare-Tunnel bedient, kann Cloudflare Anfragen auf beide Connectoren verteilen. Nach einer Umstellung auf den neuen Host-Connector den alten Connector in Docker stoppen oder dessen Service URL passend beibehalten. Titan stoppt vorhandene fremde Connectoren nicht automatisch; deren Netzwerk kann für das Loopback-Ziel ungeeignet sein.

## Titan-Adresse und Service URL

1. Die öffentliche Titan-Adresse als HTTPS-Domain eintragen, beispielsweise `https://nas.example.de`. Dafür sind Port 443 und eine Domain ohne zusätzlichen Pfad vorgesehen.
2. Den installierten Cloudflared-Connector auswählen. Für einen selbst verwalteten Connector im Host-Netz steht eine eigene Auswahl bereit.
3. Fernzugriff speichern und die danach angezeigte **Service URL** als HTTP-Ziel der Tunnelroute in Cloudflare übernehmen. Den öffentlichen Hostnamen unverändert weiterreichen.
4. **Verbindung prüfen** ausführen. Anschließend den öffentlichen Zugang aus einem anderen Netz öffnen, anmelden und die benötigten Funktionen bedienen.

Das lokale Tunnelziel verwendet **HTTP auf Port 5102**. Die öffentliche Verbindung verwendet HTTPS; am lokalen Tunnelziel ist kein selbstsigniertes NAS-Zertifikat einzurichten.

| Connector-Netz | Service URL | Lokaler Zugang |
| --- | --- | --- |
| Host-Netz auf dem NAS | `http://127.0.0.1:5102` | Listener nur auf Loopback |
| Erkannte Docker-Bridge | `http://<erkannte-Bridge-Gateway-IP>:5102` | Auf das beobachtete private IPv4-Subnetz der Bridge und den eingetragenen öffentlichen Hostnamen beschränkt |

Die Bridge-Adresse wird aus der tatsächlichen Container- und Docker-Netzkonfiguration ermittelt. Eine Container-IP wird deshalb nicht von Hand als Titan-Ziel eingetragen. Titan ergänzt die benötigte verwaltete Firewallregel für das erkannte Connector-Netz. Nach einem Wechsel des Docker-Netzes die Fernzugriffseinstellungen erneut speichern und prüfen. Interne Docker-Netze oder nicht bestätigte Netze werden nicht automatisch freigegeben.

Titan speichert keinen Cloudflare-Verwaltungs-API-Token und erstellt keine DNS-Einträge oder Tunnelrouten über die Cloudflare-API. Ein Tunnel-Token berechtigt zum Betrieb eines Connectors; das Anlegen der öffentlichen Route benötigt andere Cloudflare-Rechte. [Offizielle Token-Dokumentation](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/).

## Diagnose

**Verbindung prüfen** zeigt getrennte Ergebnisse für das beobachtete Connector-Netz, den Containerstatus, die Erreichbarkeit des lokalen Titan-Ziels aus dem Connector und die öffentliche HTTPS-Adresse. Bei einem extern verwalteten Connector kann der Containerstatus unbekannt bleiben. Der öffentliche Test prüft TLS und eine Titan-Antwort der aktuellen Konfiguration; eine andere erreichbare Website genügt nicht.

| Ergebnis | Nächster Schritt |
| --- | --- |
| Connector läuft, lokales Ziel nicht erreichbar | Angezeigte Service URL, Docker-Netz und Firewall prüfen; nach Netzwerkänderungen erneut speichern |
| Lokales Ziel erreichbar, öffentliche Adresse fehlerhaft | Cloudflare-Domain, Tunnelroute und weitergereichten Hostnamen prüfen |
| Connector-Netz hat sich geändert | Aktuellen Connector wählen, erneut speichern und prüfen |
| Öffentliche Prüfung erfolgreich | Anmeldung und benötigte Datei-, Terminal- oder Konsolenfunktionen aus einem externen Netz praktisch prüfen |

Eine vorgeschaltete Cloudflare-Anmeldung kann die automatische öffentliche Prüfung verhindern. Die praktische Abnahme erfolgt dann zusätzlich im Browser mit der vorgesehenen Anmeldung. Die isolierte Titan-Demo bietet die Anzeige, verändert aber keine Fernzugriffseinstellungen und führt keine Diagnose aus.

## Öffentliche App-Adressen

Für installierte Apps lässt sich jeweils eine ausdrücklich eingerichtete HTTPS-Adresse hinterlegen. Sie erscheint bei den bestätigten öffentlichen Endpunkten der Docker-Verwaltung. Titan errät keine Tunnel-Links aus Container-IP oder Port. Die entsprechende Route in Cloudflare und gegebenenfalls vertrauenswürdige Domains oder Proxy-Einstellungen innerhalb der App werden separat eingerichtet.
