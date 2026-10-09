# Titan 0.7.0 · Horizon

Ein eigenständiger Desktop mit zusammenhängender Navigation für Dateien, Fotos,
Apps und virtuelle Maschinen. Referenz waren ausschließlich die öffentliche
Produktbeschreibung und dokumentierte Bildschirmaufnahmen von TitanOS; kein
TitanOS-Code und keine TitanOS-Assets wurden übernommen.

## Neu

- Systemmenü oben links mit persönlicher Darstellung, Widgets, Konto und
  bestätigten Systemaktionen; Abmelden fragt jetzt ebenfalls nach.
- Eigener Landschaftshintergrund, farbige Werkzeug-Icons und ruhige Glasflächen.
  Neue Konten starten dunkel, explizite vorhandene Farbmodi bleiben erhalten.
- Direkte Anwendungssuche auf dem Desktop; Strg/Cmd+K funktioniert auch aus
  geöffneten Titan-Fenstern.
- Fotos als eigene Anwendung: Freigaben, Ordner-/Dateinamensfilter,
  Unterordnersuche, 48 Treffer pro Seite, Vorschau, Vor/Zurück und Originaldownload.
  Dieselben serverseitigen Dateirechte wie im Dateimanager gelten unverändert.
- Größere mobile Bedienflächen, klarere Einstellungsbeschriftungen, sichtbarer
  Tastaturfokus und Rücksicht auf reduzierte Bewegung/Transparenz.

## Aktualisierung

Das separate signierte Webupdate ist für die bestehende Container-Installation
ab Systembasis 0.6.1 vorgesehen. Agent-API und Datenbankschema bleiben unverändert.
Ein vollständiges Installationsimage wird getrennt durch die vorhandene
Boot-/Recovery-Pipeline geprüft. Vorhandene Releases und Tags werden nicht ersetzt.
Veröffentlichungslinks und bestandene Nachweise stehen in [VERIFY-0.7.0.md](VERIFY-0.7.0.md).

## Grenzen

Die Galerie indiziert keine gesamte Platte im Hintergrund und überträgt keine
Bilder an einen Cloudanbieter. Unterordnersuchen können vom bestehenden Backend
zeitlich begrenzt werden; Teilergebnisse werden gekennzeichnet. Vorschauen sind
für JPEG/PNG/GIF/WebP bis 24 MiB vorgesehen, automatische Vorschaubilder bis 4 MiB.
HEIC, SVG und größere Dateien können heruntergeladen werden. Es gibt keine
Gesichtserkennung, automatische Albumverwaltung oder serverseitige Konvertierung.

Reale Controller-/USV-Kompatibilität, vollständiger Ersatzhardware-Import und
langfristiger NAS-Dauerbetrieb sind nicht durch UI-/VM-Tests bewiesen.
Die bekannten Grenzen in [NAS-FUNCTION-AUDIT.md](NAS-FUNCTION-AUDIT.md) gelten
weiter, insbesondere für Quoten, externe Backups und Wiederherstellung.
