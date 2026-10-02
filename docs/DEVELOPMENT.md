# Titan entwickeln

```sh
python3 -m unittest discover -s tests
python3 -m titan.server --demo --host 127.0.0.1 --port 5089
python3 scripts/build-debian-package.py
```

Die Demo simuliert Hostfunktionen. Das Debian-Paket ist ein Baustein des Images, kein Installer für bestehende NAS-Systeme. Aktive Workflows bauen ausschließlich Debian. Unter `legacy/ucore` liegen inaktive Rezepte des Vorgängers für Regressionstests, keine Titan-Veröffentlichung.

Quellstand des Imports: RaNAS `ff828eae7d4c50662e225dbf8f7ba0d9e5e47c59`. Die Versionsnummer 0.4.6 bezeichnet den übernommenen Anwendungsstand; Titan-Systemveröffentlichungen erhalten eigene Manifeste und Schlüssel.

Private Schlüssel gehören ausschließlich in `.secrets/` und GitHub Actions Secrets. Ins Repository kommen nur öffentliche Prüfschlüssel. `TITAN_SIGNING_KEY` signiert Veröffentlichungen.
