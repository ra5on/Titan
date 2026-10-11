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

Der Server liefert `/` aus `titan/ui/` aus. Gemeinsame Dateien (App-Symbole, Hintergründe, VM-Konsole) und die bisherige Oberfläche unter `/classic` kommen weiter aus `titan/web/`.

## App-Abnahme und eingefrorene Quellen

Der Workflow **Native app runtime checks** ruft die wiederverwendbare App-Abnahme auf. Für Titan ab 0.5.8 gibt es keinen Live-BigBear-Katalog als Voraussetzung. Getrennte Wegwerf-Runner prüfen den eigenen Cloudflare-Installer und eine lokal gebündelte Compose-Fixture mit zwei Containern. Ab dem eingefrorenen Anwendungsstand 0.5.9 kommen echte Immich-/AdGuard-Installationen sowie die Tailscale-Konfiguration mit absichtlich ungültigem Auth-Key hinzu. Ältere eingefrorene Stände führen diese neuen Prüfskripte nicht aus.

Der Cloudflare-Test verwendet das echte Cloudflared-Image mit einem absichtlich ungültigen, formal zulässigen Test-Token. Er prüft reale Docker-Schritte, fehlgeschlagene Verbindung, geschützte Token-/Wiederaufnahme-Dateien, einen Wiederholungsversuch ohne erneute Tokenübertragung und den weiterhin erreichbaren lokalen Titan-Zugang. Ein gestarteter Container darf keinen Tunnel-Erfolg vortäuschen. Echte Caddy-Validierung und ein gestarteter Tunnel-Proxy werden separat geprüft. Eine erfolgreiche Verbindung mit einem echten Cloudflare-Konto, DNS-Route und externer Anmeldung benötigt weiterhin eine praktische Abnahme.

Die eigene Fixture `tests/fixtures/runtime-stack-store.json` prüft Gruppierung, HTTP-Bereitschaft, Container- und Paketaktionen, parallelen Dateizugriff und Datenerhalt bei Deinstallation. Ihre Backup-Abnahme verwendet ein separates ext4-Loop-Gerät und die normalen HTTP-/Host-APIs: kalte Sicherung, ausdrücklich gewählte Nutzdaten, SQLite-Daten, relative interne Links, Unix-Rechte, private Einstellungen, gestoppte Wiederherstellung und anschließenden Neustart. Sie verändert keine öffentlichen Installationsfreigaben.

Der Boot-Test lädt diese Fixture ausschließlich vor dem Start in seine private QCOW2-Testschicht. Die Datei `/var/lib/titan-agent/ci-compose-fixtures.json` muss im ausgelieferten Rohimage fehlen. Der Agent akzeptiert sie nur als begrenzte normale Root-Datei mit Modus 0600, ohne Links und in einem geschützten Verzeichnis. Die öffentliche App-Liste enthält ausschließlich die eigenen Angebote des eingefrorenen Anwendungsstands: ab 0.5.9 Cloudflare Tunnel, Immich, AdGuard Home und Tailscale. Das Rohimage wird nur lesbar geöffnet und sein SHA256 nach dem Test erneut verglichen.

Systemupdates können einen älteren Anwendungsstand behalten. Die App-Abnahme liest deshalb die Versionsnummer aus genau diesem eingefrorenen Checkout, ohne ihn zu importieren. Für 0.5.6/0.5.7 bleiben die bisherigen, auf eine BigBear-Commit-ID festgelegten Legacy-Abnahmen aktiv; Parser- und Kompatibilitätstests erhalten die Verwaltung vorhandener Anwendungen. Native und Legacy-Abnahmen laufen nicht gleichzeitig für denselben Anwendungsstand.

Das aktuelle Build-Werkzeug wird getrennt unter `.titan-ci-builder` ausgecheckt. Host-Abhängigkeiten und neue CI-Helfer kommen aus diesem aktuellen Stand; die getesteten Produktmodule, Vorlagen und Produkt-Smokes stammen weiterhin aus dem eingefrorenen Anwendungsstand. So benötigt ein älterer Checkout keine nachträglich hinzugefügten Build-Helfer. Die APT-Spiegelanpassung gilt ausschließlich auf bestätigten GitHub-gehosteten Wegwerf-Runnern und verändert keine NAS-Paketquellen.

Lokale Tests, Demo und simulierte Docker-Transporte ersetzen diese Betriebsprüfung nicht. Die echten Smoke-Skripte verlangen ausdrücklich einen Wegwerf-Runner und dürfen nicht auf einem benutzten NAS ausgeführt werden.

## A/B-Testbasis bei Installationsimages

Der Feature-Release-Workflow verwendet derzeit `initial_image: true`. Für diese Abnahme erzeugt er eine private, als älterer Stand markierte Kopie des aktuellen Builds. Der Bericht nennt sie `baseline_source: generated-current-build`; die Versionsmarkierung `0.4.5-alpha.1` bezeichnet hierbei keine heruntergeladene Veröffentlichung dieses alten Quellcodes.

Damit werden das signierte Schreiben in den inaktiven Slot, Neustart, Konten-/Rechte-/Datenerhalt, manueller Rollback und die Rückkehr nach einem fehlgeschlagenen Kandidaten geprüft. Die Abnahme beweist keine vollständige Upgrade-Kompatibilität mit einer tatsächlich älteren veröffentlichten Titan-Version und ihren vorhandenen Zuständen. Dafür ist eine zusätzliche Prüfung mit deren verifiziertem Image beziehungsweise Systembundle nötig. Veröffentlichte Berichte und Manifeste müssen diese Testbasis eindeutig erkennen lassen.
