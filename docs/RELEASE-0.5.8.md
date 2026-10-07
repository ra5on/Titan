# Titan 0.5.8 Alpha

Titan ersetzt den BigBear-AppStore und die bisherige Cloudflare-Einrichtung durch eigene Docker-Compose-Apps. Die erste angebotene App ist **Cloudflare Tunnel**. Image und signiertes Update werden nach erfolgreichen Quellcode-, Paket-, Boot- und Wiederherstellungsprüfungen veröffentlicht.

## Änderungen

- **Apps statt externem Store:** ein lokales Angebot eigener Compose-Rezepte, ohne automatische Katalogdownloads oder Store-Verwaltungsmenüs. Bereits installierte Anwendungen behalten ihre gespeicherten Rezepte und Daten und bleiben verwaltbar.
- **Cloudflare als erste App:** Tunnel-Token und optional die öffentliche HTTPS-Adresse eintragen. Kein zusätzliches Verwaltungspasswort, keine Docker-IP-Auswahl. Titan verwendet den eigenen begrenzten Connector und richtet dessen lokales HTTP-Ziel ein.
- **Tatsächlicher Installationsverlauf:** Docker prüfen, Dateien und Compose erstellen, Image laden, Container erstellen, starten, Cloudflare-Verbindung prüfen, lokalen Zugang einrichten und öffentliche Erreichbarkeit prüfen. Die Schritte zeigen Ergebnisse und Zeitpunkte, bleiben nach einem Fensterwechsel erhalten und können nach einer Unterbrechung fortgesetzt werden.
- **Verbindung und Installation getrennt:** Ein laufender Container bestätigt keine Cloudflare-Verbindung. Ein verbundenes Cloudflare bestätigt noch keine erreichbare öffentliche Titan-Adresse. Übersprungene und fehlgeschlagene Prüfungen bleiben sichtbar.
- **Desktop-Korrekturen:** durchgängige Hell-/Dunkel-Flächen, direkt erreichbare Moduswahl und Transparenz pro Konto, einzelne verschiebbare Widgets mit Galerie, Desktop-Schnellaktionen und App-Symbole ohne zusätzliche Rahmen. VM-Kacheln zeigen gemessene CPU-/RAM-Werte; Seitenleisten bleiben anpassbar. Bestätigungen zeigen die positive Aktion links und Nein/Abbrechen rechts.

## Installation und Grenzen

AMD64, UEFI/OVMF, Secure Boot ausgeschaltet, 8 GiB RAM und mindestens 64 GiB Festplatte. Die `.img.xz` entpacken; das enthaltene Image ist 48 GiB groß. Neuinstallationen öffnen unter `https://<NAS-IP>`; vorhandene Installationen behalten ihre Webports. Das signierte Update erscheint im Alpha-Kanal.

Der öffentliche Hostname muss im Cloudflare-Konto dem angezeigten lokalen HTTP-Ziel zugeordnet sein. Ein Tunnel-Token kann diese Route nicht selbst anlegen. Die lokale Demo installiert keine Container. Ohne gültigen Kundentoken und echte Domain ist ein externer Cloudflare-End-to-End-Test nicht möglich; eine Cloudflare-Access-Anmeldung kann die automatische öffentliche Prüfung verhindern.

Der Connector verwendet das offizielle, per Digest gebundene Cloudflared-Image. Release-Prüfungen testen die tatsächlichen Compose-Schritte, private Token-Datei, Container-Beschränkungen und fehlgeschlagene Authentifizierung ohne Kundentoken. Ein eigenes isoliertes Compose-Prüfrezept testet Containerverbund, Neustart, Sicherung und Datenbewahrung. Dieses Rezept ist nur im wegwerfbaren Testsystem freigegeben und erscheint nicht im veröffentlichten App-Angebot. Boot-, Laufzeit- und Update-/Rollback-Prüfungen bleiben Voraussetzung für die Veröffentlichung.

TitanOS diente ausschließlich als visuelle Orientierung; Code und Assets wurden nicht übernommen. App-Daten benötigen unabhängige Sicherungen; ein System-Rollback setzt sie nicht zurück.

[Apps](APP-STORES.md) · [Cloudflare](REMOTE-ACCESS.md) · [Bedienung](UI-DESIGN.md) · [Release und Prüfberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.8-alpha.1).
