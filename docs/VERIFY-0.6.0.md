# Lokale Prüfung für Titan 0.6.0

Stand: 8. Oktober 2026. Diese Ergebnisse betreffen den Quellstand und die isolierte lokale Vorschau. Die Image-Prüfungen laufen zusätzlich im GitHub-Release-Workflow.

| Prüfung | Ergebnis |
| --- | --- |
| Python-Suite | 1.855 Tests, erfolgreich, 12 ausdrücklich übersprungen |
| UI-Testdateien | 73 Dateien erfolgreich; einschließlich neuer Desktop-, Store-, Dateiansicht-, Settings- und Konsolenregressionen |
| JavaScript und Shellsyntax | 47 Frontendmodule und vorhandene Shellskripte erfolgreich geprüft |
| Debian-Paket | `titan-debian-preview_0.6.0+debian1_amd64.deb` erfolgreich gebaut |
| Patchformat | `git diff --check` ohne Fehler |

Zusätzliche Quellenprüfung: 54 gezielte Tests für versionsgenaue Sammlung, historische signierte APT-Archive, Tarinhalt, fehlende Teile, Paketzuordnung und Veröffentlichungsgrenzen erfolgreich. Zwei echte Quelldownloads wurden geprüft: `hello=2.10-5` aus aktuellen signierten Trixie-Indizes und die nicht mehr aktuelle eingebettete Quelle `golang-fsnotify=1.8.0-1` aus dem authentifizierten Snapshot `20241110T083149Z` (`sid/main`). DSC-Identität, Dateigrößen und SHA-256 stimmen. Ein daraus erzeugtes GNU-Tar wurde über mehrere Teile gestreamt und vollständig verifiziert. Das ist ergänzende Werkzeugprüfung; die vollständige Sammlung aller Image-Pakete muss zusätzlich im Release-Build bestehen.

Im Browser geprüft: frischer Desktop mit Begrüßung, Widgetreihe und Dock; Hinzufügen einer Uhr; Hell-/Dunkel-Wechsel; Einstellungsfilter, Suche und Unterseiten; Seitenleistenänderung mit Maus und Tastatur; Dateisymbole und Ansichtspopover; AppStore-Suche, Detail-/Rücknavigation und Scrollen; Docker-Details; VM-Kacheln und Sicherungsansicht; Terminal-Verbindung, Rechtsklick-Menü und bestätigtes Schließen. Die AppStore-Ansicht wurde zusätzlich bei 390 Pixeln Breite geprüft und hatte keinen horizontalen Dokumentüberlauf. Die geprüften Sitzungen zeigten keine Browserwarnungen oder JavaScript-Fehler.

README-Abbildungen wurden aus dieser Titan-Demo aufgenommen. Beispieldaten sind erkennbar. Die neuen Landschaften, Toolbar-Grafiken und Store-Illustrationen wurden eigenständig erstellt; UmbrelOS/TitanOS-Code und Assets wurden für diesen Umbau nicht kopiert. Ein Hashvergleich der Webdateien fand keine vollständig identischen Webdateien im lokalen TitanOS-Bestand. Das ist ein begrenzter technischer Herkunftscheck und keine vollständige Lizenz- oder Gestaltungsrechtsprüfung; siehe [LICENSING.md](LICENSING.md).

Die Demo bestätigt keine Installation auf einem echten NAS und keine Verbindung über ein echtes Cloudflare- oder Tailscale-Konto. Die Konsole wurde zuvor mit einer isolierten QEMU-Firmware geprüft; dynamische Auflösung und Gast-Zwischenablage eines konkreten Grafikbetriebssystems sind damit nicht nachgewiesen. Der normale feste Anzeigemodus erhält die Proportionen. Der Grafikmodus kann eine neue Auflösung nur anfordern; der Gast muss sie unterstützen.

Die endgültige Image-Freigabe ergibt sich aus dem abgeschlossenen Workflow und dessen beigefügten Prüfberichten. Die A/B-Prüfung nutzt eine als Altstand markierte Kopie des aktuellen Builds und ersetzt keine nachgewiesene Migration von einem älteren veröffentlichten Titan-Image.
