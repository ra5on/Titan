# Titan entwickeln

```sh
python3 -m pip install PyYAML
python3 -m unittest discover -s tests
python3 -m titan.server --demo --host 127.0.0.1 --port 5089 --data /tmp/titan-demo
python3 scripts/build-debian-package.py
```

Die Demo simuliert Hostfunktionen. Das Debian-Paket ist ein Baustein des Images, kein Installer für bestehende NAS-Systeme. Aktive Workflows bauen ausschließlich Debian.

Quellstand des Imports: RaNAS `ff828eae7d4c50662e225dbf8f7ba0d9e5e47c59`. Die Versionsnummer 0.4.6 bezeichnet den übernommenen Anwendungsstand; Titan-Systemveröffentlichungen erhalten eigene Manifeste und Schlüssel.

Private Schlüssel gehören ausschließlich in `.secrets/` und GitHub Actions Secrets. Ins Repository kommen nur öffentliche Prüfschlüssel. `TITAN_SIGNING_KEY` signiert Veröffentlichungen.

## Oberfläche

Die Oberfläche liegt als React-Projekt in `ui/` (Vite, TypeScript, Tailwind). Der fertige Build steht in `titan/ui/` und wird mit eingecheckt, damit Paket- und Container-Build ohne Node auskommen.

```sh
cd ui
npm ci
npm run dev      # http://localhost:5173, leitet /api an die Demo auf Port 5089 weiter
npm run build    # schreibt titan/ui; das Ergebnis mit committen
npm run e2e      # Browsertests gegen die Demo (Linux; unter Windows ohne Dateitest)
```

Der Server liefert `/` ausschließlich aus `titan/ui/` aus. `/classic` leitet auf diesen Desktop um; alte Lesezeichen werden passenden Bereichen zugeordnet. Gemeinsame Dateien (App-Symbole, Hintergründe, VM-Konsole) kommen weiter aus `titan/web/`. Die Verwaltungsmodule werden über `ui/src/management` in denselben React-Desktop eingebunden. Die alten Shell-Dateien `app.js` und `workspace.js` werden dabei nicht geladen.

## Optionale Systemplugins

Systemreleases veröffentlichen die getestete Weboberfläche nur innerhalb des vollständigen Images und A/B-Bundles. Ältere Web-Updater können zusätzliche Anforderungen an den Host-Agent nicht erkennen; ein separater `web-container.tar.xz`-Download würde ihnen deshalb unpassende Oberflächen anbieten. Der unabhängige Web-Workflow verlangt vor Tag-Reservierung und Veröffentlichung ein ausdrückliches `__web_update_standalone__ = True` im eingefrorenen Anwendungsstand. Dieses Opt-in darf nur für Änderungen gesetzt werden, die mit allen unterstützten bestehenden Host-Agents funktionieren. Es bleibt für die neuen Plugin-APIs deaktiviert.

Der Appstore verwaltet die festen Plugin-Kennungen `cloudflare` und `nvidia` über `/api/plugins` und die Administratoraktion `plugin_action`. Neue Plugins erfordern geprüften Produktcode; es gibt keine API zum Ausführen beliebiger Installationsskripte. Änderungen laufen als exklusive Verwaltungsaufträge mit erneuter Rechteprüfung und einer Revision des zuvor angezeigten Stands.

Cloudflared wird erst bei Installation aus einem stabilen offiziellen GitHub-Release geladen und anhand der SHA-256-Summe geprüft. Binärdatei und Registry liegen im persistenten Datenbereich; der Token liegt separat mit Modus 0600 im Agent-Verzeichnis. Systemd erhält ihn über `LoadCredential`. Der Dienst verwendet einen dynamischen Benutzer und wird nach fehlgeschlagener Einrichtung auf den vorherigen Zustand zurückgesetzt. Nach einem Agent-Neustart bleibt ein bewusst gestoppter Dienst gestoppt. Die öffentliche Route muss im Cloudflare-Konto auf **HTTP `127.0.0.1:5102`** zeigen. Der Tunnel-Token erlaubt keine automatische Änderung dieser Kontoeinstellung.

NVIDIA-Pakete kommen bei ausdrücklicher Installation aus dem offiziellen, per APT-Signatur geprüften Archiv. Der feste Komponentenhelfer übernimmt Installation, Updateprüfung, Aktualisierung und Entfernung. Updates oder Entfernung werden bei laufenden GPU-Containern oder GPU-Prozessen abgewiesen. Eine NVIDIA-Paketänderung ist keine atomare Transaktion; bei Fehlern wird der Auftrag als unvollständig gemeldet. Nach einem A/B-Systemwechsel wird ein zuvor gewünschter Treiber für den neuen Kernel erneut eingerichtet. Beide Plugins tragen eine eigene Beta-Kennzeichnung; Titan-Releases bleiben Stable.

## App-Abnahme und eingefrorene Quellen

Der Workflow **Native app runtime checks** ruft die wiederverwendbare App-Abnahme auf. Für Titan ab 0.5.8 gibt es keinen Live-BigBear-Katalog als Voraussetzung. Getrennte Wegwerf-Runner prüfen den eigenen Cloudflare-Installer und eine lokal gebündelte Compose-Fixture mit zwei Containern. Ab dem eingefrorenen Anwendungsstand 0.5.9 kommen echte Immich-/AdGuard-Installationen sowie die Tailscale-Konfiguration mit absichtlich ungültigem Auth-Key hinzu. Ältere eingefrorene Stände führen diese neuen Prüfskripte nicht aus.

Der Cloudflare-Test verwendet das echte Cloudflared-Image mit einem absichtlich ungültigen, formal zulässigen Test-Token. Er prüft reale Docker-Schritte, fehlgeschlagene Verbindung, geschützte Token-/Wiederaufnahme-Dateien, einen Wiederholungsversuch ohne erneute Tokenübertragung und den weiterhin erreichbaren lokalen Titan-Zugang. Ein gestarteter Container darf keinen Tunnel-Erfolg vortäuschen. Echte Caddy-Validierung und ein gestarteter Tunnel-Proxy werden separat geprüft. Eine erfolgreiche Verbindung mit einem echten Cloudflare-Konto, DNS-Route und externer Anmeldung benötigt weiterhin eine praktische Abnahme.

Die eigene Fixture `tests/fixtures/runtime-stack-store.json` prüft Gruppierung, HTTP-Bereitschaft, Container- und Paketaktionen, parallelen Dateizugriff und Datenerhalt bei Deinstallation. Ihre Backup-Abnahme verwendet ein separates ext4-Loop-Gerät und die normalen HTTP-/Host-APIs: kalte Sicherung, ausdrücklich gewählte Nutzdaten, SQLite-Daten, relative interne Links, Unix-Rechte, private Einstellungen, gestoppte Wiederherstellung und anschließenden Neustart. Sie verändert keine öffentlichen Installationsfreigaben.

Der Boot-Test lädt diese Fixture ausschließlich vor dem Start in seine private QCOW2-Testschicht. Die Datei `/var/lib/titan-agent/ci-compose-fixtures.json` muss im ausgelieferten Rohimage fehlen. Der Agent akzeptiert sie nur als begrenzte normale Root-Datei mit Modus 0600, ohne Links und in einem geschützten Verzeichnis. Die öffentliche App-Liste enthält ausschließlich die eigenen Angebote des eingefrorenen Anwendungsstands: ab 0.5.9 Cloudflare Tunnel, Immich, AdGuard Home und Tailscale. Das Rohimage wird nur lesbar geöffnet und sein SHA256 nach dem Test erneut verglichen.

Systemupdates können einen älteren Anwendungsstand behalten. Die App-Abnahme liest deshalb die Versionsnummer aus genau diesem eingefrorenen Checkout, ohne ihn zu importieren. Für 0.5.6/0.5.7 bleiben die bisherigen, auf eine BigBear-Commit-ID festgelegten Legacy-Abnahmen aktiv; Parser- und Kompatibilitätstests erhalten die Verwaltung vorhandener Anwendungen. Native und Legacy-Abnahmen laufen nicht gleichzeitig für denselben Anwendungsstand.

Das aktuelle Build-Werkzeug wird getrennt unter `.titan-ci-builder` ausgecheckt. Host-Abhängigkeiten und neue CI-Helfer kommen aus diesem aktuellen Stand; die getesteten Produktmodule, Vorlagen und Produkt-Smokes stammen weiterhin aus dem eingefrorenen Anwendungsstand. So benötigt ein älterer Checkout keine nachträglich hinzugefügten Build-Helfer. Die APT-Spiegelanpassung gilt ausschließlich auf bestätigten GitHub-gehosteten Wegwerf-Runnern und verändert keine NAS-Paketquellen.

Lokale Tests, Demo und simulierte Docker-Transporte ersetzen diese Betriebsprüfung nicht. Die echten Smoke-Skripte verlangen ausdrücklich einen Wegwerf-Runner und dürfen nicht auf einem benutzten NAS ausgeführt werden.

## A/B-Testbasis bei Installationsimages

Ab 0.8.5 verwendet der Feature-Release-Workflow das veröffentlichte 0.8.1-Installationsimage mit festgelegter SHA-256-Prüfsumme. Das unveränderte Image ist die lesbare Basis einer privaten QCOW2-Testschicht. Der Bericht nennt `baseline_source: published-release` und `baseline_version: 0.8.1`. Neue Erstinstallationen werden weiterhin separat mit dem aktuellen Image geprüft.

Der A/B-Test ersetzt im alten Updater nur den Netzwerktransport durch ein privat signiertes Testangebot. Release-Auswahl, Signaturprüfung, Startzustand und Installationsprüfung laufen im tatsächlich installierten alten Produktcode. Der Test bereitet das Update vor, weist eine zweite Installation ohne Zustandsänderung ab, aktiviert die neue Version über die produktive Neustart-API und prüft Konten, ACLs und Daten sowie Rollback und Fehlstart-Rückkehr. Der Bericht ersetzt weiterhin keine Hardware-Abnahme für jedes NAS-Modell.

Die bis einschließlich 0.8.4 verwendete Testbasis `generated-current-build` war eine als älter markierte Kopie des damaligen neuen Builds. Diese älteren veröffentlichten Berichte bleiben unverändert; sie belegen keinen Übergang von einer tatsächlich älteren Veröffentlichung.
