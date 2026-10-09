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

CI, Webcontainer, Installationsimage, UEFI-Start und A/B-Wiederherstellung stehen
für diesen Commit noch aus. Keine Ergebnisse früherer Releases werden als
Nachweis für 0.7.0 ausgegeben. Der lokale Host hat keinen nutzbaren KVM-Zugang und
zu wenig freien Plattenplatz für den vollständigen Image-Build.
