# Fernzugriff mit Cloudflare Tunnel

Unter **Apps → Cloudflare Tunnel** wird Titan über einen eigenen Docker-Compose-Connector mit Cloudflare verbunden. Die lokale NAS-Adresse bleibt erreichbar. Die frühere Tunnel-Einrichtung in der Systemsteuerung und neue Cloudflared-Web-Installationen wurden durch diese App ersetzt.

## Tunnel und öffentliche Route einrichten

1. Im Cloudflare-Konto einen Tunnel anlegen oder öffnen. Aus der Connector-Einrichtung den **Tunnel-Token** kopieren; nur den Token, keinen Installationsbefehl oder Verwaltungs-API-Token.
2. In Titan **Apps → Cloudflare Tunnel** öffnen und den Token einfügen. Eine bereits eingerichtete öffentliche Titan-Adresse kann optional angegeben werden.
3. **Installieren & verbinden** wählen. Titan prüft Docker, erstellt die privaten Dateien und Compose-Konfiguration, lädt das Image und erstellt und startet den Connector. Jeder Schritt wird erst nach seinem tatsächlichen Ergebnis aktualisiert. Ein zusätzliches Verwaltungspasswort ist nicht erforderlich.
4. Den öffentlichen Hostnamen in Cloudflare auf **HTTP → `http://127.0.0.1:5102`** richten. Der öffentliche Hostname muss unverändert an Titan weitergegeben werden.
5. Die HTTPS-Adresse unter **Öffentliche Route** eintragen, beispielsweise `https://nas.example.de`, und **Adresse speichern & prüfen** wählen. Danach den Zugang aus einem anderen Netz öffnen und die Titan-Anmeldung praktisch prüfen.

Der verwaltete Connector läuft im Host-Netz. Das verhindert, dass eine wechselnde oder gesperrte Docker-Container-IP als lokales Titan-Ziel verwendet wird. Der Titan-Tunnelzugang auf Port 5102 und der Cloudflared-Prüfport 5103 bleiben auf Loopback begrenzt. Das lokale Ziel verwendet HTTP, die öffentliche Verbindung HTTPS. Portweiterleitungen am Router sind für diesen Connector nicht erforderlich; ausgehende Cloudflare-Verbindungen müssen möglich sein.

Der Tunnel-Token berechtigt zum Betrieb eines Connectors. Er kann keine DNS-Einträge oder öffentlichen Tunnelrouten anlegen. Diese Route wird im Cloudflare-Konto eingerichtet. Titan speichert keinen Cloudflare-Verwaltungs-API-Token. [Offizielle Token-Dokumentation](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/).

## Fortschritt und Wiederaufnahme

Die Einrichtung läuft als Hintergrundauftrag weiter, wenn das Fenster geschlossen wird. Beim erneuten Öffnen lädt Titan den gespeicherten Verlauf und prüft den aktuellen Zustand.

**Mit Cloudflare verbunden** bestätigt die tatsächliche Connector-Verbindung über Cloudflareds lokalen `/ready`-Endpunkt. **Öffentlicher Zugang geprüft** bestätigt zusätzlich eine sichere HTTPS-Antwort dieses Titan zur aktuellen Konfiguration. Eine fremde erreichbare Website, ein gestarteter Container oder ein alter erfolgreicher Auftrag genügen nicht.

Ohne öffentliche Adresse kann der Connector bereits verbunden sein, während die beiden letzten Schritte ausstehen. Bei einer noch nicht bestätigten Route zeigt Titan den verbleibenden Bedarf an. Nach einer fehlgeschlagenen oder unterbrochenen Installation ist **Einrichtung fortsetzen** verfügbar, solange sichere private Eingaben vorhanden sind. Titan prüft die echten Voraussetzungen erneut und übernimmt keine veränderten fremden Dateien oder Container als erfolgreich.

## Token ersetzen und App verwalten

Der Token wird als privates App-Geheimnis und in einer atomar ersetzten Datei mit Modus **0600** gespeichert. Der Container bindet das geschützte Verzeichnis nur lesbar ein. Der Token steht weder in Compose-Befehlen noch Container-Umgebungsvariablen, öffentlichen Jobmeldungen oder HTTP-Statusantworten. Das Formular zeigt ihn nie wieder an.

Unter **Token ändern oder erneut verbinden** lässt sich ein neuer Token ausdrücklich einfügen. Schlägt die Erneuerung fehl, stellt Titan den vorherigen Token und Laufzeitstatus wieder her, soweit die beteiligten Dienste erreichbar sind. Fehler bei dieser Rücksetzung werden gemeldet. Ein neuer fehlgeschlagener Connector bleibt verwaltet und wird sicher gestoppt. Änderungen am lokalen Tunnel-Proxy werden synchron abgeschlossen oder zurückgesetzt, bevor der Auftrag endet.

Vorübergehende private Wiederaufnahme-Eingaben werden nach erfolgreichem Abschluss und bei ausdrücklicher Deinstallation entfernt. Die gewöhnliche Deinstallation behält App-Konfiguration und Nutzdaten. **Starten** und **Stoppen** stehen in der App zur Verfügung; weitere Containerdetails und Protokolle liegen unter **Docker**.

## Fehler eingrenzen

| Anzeige | Nächster Schritt |
| --- | --- |
| Image laden oder Container erstellen fehlgeschlagen | Docker, Internetzugang, freien Speicher und Portkonflikte prüfen; Verlauf erneut öffnen |
| Gestartet, Cloudflare-Verbindung ausstehend | Vollständigen Tunnel-Token und ausgehenden TCP/UDP-Port 7844 prüfen |
| Connector verbunden, öffentliche Adresse fehlt | Hostnamen und Route in Cloudflare einrichten, HTTPS-Adresse in Titan ergänzen |
| Lokaler Zugang eingerichtet, öffentliche Route unbestätigt | Öffentlichen Hostnamen, Service URL und weitergereichten Host-Header prüfen |
| Öffentlicher Zugang geprüft | Anmeldung und benötigte Datei-, Terminal- oder Konsolenfunktionen aus einem externen Netz praktisch prüfen |

Eine vorgeschaltete Cloudflare-Anmeldung kann die automatische öffentliche Prüfung verhindern. Die praktische Abnahme erfolgt dann im Browser mit der vorgesehenen Anmeldung. Die Demo verändert keine Fernzugriffseinstellungen und installiert keine Container.

## Bereits vorhandene Connectoren

Bestehende Docker-Anwendungen, private Token und gespeicherte Fernzugriffseinstellungen werden durch die neue Apps-Oberfläche nicht automatisch entfernt oder migriert. Frühere Cloudflared-Web- oder selbst verwaltete Connectoren bleiben unter Docker verwaltbar.

Wenn zwei Connectoren denselben Cloudflare-Tunnel bedienen, kann Cloudflare Anfragen auf beide verteilen. Nach einem Wechsel auf die neue App den vorherigen Connector gezielt stoppen oder dessen Ziel passend beibehalten. Ein Bridge-Connector erreicht das Loopback-Ziel `127.0.0.1` auf dem NAS nicht als eigenen Host. Frühere Bridge-Freigaben bleiben auf das beobachtete private Netz und den eingetragenen öffentlichen Hostnamen beschränkt; eine Container-IP wird nicht als Titan-Ziel erraten.

Bereits ausdrücklich gespeicherte öffentliche App-Adressen bleiben erhalten. Ihre Tunnelroute sowie vertrauenswürdige Domains oder Proxy-Einstellungen innerhalb der jeweiligen App müssen weiterhin separat passen.
