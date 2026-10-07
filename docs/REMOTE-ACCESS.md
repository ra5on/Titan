# Fernzugriff mit Cloudflare Tunnel

Unter **Systemsteuerung → Allgemein → Fernzugriff · Cloudflare Tunnel** lässt sich eine zusätzliche öffentliche HTTPS-Adresse für Titan einrichten. Die lokale NAS-Adresse bleibt erreichbar. Titan richtet den lokalen Zugang zum Connector ein; die Domain und Tunnelroute werden weiterhin in Cloudflare eingerichtet.

## Connector installieren

Cloudflared Web aus dem BigBear-Katalog installieren und den Tunnel dort einrichten. Das **Verwaltungspasswort** ist bei neuen Installationen optional. Ein leeres Passwort deaktiviert die Basic-Anmeldung der Cloudflared-Verwaltung. Es ist unabhängig vom Tunnel-Token und vom Titan-Konto; die Titan-Anmeldung bleibt erforderlich. Bestehende installierte Vorlagen und Zugangsdaten werden durch einen Katalog-Refresh erhalten.

Ein verbundener Tunnel bestätigt zunächst die Verbindung des Connectors zu Cloudflare. Zusätzlich muss der Connector die Titan-Weboberfläche erreichen können.

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

Die Funktion speichert keinen Cloudflare-API-Token und erstellt keine DNS-Einträge oder Tunnelrouten über die Cloudflare-API. Der Tunnel-Token bleibt Teil der Connector-Einrichtung.

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
