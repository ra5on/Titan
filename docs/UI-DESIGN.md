# Titan: Dashboard und Verwaltung

Stand: 7. Oktober 2026, Entwicklung für 0.5.8-alpha.1. Titan bleibt Alpha. Die älteren Abschnitte dokumentieren die Entwicklung der Oberfläche; die aktuelle Ergänzung steht unter [Desktop und Dialoge ab 0.5.6](#desktop-und-dialoge-ab-056). „VDSM“ verstehen wir hier als die Bedienidee von Synology DSM bzw. Virtual DSM, nicht als eine zusätzliche Titan-Laufzeit.

## Was die Recherche hergibt

Diese Auswahl ist eine kleine qualitative Stichprobe öffentlich auffindbarer Erfahrungsberichte. Sie enthält positive und negative Rückmeldungen, teils zu älteren Versionen. Sie ist weder eine Nutzerumfrage noch ein repräsentativer Beliebtheitsvergleich. Einzelne Fehlerberichte beweisen keinen allgemeinen Produktmangel. Herstellerdokumentation erklärt die Organisation, ersetzt aber keine Nutzererfahrung. Die beiden CasaOS-Berichte wurden vollständig im Browserwerkzeug gelesen; der DSM-Forenbericht wurde im abschließenden Quellencheck gelesen. Nur als Suchtreffer gelesene, später nicht erneut abrufbare Beiträge wurden durch diese überprüften Quellen ersetzt.

| Quelle | Beobachtung | Schluss für Titan |
| --- | --- | --- |
| [Anyone tried CasaOS?](https://lowendspirit.com/discussion/8494/anyone-tried-casaos), Oktober/November 2024 | Nutzer berichten von einfacher App-Verwaltung und einem hilfreichen Dashboard. Ein Nutzer beschreibt in derselben Diskussion einen zeitweise unerreichbaren Zugang. | App-Kacheln und direkte Installation behalten; Status und Fehler sichtbar machen. |
| [CasaOS: Apps finden eingehängtes Laufwerk nicht, Issue #1765](https://github.com/IceWhaleTech/CasaOS/issues/1765), April 2024, inzwischen geschlossen | Ein Nutzer berichtet, dass Jellyfin/Plex die Inhalte eines eingehängten Datenlaufwerks nicht sehen. | Speicherbereiche vor der Installation benennen und auswählen lassen. Berechtigungen und tatsächliche Verfügbarkeit erklären. |
| [DSM: Container Manager als Desktop-Verknüpfung](https://www.reddit.com/r/synology/comments/1apmauc), Februar 2024 | Ein Nutzer sucht die Verknüpfung zum Container Manager; die Lösung führt über das Hauptmenü. | Werkzeuge über eine feste Navigation und eine zentrale Verwaltung erreichbar machen. Direkter Zugriff über Navigation und Verwaltung; ab v0.4.5 zusätzlich ein NAS-Desktop nach der ausdrücklich gewünschten FygoOS-Vorlage. |
| [Synology DS725+ Hands-on](https://www.techradar.com/pro/synology-ds725-nas-review), 2026 | Der Tester beschreibt einfache Einrichtung und Nutzung auf Telefon, Tablet und Desktop sowie verständliche Volume-Verwaltung. | Durchgängige responsive Formulare; Laufwerke und Aufgaben mit verständlichen Namen darstellen. |
| [CasaOS – offizielle Produktseite](https://casaos.zimaspace.com/) | Dashboard und App-Installation stehen im Vordergrund. | Persönliche Übersicht mit Apps, Dateien und echten Statuswerten behalten. |
| [Synology Package Center](https://kb.synology.com/en-me/DSM/tutorial/How_to_install_applications_with_Package_Center), aktualisiert Mai 2026; [DSM-7.3-Handbuch](https://global.synologydownload.com/download/Document/Software/UserGuide/Os/DSM/7.3/enu/Syno_UsersGuide_NAServer_7_3_enu.pdf) | Paketverwaltung und Systemverwaltung sind als eigene Aufgaben organisiert. | App Store, Dateimanager, Speicher und Systemverwaltung klar trennen und gegenseitig verlinken. |

Der Hybridansatz ist unsere Designentscheidung aus diesen Hinweisen und den Titan-Anforderungen. Daraus lässt sich kein objektiver Sieger zwischen CasaOS und DSM ableiten.

## Konkrete Oberfläche

- **Übersicht:** gespeicherte, verschiebbare Kacheln für den täglichen Blick. CPU-Auslastung kommt aus echten CPU-Zeitdifferenzen; Load bleibt separat. Fehlende Temperaturwerte werden nicht erfunden. Der Verlauf verwendet echte Messzeitpunkte und zeigt Messlücken. Die Demo kennzeichnet Beispieldaten.
- **Verwaltung:** eigener Einstieg mit Aufgabenbereichen Dateien/Speicher, Anwendungen/Virtualisierung und NAS-Verwaltung. Eine Suche findet Werkzeuge anhand von Name und Zweck. Alle Seiten sind über das Hauptmenü und die Aufgabenbereiche erreichbar.
- **App Store:** installierte Apps oben, entdeckbare Vorlagen darunter. Suche über Name, Beschreibung und Kategorie; kombinierbare Filter für Kategorie und Installationsstatus; sichtbare Trefferzahl. 42 gepflegte Vorlagen mit „Details & Anmeldung“ erklären Standardzugänge, Erst-Einrichtung, selbst gewählte oder temporär generierte Kennwörter. Die Hinweise stehen vor Installation und beim Verwalten zur Verfügung. Das Formular zeigt ausschließlich die Optionen der kuratierten Vorlage. Persönliche Passwörter werden als Passwortfelder erfasst und nicht wieder ausgelesen.
- **Dienste:** eine Liste mit Suche und Zustandsfilter. Der Dienstname öffnet Details, Logs, Autostart, erlaubte Aktionen und – soweit tatsächlich verfügbar – Prozessmetriken und Abhängigkeiten. Geschützte Titan-Zugangsdienste bleiben erkennbar.
- **Pfadauswahl:** VM-Speicher, ISO-Bibliothek, Laufwerksimages und Freigaben verwenden vorhandene benannte Dropdowns. Apps wählen eine freigegebene Datenquelle mit passendem Dienstkontozugriff. Sicherungsziele und Dienst-Arbeitsverzeichnisse wählen jetzt benannte Speicherorte und vorhandene Unterordner; ein technischer Pfad ist zusätzliche Information. Eigene Dienstprogramme sind eine ausdrücklich erweiterte Option.

## Daten- und Sicherheitsgrenzen der Auswahl

`GET /api/storage-locations` steht nur Administratoren offen und verändert keine Laufwerke. Die Liste basiert auf vorhandenen Verzeichnissen, Freigaben und eingehängten Laufwerken. Als Backupziel werden nur vom bestehenden Backupvalidator geprüfte separate beschreibbare Dateisysteme angeboten. Zusätzliche eingehängte Orte `/var/mnt` und `/var/media` werden unterstützt. Unverfügbare oder nicht sicher geprüfte Laufwerke werden nicht als Sicherungsziele angeboten.

Der Ordnerpicker verwendet die bestehende Administrator-Dateiliste, respektiert deren Lesbarkeit, überspringt symbolische Links und bietet weitere Seiten bei großen Ordnern an. Das Auswählen ersetzt keine Backendprüfung: jede eigentliche Aktion prüft Rechte, Mounts und Pfade erneut. Die Auswahlliste kann sich zwischen Anzeige und Ausführung ändern.

App-Datenbindung bleibt bewusst auf verwaltete Freigaben begrenzt. Das Formular bietet keine freien Compose-Texte, Umgebungsvariablen oder ungeprüften Host-Mounts. Titan-App-Konfiguration, App-Nutzdaten und Docker-interne Images sind unterschiedliche Speicherbereiche; das Auswählen einer Freigabe verschiebt nicht den globalen Docker-Datenbestand.

## Verifikation

Gezielte Node-Regressionen prüfen Such-/Filterkombinationen, nur kuratierte App-Optionen, Passwortfelder, Escaping, bestehende Unterordner, Mount-Auswahl, Paging und das Verwerfen verspäteter Antworten nach dem Verlassen eines Pickers. Python-Tests prüfen verfügbare Mounts, ausgeschlossene unsichere Sicherungsziele, fehlende Verzeichnisse, doppelte Einträge und Lookupfehler.

Im zusammengeführten Stand wurde die isolierte Demo auf Desktop und bei 390 px geprüft: Verwaltung, Navigation, App-Suche/Kategorien/Installationsoptionen, Backup-Laufwerksauswahl mit Unterordnern und Dienstanlage mit Programm-/Ordnerauswahl. Die Dienstanlage erzeugte einen erfolgreichen Demo-Auftrag. Die mobile Ansicht zeigte keinen horizontalen Überlauf. Gefundene Fokusprobleme beim Ordnerwechsel, Dialogschließen und Speichern wurden korrigiert und gezielt durch Node-Regressionen abgesichert.

Screenshots: [Verwaltung Desktop](images/titan-040-control-desktop.png), [Verwaltung Mobil](images/titan-040-control-mobile.png), [App Store Desktop](images/titan-040-appstore-desktop.png). Die zusätzliche HTTP-Regression bestätigt, dass normale Nutzer keine Speicherortliste erhalten (403) und Administratoren den richtigen Leseaufruf auslösen (200). Die abschließende Browserprobe bestätigte 26 App-Vorlagen, passende Kategoriefilter sowie den erhaltenen Fokus nach Ordnerauswahl und dem Speichern der Sicherungseinstellungen.

Die Prüfung für v0.4.1 bestätigt zusätzlich 42 Vorlagen, öffentliche Standardzugänge im Detail- und Installationsdialog sowie den fokussierten Sprung aus einer installierten Demo-App zum Protokoll. Die 390-Pixel-Ansicht zeigt keinen horizontalen Überlauf. Die Kopierfunktion bietet bei nicht verfügbarem Browser-Clipboard einen markierten Wert zum manuellen Kopieren.

Eine Demo bestätigt Bedienabläufe, ersetzt aber keine reale App-Installation, Berechtigungsprüfung auf einem NAS oder einen Image-Starttest.

## Dateimanager und Hauptmenü ab v0.4.4

Jede bearbeitbare reguläre Datei bietet einen Stift direkt in der Zeile und die Taste F4. Die Vorschau prüft UTF-8-Inhalt anstelle einer Liste erlaubter Textendungen. Der Editor speichert mit Strg/Cmd+S oder dem Speichern-Knopf, bleibt geöffnet und zeigt Änderung, Dateigröße, Zeile/Spalte sowie Speichern/Fehler an. BOM und einheitliche LF-, CRLF- oder CR-Zeilenenden bleiben erhalten; gemischte Zeilenenden werden erst bei einer gespeicherten Änderung ausdrücklich auf LF vereinheitlicht. Binäre Inhalte, zu große Dateien und schreibgeschützte Ziele werden nicht überschrieben. Titan prüft die gelesene Dateiversion vor dem Schreiben und die gespeicherten Bytes anschließend erneut.

Die Dateimanager-Seite nutzt die sichtbare Fensterhöhe: Befehle, Pfad und Suche bleiben stehen, Dateiorte und Inhalte scrollen innerhalb ihrer Bereiche. Auf Mobilgeräten sind Liste und Eigenschaften gemeinsam erreichbar. Sehr kurze Fenster erhalten einen vertikalen Scroll-Fallback, damit die Aktionen erreichbar bleiben.

Über den Knopf links in der Kopfzeile lässt sich die Desktop-Navigation auf Symbole reduzieren. Namen bleiben über Tooltips und barrierefreie Beschriftungen verfügbar. Ab v0.4.5 startet sie auf Desktop und Tablet ohne gespeicherte Einstellung platzsparend; die persönliche Auswahl hat Vorrang. Sie wird im Browser pro Benutzer gespeichert. Bis 760 Pixeln bleibt die Navigation ein aufklappbares Menü mit Escape- und Fokussteuerung.


## NAS-Desktop ab v0.4.5

Auf ausdrücklichen Wunsch dient [FygoOS](https://fygonas.com/de-DE) als neue Bedienvorlage. Die öffentlich sichtbaren Desktop-, Datei- und VM-Ansichten wurden im Browser gelesen: farbige App-Symbole, ein schmales Dock, helle Verwaltungsfenster mit interner Navigation und direkt auswählbare Systembereiche. Titan verwendet eigene SVG-Symbole und einen CSS-Hintergrund; Markenbilder und Produktgrafiken werden nicht übernommen.

Der Desktop zeigt zwölf direkte Werkzeuge und daneben die bisherigen sechs Statuskarten. Die gespeicherte Reihenfolge bleibt erhalten, CPU/RAM und Uhrzeit aktualisieren sich weiter. Appseiten haben eine Titelleiste mit echter Rückkehr zum Desktop und einem Knopf für mehr Fensterbreite. Eine vorhandene Menüpräferenz bleibt gültig; neue Desktop-Sitzungen beginnen mit dem kompakten Dock. Das Dock scrollt bei geringer Höhe und hält das Konto erreichbar.

Das Einstellungszentrum bietet zehn Kategorien mit kombinierbarer Suche. Server/Zugriff, Update-Kanal und Komponentenprüfung haben eigene Unterseiten. Getrennte Formulare bewahren alle ausgeblendeten Werte; das Speichern des Servernamens ändert keine Update-Einstellung. Die weiteren Kategorien öffnen die bestehenden Verwaltungsbereiche.

VM- und Docker-Manager ordnen ihre Daten mit internen Tabs, Suche und Statusfilter. Die VM-Ansichten zeigen Maschinen, konfigurierte Ressourcensummen, ISO-Medien und tatsächliche Host-CPUs inklusive zuverlässig gemeldeter P-/E-Kerne. Es werden keine nicht gemessenen Gast-Auslastungen erfunden. Docker zeigt verwaltete Apps, Status, Adressen und die vorhandenen Steuerungs-, Anmelde- und Netzwerkaktionen. Der separate App Store behält 42 Vorlagen und Installationsoptionen. Tabs und Filter bleiben innerhalb der Sitzung pro Konto erhalten.

Der Dateimanager behält System-/Freigabeorte, Listen-/Symbolansicht, Vorschau, direkten Texteditor und feste Befehlsleisten. Alle Verwaltungsseiten, Formulare, Dialoge, Diagramme und Hinweise verwenden das neue helle Thema. Auf dem Telefon werden die internen Manager-Tabs horizontal und die Einstellungs-Kacheln untereinander angezeigt.


## Gemeinsamer Fensterrahmen und Hauptmenü ab v0.4.6

v0.4.6 ersetzt die oben historisch beschriebenen Seitenleisten-/Dockvarianten vollständig. Die globale linke Navigation und ihr Drawer-Code sind entfernt. Hauptmenü, Meldungen, Aufträge und Konto sind beschriftete Schaltflächen in der Kopfzeile. Die internen, auf die jeweilige App begrenzten Ansichten von VM-/Docker-Manager sowie die Dateiorte bleiben erhalten.

Die erneut betrachteten öffentlichen [FygoOS-Ansichten](https://fygonas.com/de-DE) zeigen ruhige Verwaltungsfenster und kompakte Anwendungssymbole. Die offiziellen Beschreibungen von [Synology DSM](https://kb.synology.com/index.php/en-us/DSM/help/DSM/MainMenu/get_started?version=7) und [QNAP QTS](https://docs.qnap.com/operating-system/qts/5.1.x/en-us/desktop-CEDCE7CF.html) dienen zusätzlich als Orientierung für Hauptmenü, Appfenster und Desktop. Die folgenden Maße sind eigene Titan-Entscheidungen, keine übernommenen Herstellervorgaben.

- Appfenster sind normalerweise maximal 1080 px (Einstellungen), 1120 px (Verwaltung), 1200 px (Terminal), 1280 px (Dateien/VMs/Docker) oder 1360 px (App Store) breit und höchstens 820 px hoch. Verfügbarer Platz und Browserzoom begrenzen diese Maße immer. Maximieren nutzt die gesamte Arbeitsfläche; die Wahl bleibt pro Konto und App gespeichert.
- Auf breiten Desktops lässt sich die Größe über den nativen Griff rechts unten verändern. Container-Abfragen passen VM-/Docker-Inhalte an die tatsächliche Fensterbreite an. Bis 1000 px werden Apps automatisch flächig; die manuell gewählte Desktopgröße kann dies nicht übersteuern.
- Das Hauptmenü verwendet 112 px breite Appkacheln mit 56 px großen Symbolen. Bei geringerer Breite sind die Symbole 48 px groß. Mehr Platz erzeugt mehr Spalten statt immer größerer Symbole. Einstellungs-Kacheln verwenden ein einheitliches Raster innerhalb aller Kategorien.
- Hauptmenü und Statuskarten scrollen am Desktop unabhängig. Alle Verwaltungsfenster begrenzen die Inhaltshöhe; Fensterkopf, Manager-Navigation und Befehle bleiben erreichbar. Bei sehr geringer Höhe wird ausdrücklich der gesamte Appinhalt scrollbar. Dateiaktionen behalten die bestehenden eigenen Scrollbereiche.
- Der Telefonkopf hält die Beschriftung „Aufträge“ auch bei 320 px sichtbar. Dialoge, mehrspaltige Formulare, Tabellen, Dateimanager, Appkatalog und Verwaltungsseiten passen sich dem verfügbaren Platz an. Bewegungsreduzierung wird respektiert.

Der native Größenwechsel verändert weder NAS-Daten noch die laufenden Dienste. Das Schließen einer Appansicht kehrt zum Hauptmenü zurück; bestehende Lebenszyklen von Terminal, Pickern und Live-Abfragen bleiben erhalten.


## Einheitliche Arbeitsbereiche ab 0.5.2

Die aktuelle Verwaltung folgt dem DSM-Prinzip mit klarer Bereichsnavigation, einer Auswahl mit zugehörigen Details und erreichbaren Aktionen. Dateimanager, VM-Verwaltung, Docker und Speicher besitzen jeweils ihre eigene Arbeitsfläche. Die Systemsteuerung bleibt der zentrale Zugang zu Benutzern, Rechten, Diensten, Updates und Sicherungen. Die oben beschriebenen älteren Varianten sind Entwicklungsgeschichte.

Dateiorte lassen sich links/rechts platzieren und per Trennlinie auf 160–360 Pixel einstellen; die Benutzerpräferenz bleibt erhalten. Mobile Dateiorte erscheinen als Schublade. Bei einer langen Dateiliste bleiben Werkzeugleiste und Auswahlaktionen sichtbar. Die VM-Navigation verwendet am Desktop 148 Pixel, Details eine zusätzliche kompakte Maschinenliste. Schmale Ansichten zeigen eine Ebene mit Zurück-Navigation; die Konsole erhält die volle Arbeitsfläche.

Docker gliedert sich in Übersicht, Projekte, Container, Images, Netzwerke und Volumes. Speicher gliedert sich in Übersicht, Speicherbereiche, HDD/SSD und Wartung, mit Systemkapazität und verschachtelten ZFS-Datenbereichen. Die Anwendung verwendet einen eigenen Inhaltsklassennamen, damit frühere Dashboard-Stile ihre Geometrie nicht überlagern. Historische allgemeine VM-Manager-Regeln sind auf den alten Docker-Fallback beschränkt.

Tatsächliche Browserprüfung bei 1366 Pixel Desktop sowie 320/390 Pixel Mobil, Controller-Regressionen und getrennte Release-Prüfungen: [QA 0.5.2](QA-0.5.2.md). Eigene Symbole, Styles und Code; Herstellerassets werden nicht übernommen.


## Platz und Desktop-Einstellungen ab 0.5.5

Die VM-Übersicht verwendet ein anpassbares Kachelraster mit Name, Status, gemessener CPU und **RAM auf NAS (RSS)**. Die Werte werden bei sichtbarer Ansicht alle fünf Sekunden abgefragt. Ein Klick öffnet die Details über die nutzbare Fensterfläche; eine dauerhafte zweite Maschinenliste entfällt. Zurück erhält Suche, Filter und Tastaturfokus. Die Konsole bekommt die große Inhaltsfläche. Fehlende Messungen erscheinen als solche, nicht als erfundene Gast-Auslastung.

Im App Store scrollen die kompakte Ansichtsleiste, Katalogaktionen, Hinweise, Suche und Apps zusammen. Der obere Bereich bleibt nicht über der App-Liste stehen. Die gewählte Ansicht und Filter bleiben erhalten.

Die internen Seitenleisten von Systemsteuerung, Speicher, Docker und VM-Verwaltung lassen sich an ihrer Trennlinie schmaler oder breiter ziehen. Die Breite wird im Browser pro Konto und Arbeitsbereich gespeichert. Pfeiltasten verändern sie um 16 Pixel, mit Umschalt um 32 Pixel; Pos1/Ende wählen die verfügbare Mindest-/Maximalbreite, Doppelklick den Standard. Die Navigation liegt normalerweise zwischen 128 und 360 Pixeln; der verbleibende Inhalt begrenzt die tatsächliche Breite. Docker-Details und der rechte Detailbereich der Benutzerverwaltung lassen sich bei genügend Platz zwischen 240 und 520 Pixeln einstellen. Bis 760 Pixeln entfällt der Griff; die kompakte mobile Navigation bleibt erhalten. Der Dateimanager behält seine eigene verstellbare Ortsleiste. In VM-Details wird die Seitenleiste ausgeblendet.

Das Benutzermenü mit Abmelden, Neustart und Herunterfahren enthält außerdem **Transparenz** und **Klick auf freien Desktop**. Dieselben Einstellungen sind unter **Persönlich** erreichbar. Die Auswahl gilt für das jeweilige Konto und wird auf dem NAS zusammen mit der Desktop-Anordnung gespeichert. Standardmäßig bewirkt ein freier Desktopklick nichts; **Alle Fenster minimieren** blendet die offenen Fenster aus und erhält ihre laufenden Inhalte. Klicks auf App-Symbole, Fenster, Menüs oder Bedienelemente lösen dies nicht aus.

Der Transparenzregler reicht von 0 % (undurchsichtig) bis 100 % (höchste Transparenz), Standard 40 %. Er verändert die Hintergründe der Desktop-Oberflächen und Fensterköpfe, nicht die Deckkraft von Text oder App-Inhalten. Betriebssystemwünsche für reduzierte Transparenz oder stärkeren Kontrast erhalten eine undurchsichtige Darstellung. Bei fehlgeschlagenem Laden der Desktop-Einstellungen bleiben die Änderungen gesperrt, damit der gespeicherte Stand erhalten bleibt.

## Desktop und Dialoge ab 0.5.6

Im **Kontomenü → Darstellung** stehen **Hell**, **Dunkel** und **Automatisch** zur Wahl. Standard ist Hell; Automatisch folgt dem hellen oder dunklen Betriebssystemthema und reagiert auf dessen Änderung. Die Auswahl wird mit den Desktop-Einstellungen pro Konto auf dem NAS gespeichert. Bereits geöffnete Titan-Appfenster erhalten den neuen Modus und die gewählte Transparenz unmittelbar; neue Fenster übernehmen den aktuellen Stand. Beim Abmelden wird die Darstellung zurückgesetzt. Die zugelassenen Werte werden auf Client und Server geprüft.

Die eigene Glasoptik betrifft Desktop-Kopfzeile, Fensterköpfe, Menüs und Statuswidgets. App-Inhalte und Text bleiben deckend und lesbar; bei reduzierter Transparenz, stärkerem Kontrast oder fehlender Unterstützung für Hintergrundunschärfe verwendet Titan deckende Flächen. TitanOS dient auf ausdrücklichen Wunsch als **visuelle Inspiration**. Die Umsetzung besteht aus eigenem Titan-Code, eigenen Styles und den bestehenden eigenen Symbolen; TitanOS-Code oder -Assets werden nicht übernommen.

**Schnellaktionen** lassen sich auf Symbolen des Desktops und des Hauptmenüs per Rechtsklick, längerem Drücken für **550 ms**, **Umschalt+F10** beziehungsweise Kontextmenütaste oder über **⋯** öffnen. Pfeiltasten und Pos1/Ende bewegen den Fokus im Menü; Escape oder Tab schließen es und geben den Fokus zurück. Längeres Drücken öffnet die Aktionen, ohne die App zusätzlich zu starten. Je nach Eintrag und bestehenden Rechten sind Öffnen, Einstellungen und Details, Starten/Stoppen, Desktop-Verknüpfungen und Ordneraktionen verfügbar.

**Vom Desktop entfernen** entfernt nur eine Verknüpfung. Die Anwendung bleibt installiert und über das Hauptmenü erreichbar. **App deinstallieren …** ist eine getrennte Aktion mit ausdrücklicher Ja/Nein-Bestätigung; Titan stoppt und deinstalliert das App-Paket, erhält aber Konfiguration, Datenbanken und Nutzdaten. Ein ausgeblendetes oder fehlendes Bedienrecht wird durch Schnellaktionen nicht erweitert.

Die vorhandenen **Statuswidgets für Administratoren** erhalten einen Verschiebegriff. Am Griff ziehen oder ihn fokussieren und mit den Pfeiltasten bewegen: normal um 24 Pixel, mit Umschalt um 4 Pixel. Die Position wird pro Konto auf dem NAS gespeichert und an die verfügbare Desktopfläche angepasst. Escape beziehungsweise ein abgebrochener Zeigerzug stellt die Ausgangsposition wieder her. CPU, RAM, Systemstatus, Meldungen und Aktivität bleiben an die bisherigen Administratorrechte gebunden.

**Bestätigungen zeigen die positive Aktion links, Nein beziehungsweise Abbrechen rechts.** Das gilt auch für eigene Dialoge, etwa Widget-Einstellungen, Root-Freigabe, Wiederherstellung und Texteditor. Ja/Nein-Abfragen fokussieren zunächst Nein; erst eine ausdrückliche positive Betätigung führt die Aktion aus. Vor der Bestätigung brechen Escape und Schließen die Abfrage ab. Der Texteditor zeigt „Änderungen verwerfen und schließen“ links und „Weiter bearbeiten“ rechts; beim Schutz ungespeicherter Änderungen bleibt Weiter bearbeiten die fokussierte Wahl. Reguläre Formularfelder und die Rückkehr zum auslösenden Bedienelement behalten ihre Fokusregeln.

Docker, Speicher, Systemsteuerung, Benutzerverwaltung und App-Details verwenden kompaktere Abstände und auf die Fensterhöhe abgestimmte Scrollbereiche. In Docker scrollen Befehle und Inhalt gemeinsam; der Detailbereich besitzt einen eigenen gemeinsamen Scroller einschließlich Kopf und Protokoll. Im Speicher-Manager scrollt der rechte Arbeitsbereich mit seinen Aktionen, während die Navigation unabhängig bleibt. Formularaktionen folgen den Feldern und überdecken keine letzten Eingaben. App-Protokolle und lange Hinweise erhalten weniger verschachtelte Scrollflächen. Schmale und kurze Fenster behalten erreichbare Aktionen; Dateimanager und VM-Konsole bewahren ihre eigenen Arbeitsflächen und Lebenszyklen.

Regressionen prüfen Theme-Nachrichten nur zwischen eigenen Appfenstern derselben Origin, den Wechsel des Systemthemas, pro Konto gespeicherte Werte, beschädigte Einstellungen und Listener-Bereinigung. Weitere UI-Tests prüfen Schnellaktionen einschließlich Touch und Tastatur, die Trennung von Verknüpfung und Deinstallation, Widget-Positionen sowie Bestätigungsaktionen und Fokus. Diese Bedienprüfungen ersetzen weiterhin keine reale App-, NAS- oder Imageprüfung. Veröffentlichung und Imagefreigabe werden im [Release 0.5.6](RELEASE-0.5.6.md) ausgewiesen.


## Korrekturen ab 0.5.7

Hell und Dunkel verwenden durchgängig gemeinsame Flächen-, Text-, Fokus- und Statusfarben. Feste helle Formularleisten, Docker-Protokollflächen und Benutzer-/Sicherheitsbereiche sind ersetzt; Erfolg, Warnung und Fehler behalten eigene Bedeutungen. Das Kontomenü bietet drei direkt erreichbare Tasten **Hell**, **Dunkel**, **Auto** und den persönlichen Transparenzregler. App-Symbole erhalten keinen zusätzlichen Rahmen um ihr vorhandenes Artwork; Fokus und Auswahl bleiben sichtbar.

**Widgets hinzufügen** öffnet eine Galerie mit Vorschau und getrennten Hinzufügen-/Entfernen-Aktionen. Jede CPU-, RAM-, Systemstatus-, Meldungs-, Aktivitäts- und Uhr-Karte besitzt einen eigenen Verschiebegriff und eine eigene gespeicherte Position. Eine leere oder ausgeblendete Auswahl kann jederzeit aus Kopfzeile, Kontomenü, Hauptmenü oder Desktop-Menü erweitert werden. Die Uhr ist auch für normale Konten verfügbar; Systemmesswerte bleiben an Administratorrechte gebunden.

Das freie Desktop-Menü bietet gruppierte Aktionen mit Symbolen und Beschreibungen: Widgets, App-Verknüpfungen, Ordner, Darstellung und Symbolgröße. Rechtsklick, langes Drücken und Tastaturbedienung funktionieren auch auf der freien Desktopfläche. Die vorhandenen App-Schnellaktionen im Hauptmenü und auf dem Desktop bleiben erhalten.


## Eigene Apps ab 0.5.8

Der frühere AppStore und seine externe Katalogsuche entfallen. **Apps** zeigt zunächst eine eigene Compose-App: **Cloudflare Tunnel**. Token und optionale öffentliche HTTPS-Adresse reichen für den Installationsauftrag. Die Installation zeigt acht tatsächlich ausgeführte Schritte; ihr Verlauf bleibt nach Schließen und Neuladen erhalten. Eine unterbrochene Einrichtung kann ohne erneute Token-Eingabe fortgesetzt werden. Historischer Installationsabschluss und aktueller Verbindungsstatus werden getrennt dargestellt.

Der gesamte Apps-Inhalt scrollt gemeinsam; ein hoher feststehender Store-Balken entfällt. Schmale Fenster ordnen Konfiguration und Verlauf untereinander. Farben folgen Hell, Dunkel und Auto. Die bisherige Cloudflare-Karte der Systemsteuerung ist entfernt. Bereits installierte Apps bleiben als kompakte Liste erreichbar; Docker öffnet die vorhandene Verwaltung. Die älteren Store-Abbildungen und Beschreibungen oben dokumentieren frühere Versionen.

## Titan 0.5.9: ruhige Aktualisierung und Schnellaktionen

Desktop-Widgets behalten beim Aktualisieren ihre DOM-Karten, Kopfzeilen und Bedienelemente. Nur Messwerte und Beschriftungen werden angepasst. VM-Details halten bei einem Poll die aktuelle Ansicht; insbesondere bleibt die Konsole im Dokument verbunden. Auswahl und Scrollposition bleiben erhalten, ein Fehler wird innerhalb der vorhandenen Ansicht angezeigt.

Der Dateimanager startet mit einer kompakten Werkzeugleiste. Eine leere Auswahlleiste ist ausgeblendet; der Detailbereich kann separat ein- und ausgeblendet werden. Rechtsklick, Langdruck und Umschalt+F10 öffnen passende Aktionen am Eintrag beziehungsweise im freien Ordnerbereich. Mehrere Dateien können per Drag-and-drop in einen beschreibbaren Ordner geladen werden. Fortschritt und Abbrechen-Button bleiben während der Übertragung stabil.

Andere Anwendungsmenüs verwenden die vorhandenen Aktionsschaltflächen als Quelle. Damit gelten weiterhin dieselben Rechte, Bestätigungen und deaktivierten Zustände. Das Titan-Terminal und die VM-Konsole besitzen eigene kontextspezifische Menüs. Eine Gast-Rechtsklickoption erhält den Zugriff auf Kontextmenüs innerhalb der VM.

Die Screenshots im README stammen aus Titans eigener Demo. TitanOS wurde ausschließlich als visuelle Referenz verwendet; dessen Quellcode und Assets wurden nicht übernommen.
