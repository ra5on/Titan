# Titan 0.4.16 Alpha · Systemsteuerung und Verwaltungsoberfläche

Titan verwendet jetzt eine einheitliche Desktop- und Verwaltungsoberfläche, orientiert an den öffentlich dokumentierten Bedienmustern von Synology DSM. Symbole, CSS, Texte und Implementierung sind eigene Titan-Bestandteile. Es werden keine Synology-Pakete oder Grafiken eingebunden.

## Bedienung

- Systemsteuerung mit durchsuchbarer Symbolübersicht, Kategorien und linker Bereichsauswahl. Benutzer, Freigaben, allgemeine Einstellungen, Updates und Rollback, Systemzustand, Komponenten, Dienste, Datensicherung und Protokoll öffnen im selben Fenster.
- Beim Bereichswechsel bleiben ungespeicherte Formulare nach einer Nein-Antwort erhalten; Ja verwirft sie. Vorhandene Berechtigungsprüfungen und Administratorgrenzen bleiben aktiv.
- Auf kleinen Bildschirmen ersetzt eine Auswahl die linke Systemnavigation. Werkzeugleisten und Fensterrahmen bleiben stehen, während der Inhalt scrollt.
- Speicherverwaltung mit einzelnen Ansichten für Systemplatte, vorhandene Datenbereiche, Laufwerke und gegebenenfalls ZFS-Diagnose und Wiederherstellungspunkte. Nur tatsächlich vorhandene Bereiche werden angeboten.
- App Store mit getrennten Ansichten für installierte Apps und Katalog; bestehende Suche, Kategorien, Sortierung, Login-Hinweise und Installationsdialoge bleiben verfügbar.
- Docker mit eigener Bereichsnavigation für Container, Stacks, Images, Volumes und Netzwerke. Containerdetails und Aktionen bleiben in derselben Anwendung.
- Einheitliche helle Fenster, kompakte Werkzeugleisten, Tabellen, Formulare, Dialoge und farbige Symbole für Dateimanager, VMs und die übrigen Werkzeuge. Drei eigene Desktop-Hintergründe.

Dies ist ein Umbau der vorhandenen Titan-Funktionen, keine Implementierung sämtlicher DSM-Dienste. Funktionen wie Synology QuickConnect, SHR oder Synology-Pakete gehören nicht zu Titan. Der Stand bleibt Alpha.

## Prüfung

959 Python-Tests erfolgreich (ein plattformabhängiger Test übersprungen). JavaScript-Regressionen einschließlich Bereichsrouting und bestehenden Formularen geprüft. Browserprüfungen mit schmalen und breiten Fenstern sowie mobiler Bereichsauswahl. Die Release-Pipeline prüft zusätzlich Boot, HTTPS, VM-Konsole, Update, Rollback und Fehlstart-Rückfall vor Veröffentlichung.

Referenz: [DSM-Benutzerhandbuch, Desktop und Verwaltungsbereiche](https://global.download.synology.com/download/Document/Software/UserGuide/Os/DSM/7.1/enu/Syno_UsersGuide_NAServer_7.1_enu.pdf).
