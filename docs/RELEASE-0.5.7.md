# Titan 0.5.7 Alpha

Dieses Release korrigiert die Darstellung und Bedienung aus 0.5.6 und ergänzt eine direkte Cloudflare-Tunnel-Einrichtung. Image und signiertes Update werden nach erfolgreichen Paket-, Boot- und Wiederherstellungsprüfungen veröffentlicht.

## Änderungen

- **Durchgängige Hell-/Dunkel-Darstellung:** Gemeinsame semantische Farben ersetzen feste helle Balken und Flächen in Systemsteuerung, Benutzerverwaltung, Sicherheit, App Store, Docker und Speicher. Statusfarben und sichtbarer Tastaturfokus bleiben erhalten. Im Kontomenü sind Hell, Dunkel und Auto direkt wählbar.
- **Widget-Galerie:** Über Widgets hinzufügen einzelne Karten auswählen. CPU, RAM, Systemstatus, Meldungen, Aktivität und Uhr lassen sich unabhängig bewegen und entfernen; Auswahl und Positionen werden pro Konto gespeichert. Die Uhr steht allen Konten offen, Systemmesswerte bleiben Administratoren vorbehalten. Auch ausgeblendete und leere Auswahlen lassen sich erweitern.
- **Desktop-Menü:** Rechtsklick, langes Drücken oder Umschalt+F10 auf freiem Desktop öffnet gruppierte Hinzufügen- und Darstellungsaktionen. Desktop und Hauptmenü behalten die App-Schnellaktionen. Zusätzliche Rahmen um App-Artwork entfallen; Auswahl und Tastaturfokus bleiben sichtbar.
- **Cloudflare direkt per Token:** Token einfügen und Tunnel einrichten. Titan installiert und startet einen eigenen, begrenzten Connector ohne zusätzliches Verwaltungspasswort, bereitet dessen private Token-Datei vor und konfiguriert das lokale Tunnelziel. Eine bekannte öffentliche HTTPS-Adresse wird mitgeprüft; fehlende Route und Adresse werden als verbleibende Schritte angezeigt. Fortschritt läuft als Hintergrundauftrag weiter. Bestehende Connectoren bleiben verfügbar.
- **Wahrheitsgemäßer Verbindungsstatus:** Connector läuft, Verbindung zu Cloudflare, lokales Titan-Ziel und öffentliche Erreichbarkeit werden getrennt bewertet. Ein Tunnel-Token kann DNS und öffentliche Routen nicht bearbeiten. Als Geprüft gilt ausschließlich eine erfolgreiche öffentliche Antwort dieses Titan mit aktueller Konfiguration.

## Installation und Grenzen

Das AMD64-Image benötigt UEFI/OVMF, ausgeschaltetes Secure Boot, 8 GiB RAM und mindestens 64 GiB Festplatte. Die `.img.xz` entpacken; enthalten ist ein 48-GiB-Image. Neue Installationen öffnen unter `https://<NAS-IP>`, vorhandene Installationen behalten ihre Webports. Signierte Updates stehen nach Freigabe im Alpha-Kanal bereit.

TitanOS wurde ausschließlich als visuelle Orientierung betrachtet; es wurden weder Code noch Assets übernommen. Die lokale Demo zeigt die Tunnel-Einrichtung, verbindet aber keinen Tunnel. Ohne einen gültigen Tunnel-Token und eine echte Domain ist kein externer Cloudflare-End-to-End-Test möglich. Die automatische Einrichtung ersetzt keine praktische Anmeldung aus einem anderen Netz. Eine vorgeschaltete Cloudflare-Access-Anmeldung kann den automatischen öffentlichen Test blockieren.

Der neue Connector wird mit dem offiziellen, per Digest gebundenen Cloudflared-Image betrieben. Die Freigabe enthält eine reale Docker-Prüfung der privaten Token-Datei, Container-Beschränkungen und fehlgeschlagenen Verbindung ohne gültigen Kundentoken. Die bestehenden Paket-, Laufzeit- und Update-/Rollback-Prüfungen bleiben Release-Voraussetzung. App-Daten benötigen weiterhin unabhängige Sicherungen; ein System-Rollback setzt sie nicht zurück.

[Bedienung](UI-DESIGN.md) · [Cloudflare-Einrichtung](REMOTE-ACCESS.md) · [Release und Prüfberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.7-alpha.1).
