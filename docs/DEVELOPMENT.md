# Titan entwickeln

```sh
python3 -m pip install PyYAML
python3 -m unittest discover -s tests
python3 -m titan.server --demo --host 127.0.0.1 --port 5089
python3 scripts/build-debian-package.py
```

Die Demo simuliert Hostfunktionen. Das Debian-Paket ist ein Baustein des Images, kein Installer für bestehende NAS-Systeme. Aktive Workflows bauen ausschließlich Debian.

Quellstand des Imports: RaNAS `ff828eae7d4c50662e225dbf8f7ba0d9e5e47c59`. Die Versionsnummer 0.4.6 bezeichnet den übernommenen Anwendungsstand; Titan-Systemveröffentlichungen erhalten eigene Manifeste und Schlüssel.

Private Schlüssel gehören ausschließlich in `.secrets/` und GitHub Actions Secrets. Ins Repository kommen nur öffentliche Prüfschlüssel. `TITAN_SIGNING_KEY` signiert Veröffentlichungen.

BigBear-Parser und Stack-Regressionsfälle: `tests/test_bigbear_stacks.py`. Der Workflow `BigBear stack runtime checks` installiert AdGuard, Nextcloud und Immich auf getrennten Wegwerf-Runnern und prüft echte HTTP-, Datei- und Containeraktionen. Lokale Demo-Tests ersetzen diese Betriebsprüfung nicht.
