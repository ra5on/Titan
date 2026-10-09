# Prüfnachweis Titan 0.7.0

Abgeschlossene Release-Prüfung vom 9. Oktober 2026. Die Versionskennung allein
ist kein Prüfnachweis; die folgenden Ergebnisse gehören zum veröffentlichten Stand.

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
| [Quell-CI](https://github.com/ra5on/Titan/actions/runs/37986917717) | Bestanden; 1.937 Python-/API-Tests, davon 26 umgebungsbedingt übersprungen; Shell-/JS-Syntax und alle 79 UI-Suiten |
| [Webcontainer](https://github.com/ra5on/Titan/actions/runs/37986930284) | Bestanden; realer Containerstart, Neustart, Kompatibilität und fehlgeschlagenes Update mit Rücknahme |
| [Signiertes Webupdate](https://github.com/ra5on/Titan/releases/tag/web-v0.7.0) | Veröffentlicht; erneut heruntergeladen, Signatur gegen den öffentlichen Repository-Schlüssel verifiziert, Größe und SHA-256 geprüft |
| [Systemimage und Recovery](https://github.com/ra5on/Titan/actions/runs/37986926687) | Bestanden und als [v0.7.0](https://github.com/ra5on/Titan/releases/tag/v0.7.0) veröffentlicht; alle fünf aktiven App-Abnahmen sowie Image, UEFI/HTTPS, NAS-Laufzeit und A/B-Recovery erfolgreich |

Das heruntergeladene Webpaket enthält exakt die getesteten Dateien `photos.js`,
`horizon.css` und `wallpapers/horizon.png` (Byte-Prüfsummen abgeglichen).

- Webarchiv: 77.677.780 Bytes
- SHA-256: `f10bcd962ba6662421a5751ff34c1fb7cd2c66647616befff6f9bc767d1a68bd`
- Container: `sha256:7acaee1ed3cbf33830d603987b45425b9665aaa50b2e9312da7336156ccdcd7c`
- Kompatibilität: Agent-API 1, Zustandsschema 1

## Vollständiges Systemimage

Signiertes Manifest und signierte `SHA256SUMS` wurden nach dem Download gegen den
Repository-Schlüssel verifiziert. Die heruntergeladenen Laufzeit-/A/B-Berichte
stimmen mit ihren signierten Prüfsummen überein. Quelle und Version stimmen mit
dem eingefrorenen Produktstand überein. Image und A/B-Updatepaket wurden vollständig
über HTTPS heruntergeladen und dabei Größe und SHA-256 gegen die signierten
Prüfsummen verifiziert (ohne die großen Dateien lokal zu speichern).

- [Installationsimage](https://github.com/ra5on/Titan/releases/download/v0.7.0/titan-0.7.0-amd64.img.xz): 674.467.348 Bytes
- Image-SHA-256: `5178b5c632eb92be206aa7f7ca4235e0b054248fbffa356e5dfa6f9ca3e34479`
- A/B-Updatepaket: 834.143.540 Bytes
- Bundle-SHA-256: `cc82ab292a7e1df4181a5635b39bf7353d169bbcef9b8f9bdfec6b11e184665f`

Der Laufzeitbericht enthält 15 bestandene Prüfgruppen: unter anderem Ersteinrichtung,
Anmeldeschutz, Trennung von NAS-Daten und Betriebssystem, Speicherkomponenten,
SMB-Mehrbenutzerrechte, Docker-Lebenszyklus/Netze/Datenerhalt und VM-Verwaltung.
Eine Gruppe zur Datenträgervergrößerung ist dort ausdrücklich ausgelassen, weil
sie im separaten A/B-Test tatsächlich geprüft wird. Der VM-Test startete eine
Domain einschließlich UEFI und authentifizierter RFB-Konsole; ein installiertes
Gastbetriebssystem wurde dabei **nicht** gebootet.

Alle sieben A/B-Prüfungen bestanden: Baseline-Start, Datenbereich-Vergrößerung,
signierte Vorbereitung ohne automatischen Neustart, Update mit Konten/ACLs/Daten,
slotabhängige Grundeinstellungen, manuelles Rollback und Rückfall nach fehlerhaftem
Kandidaten. Das verteilte Rohimage und die Testbaseline blieben unverändert.

## Nachweisgrenzen

Keine Ergebnisse früherer Releases werden als Nachweis für 0.7.0 ausgegeben.
Der lokale Host hat keinen nutzbaren KVM-Zugang und zu wenig freien Plattenplatz
für den vollständigen Image-Build; diese Tests liefen auf GitHub.
Hardware-/USV-Abnahme, Windows-/macOS-SMB-Clients, RAID-Ausfall auf echten Platten,
ein vollständiges Gastbetriebssystem und NAS-Langzeitbetrieb sind nicht geprüft.
Der Systemworkflow verwendet für seine A/B-Prüfung eine kontrolliert erzeugte
Testbaseline (`generated-current-build`, Testkennung `0.4.5-alpha.1`); das ersetzt
keinen Nachweis einer Migration von jeder älteren veröffentlichten Installation.
Die weiter offenen Funktionsgrenzen der [NAS-Funktionsprüfung](NAS-FUNCTION-AUDIT.md)
bleiben bestehen. Die Kennzeichnung **Stable-Kanal** ist keine pauschale
Hardware- oder Dauerbetriebsfreigabe.
