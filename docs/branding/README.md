# Titan Carbon

Stand: 8. Oktober 2026, lokale Gestaltung nach 0.6.0-alpha.3.

## Dateien und Herkunft

- [Symbol](../../titan/web/logo.svg): skalierbare SVG-Geometrie mit selbst konstruierten Facetten, Carbonmuster und Lichtkanten.
- [Symbol und Schriftzug](../../titan/web/brand/titan-wordmark.svg): gleiche Symbolgeometrie und selbst konstruierte Buchstabenpfade für TITAN. Keine Schriftdatei, externen Ressourcen oder eingebetteten Stockbilder.
- [Carbon-Entwurf](titan-carbon-concept.png): unverändert gespeichertes Ergebnis des eingebauten Imagegen-Tools, 2172 × 724 Pixel, RGBA mit transparentem Hintergrund. Die beigefügte Nutzervorlage diente als Hinweis auf eine kantige Formensprache. Das Stockbild selbst ist nicht Teil des Projekts.
- [Werkzeugsymbole](../../titan/web/app-icons/): 17 eigene `titan-*.svg` und `container.svg`, jeweils 64 × 64, mit selbst konstruierten Funktionszeichen, Carbonfläche und silbernen Kanten. Dazu gehören Dateien, Speicher, Freigaben, Docker, VMs, Terminal, Sicherungen, Apps, Einstellungen, Benutzer, Gruppen, Sicherheit, Dienste, Ressourcen, Monitoring, Protokoll und Updates. Das allgemeine Containersymbol ergänzt den Satz; das Docker-Werkzeug verwendet einen eigenen Container-/Würfelaufbau.

Die SVG-Fassung ist für die kleine Darstellung in der Weboberfläche vereinfacht. Der PNG-Entwurf zeigt die Materialrichtung in großer Darstellung. Die Herkünfte sind getrennt dokumentiert; die kommerziellen Prüfungen des Projekts sind in [LICENSING.md](../LICENSING.md) beschrieben.

## Integration und Prüfung

Desktop und Login verwenden die breite Wortmarke. Login-Emblem, mobile Kopfzeile, Geräteübersicht, Favicon und Office-Kopfzeile verwenden das gemeinsame Symbol. Dynamische Gerätenamen bleiben erhalten. Desktop, Dock, Hauptmenü und Einstellungen verwenden den gemeinsamen neutralen Werkzeugsatz. Die Desktop-Wortmarke belegt denselben vertikalen Platz wie das bisherige Strichsymbol.

Graphit-/Silberflächen im dunklen und Platinflächen im hellen Modus setzen die Materialrichtung in eigenem CSS fort. Carbontextur und Schimmer bleiben zurückhaltend und auf Rahmenelemente begrenzt. Text, Formulare und Zustandsanzeigen behalten ihre Lesbarkeit. Die Farbe einer Warnung, eines Fehlers oder eines erfolgreichen Vorgangs hat weiterhin eine Funktion.

Fremde App-Symbole bleiben separat lizenzierte Originalassets. Die 74 vorhandenen Drittanbieter-SVGs wurden bei dieser Überarbeitung nicht verändert; ein SHA-256-Vergleich bestätigte dies. Die graue Darstellung in Titan entsteht durch CSS. Sie macht die Bilder weder zu eigenen Titan-Assets noch ersetzt sie ihre Lizenzbedingungen.

Die echten Desktop- und Login-Oberflächen wurden im Browser geprüft; die Login-Prüfung nutzt einen isolierten Datenbestand und ausschließlich den Demo-Provider, ohne Anmeldung oder echte NAS-Aktionen. Die PNG-Transparenz und SVG-Referenzen wurden separat geprüft.

Die 18 Werkzeug-/Containersymbole wurden als XML und auf lokale Referenzen geprüft sowie mit librsvg/Cairo gerendert und visuell kontrolliert. Sie enthalten keine aktiven oder externen Ressourcen. Die eigenen SVG-Dateien sind eine eigenständige Vektorarbeit; das Imagegen-Ergebnis bleibt der separat dokumentierte Materialentwurf für Symbol und Wortmarke.

## Finaler Imagegen-Prompt

Tool: eingebautes Imagegen, transparente Ausgabe; eine vom Nutzer beigefügte Bildreferenz.

```text
Use case: logo-brand. Create an original premium brand lockup for a personal NAS operating system named TITAN. Image 1 is only a broad style reference for a bold angular T silhouette, NOT an edit target: do not trace or reproduce its geometry or any stock artwork. Design a distinctly new architectural T monogram with strong clipped angular shoulders, a substantial central vertical spine, carefully balanced negative space and a chamfered tapered lower termination; make it legible and original. Beside it, place the exact text "TITAN", spelled T I T A N, in a custom wide geometric uppercase wordmark with restrained angular cuts that belong to the same design family. One coherent horizontal lockup, symbol on the left, wordmark on the right, balanced spacing, all content fully visible with comfortable transparent margins. Both symbol and lettering are deep black graphite carbon fibre: extremely fine understated woven carbon texture, satin black surfaces, subtle glossy graphite sheen and thin cool silver edge reflections, tasteful shallow bevel depth. Keep the overall appearance BLACK, not silver or white, no colored accents, no excessive chrome, no glow. Straight-on view, no perspective distortion, no surface or scene behind it, no drop shadow extending far beyond the shapes. Genuinely transparent background with clean alpha edges. No extra text, tagline, watermark, badge, frame, mockup object or background. This is original commercial-product branding, not a reproduction of an existing logo.
```
