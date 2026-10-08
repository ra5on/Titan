# Menüführung und Platzverteilung · 0.6.0-alpha.4

Der Durchlauf prüft Hauptmenü, Dock, Konto, App Store, Docker, Dateimanager,
Einstellungen, VM- und Speicherverwaltung sowie die gemeinsamen Seiten für
Benutzer, Rechte, Sicherheit, Dienste, Sicherungen, Meldungen, Ressourcen und
Protokoll. Die gemeinsame Gestaltung bleibt Carbon/Graphit mit einem hellen
Platinmodus. Eigene Titan-Symbole ersetzen keine fremden Originaldateien.

## Überarbeitet

- Hauptmenü: kleinere Symbolflächen und Zeilenabstände, weniger Außenabstand.
- Einstellungen: einheitlicher Name, kompakte Gruppen und Zeilen, eigene
  Carbon-Symbole in der Abschnittsnavigation und ein begrenztes Optionsmenü.
- Dateien: mobile Ansichtsschalter auch im Menü; bedienbarer Upload-Button,
  korrekt angekündigte Filter und sichtbare Tastaturauswahl.
- Niedrige Fenster: Dateiwerkzeuge und Suchfilter, Speicheraktionen sowie
  VM-Details scrollen mit. Die laufende Gastkonsole bleibt davon ausgenommen.
- Mobile Speicherverwaltung: fünf Bereiche in einer horizontal scrollbaren
  Zeile. Keine zweite Zeile mit vier ungenutzten Positionen.
- App Store: kompaktere mobile Empfehlungen. Details beginnen oben; Zurück
  erhält Katalogposition und Fokus.
- Docker: vollständige Tab-Tastaturbedienung, ein Tab-Fokus, passende
  Bereichsbezeichnungen und Orientierung. Aktualisierung erhält Fokus und
  Scrollposition. Containerwerte heißen „RAM“, die Summe „RAM gesamt“.
- Fenster schließen sofort logisch, aktualisieren Dock und gespeicherten Zustand
  und sperren den noch ausblendenden Rest. Hintergrundanimationen können die
  Bedienung nicht unbegrenzt aufhalten.
- Seitenaktionen scrollen regulär mit. Bestätigungsdialoge behalten ihre
  eigenen Aktionsbereiche und die positive Aktion links.

## Browserprüfung

Die isolierte Demo wurde bei 1280 × 720, 390 × 844 und 1280 × 360 geprüft.
Im niedrigen Dateifenster ließ sich mit geöffneten erweiterten Suchfiltern bis
zu Dateien und Fußleiste scrollen; die Werkzeugleiste scrollte aus dem Bild.
Mobil ließ sich über „Ansicht einstellen“ auf Liste umstellen. Im allgemeinen
Einstellungsformular war die unterste Webzugriffsaktion sichtbar erreichbar.

Der mobile App Store scrollte bis zu den installierten Apps; seine Überschrift
lag dann oberhalb des sichtbaren Bereichs. Die Immich-Einrichtung begann bei
Scrollposition null. Zurück stellte die vor dem Öffnen gespeicherte Position
und den Einrichten-Button als Fokusziel wieder her. Docker reagierte auf
Pfeiltasten und hatte genau einen per Tab erreichbaren Bereichsschalter.

Gruppen, Sicherheit, Dienste, Sicherungen, Meldungen, Protokoll und Ressourcen
zeigten mobil keinen horizontalen Überlauf des Hauptinhalts. Ihre Inhalte
bleiben innerhalb des jeweiligen Fensters scrollbar. VM-Details wurden
zusätzlich mobil geprüft. Demo-Daten belegen keine NAS-Mutation und keine
verbundene Gastanzeige.

Automatisierte Ergebnisse und Image-Nachweise stehen in
[VERIFY-0.6.0.md](VERIFY-0.6.0.md). [Gestaltungsgrundlagen](UI-DESIGN.md).
