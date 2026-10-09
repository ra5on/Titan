# Prüfnachweis Titan 0.7.0

Release-Vorbereitung vom 9. Oktober 2026. Dieser Bericht wird nach den tatsächlichen
Builds aktualisiert; die Versionskennung allein ist kein Prüfnachweis.

## Herkunft und Umfang

Basis: `fee4dbd` (Titan Web 0.6.3). Eigene HTML/CSS/JS-Implementierung, eigene
Werkzeug-SVGs und neu mit Imagegen erzeugtes Landschaftsmotiv. Weder Quellcode noch
Assets des TitanOS-Referenzprojekts wurden importiert. Bestehende Lizenzhinweise
bleiben erhalten. [Plan](RELEASE-PLAN-0.7.0.md), [Hintergrundherkunft und Prompt](../titan/web/wallpapers/README.md).

## Lokale Prüfung

- Alle 79 UI-Suiten einschließlich neuer Foto-Tests bestanden.
- Python-/API-Suite: 1.937 Tests, 12 übersprungen, keine Fehler (291,584 Sekunden).
- Browser: Desktop, Systemmenü, Galerie und Einstellungen in isolierter Demo geprüft;
  Bildvorschau, Escape mit Fokus-Rückgabe, globale Suche aus einem App-Fenster,
  Abmeldebestätigung mit Abbruch funktionieren. 390 px ohne horizontalen Überlauf.
- Originaldownload tatsächlich im Browser ausgeführt; SHA-256 stimmt mit der
  Beispieldatei überein. Keine Browser-Konsolenfehler beobachtet.
- JavaScript- und Shell-Syntax sowie `git diff --check` bestanden.
- Alle sichtbaren Hardwarewerte der Demo sind simuliert.

## Veröffentlichungsprüfung

Produktquelle: `040bb6175d8159bc18dcec1375205364641278ac`, in `main` durch
[PR #1](https://github.com/ra5on/Titan/pull/1) übernommen. Spätere Nachweis- und
README-Änderungen ändern nicht den eingefrorenen Produktcode der Downloads.

| Prüfung | Ergebnis |
| --- | --- |
| [Quell-CI](https://github.com/ra5on/Titan/actions/runs/37986917717) | Bestanden; Python/API, Shell-/JS-Syntax und alle UI-Suiten |
| [Webcontainer](https://github.com/ra5on/Titan/actions/runs/37986930284) | Bestanden; realer Containerstart, Neustart, Kompatibilität und fehlgeschlagenes Update mit Rücknahme |
| [Signiertes Webupdate](https://github.com/ra5on/Titan/releases/tag/web-v0.7.0) | Veröffentlicht; erneut heruntergeladen, Signatur gegen den öffentlichen Repository-Schlüssel verifiziert, Größe und SHA-256 geprüft |
| [Systemimage und Recovery](https://github.com/ra5on/Titan/actions/runs/37986926687) | Läuft; AdGuard, Immich, Cloudflare, Tailscale und eigener Compose-Verbund bereits bestanden. Image-/Boot-/Recovery-Ergebnis noch ausstehend |

Das heruntergeladene Webpaket enthält exakt die getesteten Dateien `photos.js`,
`horizon.css` und `wallpapers/horizon.png` (Byte-Prüfsummen abgeglichen).

- Webarchiv: 77.677.780 Bytes
- SHA-256: `f10bcd962ba6662421a5751ff34c1fb7cd2c66647616befff6f9bc767d1a68bd`
- Container: `sha256:7acaee1ed3cbf33830d603987b45425b9665aaa50b2e9312da7336156ccdcd7c`
- Kompatibilität: Agent-API 1, Zustandsschema 1

## Nachweisgrenzen

Keine Ergebnisse früherer Releases werden als Nachweis für 0.7.0 ausgegeben.
Der lokale Host hat keinen nutzbaren KVM-Zugang und zu wenig freien Plattenplatz
für den vollständigen Image-Build. Hardware-/USV-Abnahme und Langzeitbetrieb sind
nicht durchgeführt. Der Systemworkflow verwendet für seine A/B-Prüfung eine
kontrolliert erzeugte Testbaseline; das ersetzt keinen Nachweis einer Migration
von jeder älteren veröffentlichten Installation. Die Grenzen der
[NAS-Funktionsprüfung](NAS-FUNCTION-AUDIT.md) bleiben bestehen.
