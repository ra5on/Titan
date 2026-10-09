# Titan 0.7.0: eigenständiger Desktop und Release-Abnahme

Arbeitsbasis: Titan `fee4dbd` (Web 0.6.3, Installationsbasis 0.6.1).
Referenz: öffentliche Produktbeschreibung und drei dokumentierte Screenshots von
[ra5on/TitanOS](https://github.com/ra5on/TitanOS), geprüft am 9. Oktober 2026.

## Ziel und Herkunft

Ein zusammenhängendes NAS-Produkt mit übersichtlichem Desktop, Dock, Systemmenü,
Dateien, Fotos, Anwendungen, VMs und Einstellungen. TitanOS dient als sichtbare
Bedienreferenz. Es werden weder dessen Quellcode noch Styles, Icons, Bilder oder
Texte in Titan übernommen. Neue Icons entstehen als eigene SVG-Zeichnungen; der Landschaftshintergrund wird mit Imagegen neu erzeugt;
neue Funktionen verwenden Titans bestehende APIs und Rechteprüfung. Vorhandene
Titan- und Drittanbieter-Lizenzhinweise bleiben erhalten. Dies ist eine
Herkunftsdokumentation, keine pauschale rechtliche Freigabe.

## Umsetzung

1. **Desktop:** eigener Landschaftshintergrund, ruhige Glasflächen, farbig
   unterscheidbare Werkzeuge; Systemmenü oben links, Suche über Menü und Strg+K,
   klare Titel, Tastaturfokus, reduzierte Animation/Transparenz. Persönliche
   explizite Einstellungen bleiben erhalten. Neue Konten starten dunkel.
2. **Fotos:** eigene Galerie mit Freigabenauswahl, paginierter Unterordnersuche,
   Dateinamensfilter, großer Vorschau und Tastaturnavigation. Ausschließlich
   authentifizierte bestehende Datei-Endpunkte; keine externen Foto-Dienste,
   keine zusätzliche Rechtefreigabe, kein Vollscan beim Desktopstart. Große und
   nicht direkt darstellbare Dateien erhalten eine verständliche Alternative.
3. **Bedienung:** einheitliche Fenster, Einstellungen und Dateimanager, mobile
   Ziele mindestens 44 px; Abmelden/Neustart/Herunterfahren bestätigen;
   Fehler und unvollständige Suchen ausdrücklich anzeigen.
4. **Regression:** Python/API, sämtliche UI-Suiten, Syntax, Lizenz-/Dateiliste,
   Browserprüfung von Desktop, Suche, Dateien, Fotos, Einstellungen und Dialogen
   bei Desktop- und Telefonbreite; neue Negativ-/Asynchronitätsfälle.
5. **GitHub:** nachvollziehbare Änderungen mit Plan und Nachweis veröffentlichen;
   CI und App-Abnahmen verfolgen; signierten Webcontainer und Systemimage über
   bestehende Build-/Boot-/Recovery-Pipeline erzeugen. Fehlgeschlagene Prüfungen
   reparieren; niemals Prüfungen entfernen, um eine Freigabe zu erzwingen.

## Stable-Kriterien und unterstützter Umfang

Kein bekannter Fehler mit Datenverlust oder unberechtigtem Dateizugriff im
geänderten Umfang; bestandene Quellprüfungen, reale Containerprüfung, signiertes
Image mit bestandenem UEFI-Start, SMB-/App-/VM-Laufzeitprüfung sowie Update,
Datenerhalt und Rollback. Release-Bericht und Prüfsummen müssen exakt den
veröffentlichten Commit/Artefakten entsprechen. Ein Quell-PR allein erfüllt das
Ziel nicht. Die Image-Veröffentlichung darf erst nach den vorhandenen Gates erfolgen.

Der getestete Zielumfang ist AMD64/UEFI und die dokumentierte VM-Testumgebung.
Physische Controller, USV, externe Cloudkonten und NAS-Dauerbetrieb werden nicht
als geprüft ausgegeben. Kein eigener OAuth-/Cloudspeicher, keine KI-Gesichtssuche,
keine HEIC-Konvertierung, keine inkrementelle Verschlüsselungs-Engine in dieser
Ausgabe. Bestehende Einschränkungen wie ZFS-only-Quoten, kalte VM-Sicherungen und
fehlender Konfigurationsimport auf beliebige Ersatzhardware bleiben ausdrücklich
dokumentiert. Backups werden nicht durch einen Systemrollback ersetzt.

## Ressourcen und Nachweise

Der lokale Host hat zu wenig freien Plattenplatz für das Systemimage und kein
verfügbares KVM-Gerät. Nur Quelltests und isolierte Demo laufen lokal. Die echten
Build-/Boot-/Containerprüfungen erfolgen auf den vorhandenen GitHub-Runnern.
Ergebnisse werden in `docs/VERIFY-0.7.0.md` mit tatsächlichem Status festgehalten.
