# Prüfungen für Titan 0.6.0

Stand: 8. Oktober 2026. Die folgenden Abschnitte unterscheiden frühere lokale Prüfungen, den abschließenden Menü-Durchlauf und den [veröffentlichten Image-Nachweis für alpha.4](#veröffentlichter-image-nachweis--alpha4). Lokale Vorschau, GitHub-Tests und Prüfungen des gebooteten Images sind jeweils gesondert ausgewiesen.

## Frühere Prüfungen für 0.6.0

| Prüfung | Ergebnis |
| --- | --- |
| Python-Suite | 1.875 Tests, erfolgreich, 12 ausdrücklich übersprungen |
| UI-Testdateien | 73 Dateien erfolgreich; einschließlich neuer Desktop-, Store-, Dateiansicht-, Settings- und Konsolenregressionen |
| JavaScript und Shellsyntax | 47 Frontendmodule und vorhandene Shellskripte erfolgreich geprüft |
| Debian-Paket | `titan-debian-preview_0.6.0+debian1_amd64.deb` erfolgreich gebaut |
| Patchformat | `git diff --check` ohne Fehler |

Zusätzliche Quellenprüfung: 61 gezielte Tests für versionsgenaue Sammlung, historische signierte APT-Archive, Tarinhalt, fehlende Teile, Paketzuordnung und Veröffentlichungsgrenzen erfolgreich. Isolierte Tests verwenden ein Schlüsselbund-Fixture; eine eigene Prüfung bestätigt den Abbruch der echten Sammlung bei fehlendem Debian-Schlüsselbund. Der Offline-Buildgast nutzt während der Sammlung temporär das Appliance-Netz; Tests bestätigen die Wiederherstellung seiner Resolver-Datei bei Erfolg und Fehlern sowie die Ablehnung dieses Modus bei der Host-Verifikation. Zwei echte Quelldownloads wurden geprüft: `hello=2.10-5` aus aktuellen signierten Trixie-Indizes und die nicht mehr aktuelle eingebettete Quelle `golang-fsnotify=1.8.0-1` aus dem authentifizierten Snapshot `20241110T083149Z` (`sid/main`). DSC-Identität, Dateigrößen und SHA-256 stimmen. Ein daraus erzeugtes GNU-Tar wurde über mehrere Teile gestreamt und vollständig verifiziert. Das ist ergänzende Werkzeugprüfung; die vollständige Sammlung aller Image-Pakete muss zusätzlich im Release-Build bestehen.

Im Browser geprüft: frischer Desktop mit Begrüßung, Widgetreihe und Dock; Hinzufügen einer Uhr; Hell-/Dunkel-Wechsel; Einstellungsfilter, Suche und Unterseiten; Seitenleistenänderung mit Maus und Tastatur; Dateisymbole und Ansichtspopover; AppStore-Suche, Detail-/Rücknavigation und Scrollen; Docker-Details; VM-Kacheln und Sicherungsansicht; Terminal-Verbindung, Rechtsklick-Menü und bestätigtes Schließen. Die AppStore-Ansicht wurde zusätzlich bei 390 Pixeln Breite geprüft und hatte keinen horizontalen Dokumentüberlauf. Die geprüften Sitzungen zeigten keine Browserwarnungen oder JavaScript-Fehler.

Für 0.6.0-alpha.2 ergänzte Regressionen prüfen den entfernten letzten App-Container, erhaltene Konfiguration und Nutzdaten, teilweise vorhandene Verbünde, gestoppte Container und Fehler bei Docker-Abfragen. UI-Tests prüfen den Vorrang des aktuellen Status gegenüber alten Registry-Einträgen, den Filter „Installiert“, bewusstes Wiedererstellen mit gespeicherten Einstellungen, den Statusabgleich vor der Aktion und vertrauensgebundene Aktualisierungen geöffneter Store-Fenster. Eingaben, Fokus und Scrollposition bleiben dabei erhalten. Eine isolierte Browseransicht mit Beispieldaten bestätigte die Darstellung „Container entfernt“ mit „Neu erstellen“, „Noch nicht installiert“ und „App gestoppt“ ohne JavaScript-Fehler; diese Vorschau selbst führt keine Docker-Aktionen aus.

Der Cloudflare-Release-Smoke prüft zusätzlich die Entfernung über den produktiven Docker-HTTP-Job, den anschließenden Store-Status, unveränderte Konfigurations-/Token-Dateien samt Dateirechten und den Erhalt eines Nutzdatenmarkers. Eine erneute Store-Installation muss einen frischen Container erstellen. Der absichtlich ungültige Testtoken darf dabei keine erfolgreiche externe Verbindung vortäuschen. Fünf zusätzliche Harness-Tests prüfen auch, dass falsche Statusangaben, Datenverlust und unzutreffende Erfolgsnachweise diesen Gate-Test scheitern lassen. Der echte Docker-Lauf muss im Release-Workflow erfolgreich sein.

Für 0.6.0-alpha.3 nutzt auch die HTTP-Suite die produktive Webserverklasse. Ein zusätzlicher Netzwerktest baut bei pausierter Annahmeschleife 64 echte Loopback-Verbindungen auf, stellt danach HTTP/1.1-Anfragen an den produktiven Handler und prüft alle 64 Session-Antworten. Die kontrollierte Gegenprobe mit dem bisherigen Backlog von fünf scheitert nach sechs Verbindungen; mit 128 besteht sie. Der Test bestätigt die Warteschlangenkapazität und vollständige HTTP-Antworten, nicht das Ausbleiben jeder Kernelwarnung auf beliebiger Hardware. Alle Clients, Server und Testthreads werden geschlossen.

README-Abbildungen wurden aus dieser Titan-Demo aufgenommen. Beispieldaten sind erkennbar. Die neuen Landschaften, Toolbar-Grafiken und Store-Illustrationen wurden eigenständig erstellt; UmbrelOS/TitanOS-Code und Assets wurden für diesen Umbau nicht kopiert. Ein Hashvergleich der Webdateien fand keine vollständig identischen Webdateien im lokalen TitanOS-Bestand. Das ist ein begrenzter technischer Herkunftscheck und keine vollständige Lizenz- oder Gestaltungsrechtsprüfung; siehe [LICENSING.md](LICENSING.md).

Die Demo bestätigt keine Installation auf einem echten NAS und keine Verbindung über ein echtes Cloudflare- oder Tailscale-Konto. Die Konsole wurde zuvor mit einer isolierten QEMU-Firmware geprüft; dynamische Auflösung und Gast-Zwischenablage eines konkreten Grafikbetriebssystems sind damit nicht nachgewiesen. Der normale feste Anzeigemodus erhält die Proportionen. Der Grafikmodus kann eine neue Auflösung nur anfordern; der Gast muss sie unterstützen.

Die endgültige Image-Freigabe ergibt sich aus dem abgeschlossenen Workflow und dessen beigefügten Prüfberichten. Die A/B-Prüfung nutzt eine als Altstand markierte Kopie des aktuellen Builds und ersetzt keine nachgewiesene Migration von einem älteren veröffentlichten Titan-Image.

## Lokale Design-Nacharbeit nach alpha.3

Am 8. Oktober 2026 wurden 74 UI-Testdateien und die Syntax aller 47 Frontendmodule erfolgreich geprüft. Die Nacharbeit betrifft Frontend und Dokumentation; die Python-, Paket- und Image-Ergebnisse oben stammen aus den vorherigen Prüfungen und wurden für diese Gestaltung nicht neu erhoben.

Die isolierte Demo auf Port 5098 wurde bei 1280 × 720 geprüft: neuer Fjorddesktop, Widget-Galerie, kompakter App Store, Suche, App-Details und Rücknavigation, Scrollen bis zu den letzten Apps, Dateimanager mit Ansichtspopover und per Tastatur veränderter Seitenleiste, Einstellungsfilter und Suche, Wechsel zwischen Hell und Dunkel, Docker-Details sowie VM-Kacheln und Übersicht. Die Sitzung zeigte keine Browserwarnungen oder JavaScript-Fehler.

Bei 390 × 844 wurde ein tatsächlicher Scrollfehler gefunden und korrigiert: Eine ältere Mobilregel setzte den eingebetteten Store auf `overflow:visible`, während das übergeordnete Fenster Inhalte abschnitt. Der korrigierte Store verwendet `overflow:auto`; nach der Scrollaktion wurden 319 Pixel Scrollposition bei 674 Pixel sichtbarer Höhe und 993 Pixel Inhalt gemessen. Jellyfin und Syncthing am Listenende waren sichtbar. Dokumentbreite und sichtbare Breite betrugen jeweils 388 Pixel; es gab keinen horizontalen Dokumentüberlauf. Die temporäre Browsergröße wurde anschließend zurückgesetzt.

Die verdichtete Widget-Galerie zeigt bei 1280 × 720 alle sechs Karten samt Aktionen und Footer. Auch Dateimanager und Einstellungen wurden bei 390 × 844 ohne horizontalen Dokumentüberlauf geprüft (jeweils 388 Pixel sichtbare und gesamte Dokumentbreite); die Einstellungen scrollten bis zum letzten Eintrag „Protokoll“. Anschließend wurde die Browsergröße zurückgesetzt. Ein erneuter VM-Aufruf bestätigte die transparente Detailfläche im Dunkelmodus.

Aufnahmen: [Desktop](images/titan-desktop.jpg), [Widget-Galerie](images/titan-widgets.jpg), [App Store](images/titan-apps.jpg), [mobile Ansicht](images/titan-apps-mobile.jpg), [VM-Übersicht](images/titan-vm-overview.jpg). Die Demo führt keine echten Installationen aus. Zum Zeitpunkt dieser lokalen Designprüfung war die Nacharbeit noch nicht in einem neuen Image veröffentlicht.

## Carbon-Symbol und Schriftzug

Die lokale Gestaltung ergänzt ein eigenes kantiges Titan-Symbol und konstruierte TITAN-Buchstaben als SVG mit Carbonmuster und Lichtkanten. Der unverändert gespeicherte Imagegen-Entwurf besitzt einen transparenten Alphakanal; die SVG-Dateien wurden als XML geprüft und enthalten keine externen Ressourcen. Herkunft und finaler Prompt stehen unter [branding/README.md](branding/README.md).

Desktop und Anmeldung wurden bei 1280 × 720 im Browser geprüft, die Anmeldung zusätzlich bei 390 × 844. Es gab keinen horizontalen Dokumentüberlauf und keine Browserwarnungen oder JavaScript-Fehler. Die Login-Prüfung verwendet einen isolierten Datenbestand mit Demo-Provider, ohne Anmeldung oder echte NAS-Aktionen. Die Aufnahmen [Desktop](images/titan-desktop.jpg) und [Anmeldung](images/titan-login.jpg) wurden aktualisiert.

Die sechs gezielten UI-Suiten für Anmeldung, Desktop-Komposition, Verknüpfungsgesten, Widgets, Einstellungen und Themes bestanden nach der Integration. JavaScript-Syntax und `git diff --check` wurden zusätzlich geprüft. Zum Zeitpunkt dieser lokalen Logo-Prüfung war die Carbon-Gestaltung noch nicht in einem neuen Image veröffentlicht.

## Carbon-Oberfläche und NAS-Funktionen

Der lokale Stand erweitert die Gestaltung auf 18 eigene Werkzeug-/Containersymbole und gemeinsame Graphit-/Silber-/Platinfarben. Fremde App-Symbole werden über CSS in Graustufen dargestellt; ihre 74 SVG-Originaldateien blieben im SHA-256-Vergleich unverändert. Die neuen eigenen Symbole wurden als XML geprüft, auf aktive/externe Referenzen kontrolliert, mit librsvg/Cairo gerendert und visuell geprüft. Semantische Theme-Regressionen prüfen unter anderem Textkontrast sowie Fokus- und Statusdarstellung.

| Automatisierte Prüfung | Ergebnis |
| --- | --- |
| Vollständige Python-Suite | 1.914 Tests insgesamt, 1.902 bestanden, zwölf ausdrücklich übersprungen; Suite-Laufzeit 55,918 Sekunden |
| Übersprungene Python-Prüfungen | Eine Ext4-Werkzeugprüfung und elf Caddy-Integrationsprüfungen; damit für diesen Lauf nicht nachgewiesen |
| Vollständiger UI-Lauf | Alle 75 CJS-Testdateien erfolgreich |
| Finaler RAID-Backend-/HTTP-Pfad | 20 Tests zusätzlich separat erfolgreich; Teilmenge der vollständigen Python-Suite |
| Abschließende Quellenprüfung | 48 eigene JavaScript-Dateien und acht geänderte Python-Module syntaktisch korrekt; `git diff --check` ohne Befund |

Die lokalen Laufprotokolle heißen `/tmp/titan-carbon-python.log`, `/tmp/titan-carbon-python.json`, `/tmp/titan-carbon-cjs.log`, `/tmp/titan-carbon-cjs.json`, `/tmp/titan-carbon-raid-final.log` und `/tmp/titan-carbon-raid-final.json`. Sie sind temporäre lokale Prüfartefakte, keine Releaseberichte.

Die RAID-Prüfungen decken unterstützte Mirror-/RAIDZ1-/RAIDZ2-Verbünde, unzureichende Restredundanz, ausgeschlossene Topologien, ungeeignete Ersatzplatten, SMART-Fehler und unbekannte SMART-Zustände, Seriennummern/Hardwarepfade, veränderte Vorschauen, Poolidentität und serverseitige Rechte ab. Die UI-Suite prüft bestätigte Auswahl, gesperrte ungeeignete Platten, Ja-links-/Nein-rechts-Reihenfolge, nur einen Start trotz Doppelklick, Status nach Auftragsannahme sowie das Verwerfen verspäteter Antworten und das Beenden der Anzeigeabfragen beim Schließen. Der erfolgreiche Start bestätigt keinen abgeschlossenen Resilverlauf.

Die Backup-/Monitoringprüfungen umfassen Kalenderfristen in lokaler Zeitzone, Sommerzeitwechsel, Kulanz, Erstaktivierung, laufende Sicherungen, Planänderungen, Teil-/VM-Archive, verifizierten Erfolg und fehlgeschlagene Archivprüfung mit temporären Sicherungsdateien. SMART-Selbsttestergebnisse werden mit simulierten ATA-/NVMe-Antworten geprüft. Die Meldung einer überfälligen Sicherung nutzt den bestehenden optionalen SMTP-Kanal. Funktionsumfang und offene Lücken sind in [NAS-FUNCTION-AUDIT.md](NAS-FUNCTION-AUDIT.md) festgehalten; den Laufwerkstausch beschreibt [RAID-RECOVERY.md](RAID-RECOVERY.md).

Die abschließende Browserprüfung verwendete isolierte Datenbestände auf Port 5098 und vorübergehend 5099. Bei 1280 × 720 wurden Carbon-Desktop, Widget-Galerie, dunkle Einstellungen mit eigenen Symbolen, Docker samt sichtbarer Statusleiste, VM-Kacheln/-Details und die unauthentifizierte Anmeldung geprüft und aufgenommen. Bei 390 × 844 scrollte der helle App Store bis Jellyfin und Syncthing; Dokumentbreite und sichtbare Breite betrugen jeweils 388 Pixel, die äußere Seite 390 Pixel. Auch der RAID-Dialog scrollte bis zu den sichtbaren Aktionen „Zustand aktualisieren“ und „Schließen“. Eine zu breite globale Footer-Regel wurde dafür auf den äußeren Workspace-Footer begrenzt. Die temporäre Browsergröße wurde zurückgesetzt.

Der simulierte defekte Mirror erlaubte erst nach Auswahl und genauer Eingabe von Pool und Ersatzplatte den Start. Nach Auftragsannahme verschwand das Formular; der Dialog wechselte zum Wiederaufbau und zeigte nach automatischer Statusabfrage 16 Prozent statt anfangs null. Die [Bestätigung](images/titan-raid-repair.jpg) und der [Fortschritt](images/titan-raid-progress.jpg) stammen ausschließlich aus der RAM-Simulation. Der Dialog ließ sich schließen. Die geprüften Sitzungen zeigten keine Browserwarnungen oder JavaScript-Fehler. Temporäre Reparatur-/Login-Vorschauen wurden beendet; die Hauptvorschau bleibt erreichbar. Der abschließende vollständige UI-Lauf nach den letzten Quelländerungen bestand erneut mit 75 Dateien; Belege: `/tmp/titan-carbon-final-cjs.log`, `/tmp/titan-carbon-final-cjs.json` und `/tmp/titan-carbon-final-source-checks.json`.

Nach dem Konsolen-Farbabgleich bestanden erneut alle 75 UI-Dateien und die Syntaxprüfung der 48 Frontendmodule. Dauerhafte Fälle in `tests/console_recovery_ui.cjs` prüfen den einmaligen Konto-Lesezugriff trotz Wiederverbindung, Vorrang des Elternthemes bei eingebetteten Konsolen, HTTP-/JSON-Fehler sowie Abbruch und verspätete Antworten nach Verlassen der Seite. Neueste Belege: `/tmp/titan-carbon-final-cjs.json` und `/tmp/titan-carbon-final-js.json`. Im Browser wurden [dunkles](images/titan-vm-console-controls-dark.jpg) und [helles](images/titan-vm-console-controls-light.jpg) VM-Konsolenmenü sowie der helle Zwischenablagedialog geprüft. Dafür wurde bewusst keine VM ausgewählt; Gastanzeige, Skalierung und Gast-Zwischenablage wurden damit nicht geprüft. Das isolierte Demo-Terminal verband sich, zeigte neutrale Grundschrift und Schnellaktionen, wechselte mit dem Kontotheme und wurde wieder getrennt. Beide Sitzungen blieben ohne Browserwarnungen oder JavaScript-Fehler.

Für diese Weiterentwicklung wurden keine echten Laufwerke ersetzt und kein physischer Ausfall, Controller-, Hotplug- oder Neustartverhalten nachgewiesen. Die isolierte Demo simuliert Hostzustände und ersetzt diese Prüfungen nicht. Zum Zeitpunkt dieses lokalen Carbon-/NAS-Durchlaufs war noch kein neues Installationsimage oder Updatepaket gebaut oder veröffentlicht. Das oben dokumentierte frühere Paket und das veröffentlichte alpha.3-Image sind getrennte Stände.


## Abschließender Menü- und Release-Durchlauf · alpha.4

Der abschließende Quellenstand enthält Carbon-Gestaltung, NAS-Reparatur und
Monitoring sowie die [überarbeitete Menüführung](UI-NAVIGATION-AUDIT.md).
Der erneute vollständige lokale Python-Lauf bestand mit **1.916 Tests insgesamt,
1.904 bestanden und zwölf übersprungen** in 56,262 Sekunden. Die gleichen
lokalen Ext4-/Caddy-Werkzeugvoraussetzungen fehlen weiterhin; diese zwölf
Prüfungen werden damit lokal nicht als bestanden ausgegeben. Alle **75 CJS-
Testdateien** und die Syntaxprüfung der **48 Frontendmodule** bestanden nach
Integration der letzten Korrekturen. Temporäre Protokolle:
`/tmp/titan-navigation-python-final.log`,
`/tmp/titan-navigation-cjs-final.log` und
`/tmp/titan-navigation-cjs-final.json`.

Zwei zusätzliche Backend-Regressionen verhindern einen verfrühten
Backup-Erfolgsstempel bei fehlgeschlagener Aufbewahrungsbereinigung. Beide
schlagen gegen die vorherige Reihenfolge erwartungsgemäß fehl. Der RAID-Dialog
zeigt auch bei unterstützter Topologie einen Sperrgrund, etwa einen geänderten
Pool-GUID. Eine dauerhafte Workspace-Regression simuliert eine Animation,
deren Abschluss niemals eintritt: Dock und Speicherung ändern sich beim
Schließen sofort; ausblendende Fenster sind gesperrt, sofortiges Wiederöffnen
bleibt erhalten, Minimieren/Maximieren enden spätestens über eine kurze Frist.

Die Browserprüfung erfolgte erneut in der isolierten Demo bei 1280 × 720,
390 × 844 und 1280 × 360. Dateifilter und Aktionen scrollten im niedrigen
Fenster mit; Liste/Symbole waren mobil im Ansichtsmenü erreichbar. Die unterste
allgemeine Einstellungsaktion blieb erreichbar. App-Details öffneten oben,
Zurück stellte Position und Fokus wieder her. Docker-Tabs reagierten auf
Pfeiltasten mit einem einzelnen Tab-Fokus. Die fünf Speicher-Tabs standen in
einer Zeile. Gruppen, Sicherheit, Dienste, Sicherungen, Meldungen, Protokoll
und Ressourcen hatten keinen horizontalen Hauptinhaltsüberlauf. Schließen
entfernte die geprüften Fenster sofort aus dem Dock. Die geprüfte Sitzung war
frei von Browserwarnungen und JavaScript-Fehlern.

Die eigenen Aufnahmen von Hauptmenü, Dateien, Einstellungen und Docker wurden
aktualisiert. Die lokalen Vorprüfungen sind keine Image- oder Hardwareprüfung;
der anschließend abgeschlossene Release-Nachweis folgt separat.

## Veröffentlichter Image-Nachweis · alpha.4

[Titan 0.6.0-alpha.4](https://github.com/ra5on/Titan/releases/tag/v0.6.0-alpha.4)
wurde am **8. Oktober 2026 um 20:41 Uhr MESZ** veröffentlicht. Der
[Release-Workflow](https://github.com/ra5on/Titan/actions/runs/37819323545)
ist erfolgreich abgeschlossen. Das signierte Manifest bestätigt für Anwendung
und Image-Builder denselben Quellstand
`24c287a2572a1afddba973335a22d2836d35e9a5`.

| Prüfung dieses Quellstands | Ergebnis |
| --- | --- |
| [Normale CI](https://github.com/ra5on/Titan/actions/runs/37819322857) | 1.916 Python-Tests insgesamt, 1.890 bestanden, 26 wegen fehlender QEMU-Werkzeuge übersprungen; 75 UI-Testdateien sowie JavaScript- und Shellsyntax erfolgreich |
| Zusätzlicher Lauf im Image-Builder | 1.916 Python-Tests insgesamt, 1.905 bestanden, elf übersprungen; anschließend alle UI- und Syntaxprüfungen erfolgreich |
| [Native App-Prüfungen](https://github.com/ra5on/Titan/actions/runs/37819323333) | Immich mit vier Containern, AdGuard, Cloudflare-Tokenablauf, Tailscale-Userspace und eigene Compose-Fixture erfolgreich |
| [Debian-Paketprüfung](https://github.com/ra5on/Titan/actions/runs/37819322856) | Erfolgreich; eigener Paketnachweis, kein Ersatz für den Image-Boot |
| Image-Boot | Boot-, HTTPS-, UEFI-, VNC- und Laufzeit-Schritt erfolgreich |
| Laufzeitbericht | 15 Prüfungen bestanden; Systempartitionsvergrößerung ausdrücklich an die separate A/B-Prüfung delegiert |
| A/B-Bericht | Sieben Szenarien bestanden: Ausgangsstart, Datenpartitionsvergrößerung, Update-Vorbereitung, Update-Boot mit Datenerhalt, Slot-Standardwerte, manueller Rollback und Rückfall nach fehlerhaftem Start |

Die veröffentlichten Berichte
[runtime-test.json](https://github.com/ra5on/Titan/releases/download/v0.6.0-alpha.4/runtime-test.json)
und [ab-test.json](https://github.com/ra5on/Titan/releases/download/v0.6.0-alpha.4/ab-test.json)
bestätigen jeweils `ok: true` und ein unverändertes auszulieferndes Rohimage.
Der Laufzeitbericht umfasst unter anderem SMB-Rechte, die Trennung von
NAS-Daten und Betriebssystem, ZFS-Modul und Werkzeugbestand, Docker-Netze und
Containeraktionen sowie VM-Definition, Firmwarestart und RFB-Verbindung.
Die separate Compose-Fixture bestätigte auch Backup und Restore von
Anwendungsdaten. Die Cloudflare-Prüfung bestätigte die Deinstallation über
Docker und anschließende Neueinrichtung im Store bei erhaltenen Nutzdaten.
Cloudflare und Tailscale verwendeten absichtlich ungültige Testzugänge; eine
echte externe Tunnelverbindung und freigegebene Subnetzroute sind damit nicht
nachgewiesen.

| Veröffentlichte Datei | Größe | SHA-256 aus signierter Prüfsummenliste |
| --- | ---: | --- |
| `titan-0.6.0-alpha.4-amd64.img.xz` | 595.850.484 Byte | `669a461e1ad88a4be2005fa1b12e14aa19d4ed42205cd6dcd4f6e136685f1d16` |
| `titan-0.6.0-alpha.4-amd64.raucb` | 726.455.611 Byte | `9da2b3abc47dbb0c0392333955c596ab683a47dcbb22ea37a1551b45119573d7` |
| `debian-sources.tar.part-000` | 1.601.105.920 Byte | `7007b8e15808fd60653297fb96a7e1c3082454980082c48ff9e18265f4221572` |

Nach der Veröffentlichung wurden Manifest, Signaturen, Prüfsummenliste,
Prüfberichte, Paket-/Quelleninventar und Installationshinweise heruntergeladen.
Die Signaturen von Manifest und `SHA256SUMS` wurden mit dem öffentlichen
Schlüssel aus dem Repository geprüft. Die heruntergeladenen Dateien stimmen
mit ihren signierten Prüfsummen überein. Bei den drei großen Dateien stimmen
Dateigröße und von GitHub gemeldeter SHA-256-Digest mit der signierten Liste
überein; sie wurden für diese Nachkontrolle nicht nochmals vollständig lokal
heruntergeladen.

Die A/B-Ausgangsbasis ist laut Bericht `generated-current-build`: eine private,
als älter markierte Kopie des aktuellen Builds. Die Versionsmarkierung
`0.4.5-alpha.1` bezeichnet deshalb kein getestetes altes veröffentlichtes
Image. Eine echte versionsübergreifende Migration bleibt separat zu prüfen.
Auch physischer Plattentausch/RAID-Wiederaufbau, reale NAS-/Proxmox-Hardware,
Langzeitbetrieb und ein installiertes VM-Gastbetriebssystem einschließlich
Grafikauflösung und Zwischenablage sind durch diese Veröffentlichung nicht
nachgewiesen. Der Stand bleibt Alpha.
