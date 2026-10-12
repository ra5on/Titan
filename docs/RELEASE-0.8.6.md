# Titan 0.8.6 · Stable

Apps und VM-Konsolen lassen sich mit dem neuen optionalen Plugin **Browser und
VM-Sitzungen** direkt in Titan bedienen. Außerdem verbessert diese Version den
Schutz der Anmeldung und die Verwaltung des Cloudflare-Plugins.

## Browser und VM-Sitzungen · Beta

- Apache Guacamole verwendet die vorhandene Titan-Anmeldung. Apps laufen in
  isolierten Browsern auf dem NAS; die Sitzung bleibt innerhalb der Oberfläche.
  Einzelne Apps müssen dafür nicht separat über Cloudflare veröffentlicht werden.
- VMs nutzen ihre vorhandene VNC-Konsole. Die bisherige Startkonsole bleibt
  auswählbar. Die Fenster berücksichtigen Änderungen der Dockgröße.
- Text-Zwischenablage, Upload und Download im Browser sowie Wiederverbinden sind
  enthalten. Abmelden oder Rechteentzug beendet den Zugriff auf die Sitzung.
- Installation, Aktualisierung, Start, Stopp und Entfernung erfolgen im App Store.
  Browser und Guacamole werden erst bei der Plugin-Installation heruntergeladen.

Eigene Anmeldungen innerhalb einer App oder eines VM-Gasts bleiben erforderlich.
Browserprofile und Downloads sind temporär und werden beim Beenden gelöscht.
RDP-Gastkonfiguration, Ton, Kamera, USB-Weitergabe und direkte VM-Dateiübertragung
sind nicht enthalten. Die Funktion bleibt **Beta**; der Titan-Releasekanal ist
**Stable**. [Bedienung, Zugriffsschutz und Grenzen](GUACAMOLE.md).

## Cloudflare

- Die Tunnelroute ordnet Anmeldeversuche einzelnen Besuchern zu, damit eine
  Anmeldesperre nicht sämtliche Fernzugriffe gemeinsam trifft. Nicht vertrauenswürdige
  Weiterleitungsheader bleiben ausgeschlossen.
- Öffentliche HTTP-Aufrufe werden auf die konfigurierte HTTPS-Adresse umgeleitet.
- Änderungen an Token oder öffentlicher Adresse behalten die geprüfte installierte
  Cloudflared-Version. Explizite Updates weisen ältere Versionen und veränderte
  Prüfsummen derselben Version zurück.
- Die Installation zeigt das erforderliche Tunnelziel **HTTP · 127.0.0.1:5102**
  direkt neben dem Eingabefeld für die öffentliche HTTPS-Adresse. Fehler beim
  Einrichten erhalten genauere Diagnosemeldungen und mehr Zeit für den TCP-Fallback.

## Update und Installation

Bestehende A/B-Installationen aktualisieren sich über **Systemsteuerung →
Updates & Rollback → Stable → Jetzt prüfen**. Die Vorbereitung schreibt den
zweiten Systembereich; der Neustart wird anschließend ausdrücklich bestätigt.
Laufende VMs vorher geordnet herunterfahren. Das IMG ist für Neuinstallationen
vorgesehen und darf nicht über vorhandene Nutzdaten geschrieben werden.

Nach dem Systemupdate im **App Store → Plugins → Browser und VM-Sitzungen** das
Plugin installieren. Der bestehende Titan-Tunnel genügt auch für diese Sitzungen.
Dieses Release enthält neue Host-Agent-APIs und wird deshalb ausschließlich als
vollständiges Systemupdate angeboten, nicht als separates Web-Update.

Die Release-Pipeline prüft Start, Laufzeit, Update, Datenerhalt, Rollback und
Fehlstart-Rückkehr vor der Veröffentlichung. Die Guacamole-CI prüft echte
Browsersitzungen direkt und über die erzeugte HTTPS/WSS-Tunnelroute. Ein echter
Kunden-Tunnel und die Vielfalt physischer NAS- und VM-Konfigurationen sind damit
nicht umfassend abgenommen. Vorhandene Beta-Kennzeichnungen bleiben bestehen.
