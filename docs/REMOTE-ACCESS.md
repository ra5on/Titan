# Fernzugriff mit Cloudflare Tunnel

Unter **App Store → Plugins → Cloudflare Tunnel** installiert Titan einen optionalen Debian-Dienst. Das Plugin ist als **Beta** gekennzeichnet. Cloudflared wird erst bei der Installation aus dem offiziellen GitHub-Release geladen und anhand der geprüften SHA-256-Summe verifiziert. Die lokale NAS-Adresse bleibt erreichbar.

## Tunnel und öffentliche Route einrichten

1. Im Cloudflare-Konto einen Tunnel anlegen oder öffnen. Aus der Connector-Einrichtung den **Tunnel-Token** kopieren; nur den Token, keinen Installationsbefehl oder Verwaltungs-API-Token.
2. In Titan das Cloudflare-Plugin öffnen, **Installieren** wählen und den Token sowie die öffentliche HTTPS-Adresse eintragen, beispielsweise `https://nas.example.de`.
3. Titan lädt Cloudflared, richtet die private Token-Datei und den Dienst ein und wartet auf eine bestätigte Verbindung. Nach dem Download darf der Verbindungsaufbau bis zu drei Minuten dauern, damit Cloudflared bei nicht erreichbarem UDP auf TCP wechseln kann.
4. Im Cloudflare-Konto den öffentlichen Hostnamen auf **Typ HTTP → URL `127.0.0.1:5102`** richten. Den HTTP-Host-Header nicht durch eine interne IP ersetzen. Eine NAS-IP mit HTTPS spricht einen anderen Titan-Zugang an.
5. Unter **Einstellungen → Fernzugriff** den öffentlichen Titan-Zugang prüfen und anschließend aus einem anderen Netz die Anmeldung und benötigten Funktionen testen.

Der lokale Titan-Tunnelzugang auf Port 5102 und der Cloudflared-Prüfport 5104 sind auf Loopback begrenzt. Das lokale Ziel verwendet HTTP, die öffentliche Verbindung HTTPS. Portweiterleitungen am Router sind dafür nicht erforderlich. Ausgehende Cloudflare-Verbindungen über Port 7844 müssen möglich sein. [Cloudflare-Verbindungsdiagnose](https://developers.cloudflare.com/tunnel/troubleshooting/).

Der Tunnel-Token berechtigt zum Betrieb eines Connectors. Er kann keine DNS-Einträge oder öffentlichen Tunnelrouten anlegen. Die Route wird im Cloudflare-Konto eingerichtet. Titan speichert keinen Cloudflare-Verwaltungs-API-Token. [Offizielle Token-Dokumentation](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/).

## Installation und Verbindung unterscheiden

Die Einrichtung läuft als Hintergrundauftrag. Das Installationsfenster zeigt währenddessen einen Wartehinweis; das Ergebnis bleibt unter **Einstellungen → Aktivität** sichtbar.

**Verbindung zu Cloudflare: Bestätigt** beruht auf Cloudflareds lokalem `/ready`-Endpunkt. **Öffentlicher Titan-Zugang bestätigt** bedeutet zusätzlich, dass die HTTPS-Adresse den Prüfendpunkt dieses Titan zur aktuellen Konfiguration erreicht. Ein gestarteter Dienst allein genügt nicht.

Ist der Tunnel verbunden, die öffentliche Route aber noch falsch eingerichtet, bleibt das Plugin installiert und zeigt die erforderliche Zieladresse. Ein Fehler beim Download, Dienststart, Verbindungsaufbau oder lokalen Titan-Zugang führt dagegen zur Rücksetzung der Installation. Auch eine unvollständige Rücksetzung wird ausdrücklich gemeldet.

## Token, Updates und Deinstallation

Titan speichert den Token in einer geschützten Datei mit Modus **0600**. Systemd stellt sie dem Dienst als Credential bereit. Der Token steht weder in Prozessargumenten noch in Browserstatus, Jobmeldungen oder Diagnosecodes. Rohes Cloudflared-Journal wird nicht an den Browser weitergegeben.

Im Plugin lassen sich **Token und Adresse ändern**, Updates prüfen und installieren sowie der Dienst starten, stoppen und deinstallieren. Bei Updates kann das Token-Feld leer bleiben, um den gespeicherten Token zu verwenden. Plugin und Token bleiben bei Titan-Systemupdates erhalten. Die Deinstallation entfernt Dienst, Programm und lokalen Token; den Tunnel im Cloudflare-Konto bei Bedarf separat löschen.

## Fehler eingrenzen

Die überarbeitete Installation nennt einen konkreten Fehlercode. Bei älteren Versionen, einschließlich 0.8.5, ersetzt eine Sammelmeldung noch sämtliche Fehler; sie belegt weder einen falschen Token noch eine Port-Sperre.

| Fehlercode | Bedeutung / nächster Schritt |
| --- | --- |
| `CF_DOWNLOAD`, `CF_DOWNLOAD_TLS` | Downloadzugang zu GitHub bzw. TLS-Prüfung fehlgeschlagen; Internet, DNS, Systemzeit und Zertifikate prüfen |
| `CF_DOWNLOAD_CHECKSUM`, `CF_DOWNLOAD_LIMIT` | Download wurde wegen abweichender Prüfsumme, Größe oder Dauer verworfen |
| `CF_STORAGE_FULL`, `CF_FILES` | Systembereich voll oder lokale Dateien konnten nicht eingerichtet werden |
| `CF_SERVICE_START`, `CF_SERVICE_EXEC`, `CF_SERVICE_CREDENTIAL` | Lokaler Dienststart, Programmausführung oder Bereitstellung der Token-Datei fehlgeschlagen |
| `CF_METRICS_PORT` | Ein anderer Dienst belegt bereits den lokalen Prüfport 5104 |
| `CF_TUNNEL_AUTH` | Cloudflare hat die Anmeldung abgelehnt; aktuellen Tunnel-Token im Konto prüfen |
| `CF_EDGE_DNS` | Cloudflared meldet einen Fehler bei der Auflösung der Tunnel-Server |
| `CF_EDGE_TCP`, `CF_EDGE_QUIC` | Cloudflared meldet Verbindungsfehler; ausgehenden Port 7844 und Netzwerk prüfen |
| `CF_CONNECT_TIMEOUT` | Nach drei Minuten keine bestätigte Verbindung; keine genauere Ursache aus dem aktuellen Dienstlauf erkennbar |
| `CF_LOCAL_ROUTE` | Tunnel verbunden, Aktivierung des lokalen Titan-Zugangs auf Port 5102 fehlgeschlagen |
| `CF_DOCKER_MIGRATION`, `CF_SAVE_STATE` | Umstieg vom bisherigen Docker-Tunnel oder dauerhaftes Speichern fehlgeschlagen |

Die Dienstdiagnose verwendet nur den aktuellen Systemd-Aufruf. Sie gibt feste Kategorien aus, keine Token, Tunnelkennungen oder ungefilterten Protokollzeilen. Für eine Fehlermeldung angeben: Titan-Version und Fehlercode; keinen Tunnel-Token mitsenden.

Eine vorgeschaltete Cloudflare-Anmeldung kann die automatische öffentliche Prüfung verhindern. Die praktische Abnahme erfolgt dann im Browser mit der vorgesehenen Anmeldung.

## Bereits vorhandene Connectoren

Der bisherige Titan-Docker-Tunnel bleibt bis zum ausdrücklich bestätigten Umstieg bestehen. Das Plugin stoppt ihn erst nach erfolgreicher eigener Verbindung und Einrichtung des lokalen Zugangs. Bei einem Fehler versucht Titan, den vorherigen Zustand wiederherzustellen. Selbst verwaltete Connectoren werden nicht automatisch entfernt.

Wenn zwei Connectoren denselben Tunnel bedienen, kann Cloudflare Anfragen auf beide verteilen. Ein Bridge-Container erreicht mit `127.0.0.1` nur sich selbst; das hier angegebene Ziel gilt für den nativen Dienst auf dem NAS. Bereits gespeicherte öffentliche App-Adressen bleiben erhalten. Deren Routen und Proxy-Einstellungen müssen separat passen.

Die CI prüft unter anderem den echten Cloudflared-Prozess mit privater Systemd-Credential-Datei sowie den Installationsabbruch und die Rücksetzung mit einem absichtlich ungültigen Testtoken. Eine erfolgreiche Verbindung zum Cloudflare-Konto des Benutzers lässt sich damit nicht nachweisen.
