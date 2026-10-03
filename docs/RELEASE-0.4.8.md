# Titan 0.4.8-alpha.1 · Systemupdate

Signiertes Debian-A/B-Systemupdate für bestehende Titan-Installationen. Das Installationsimage 0.4.6-alpha.1 bleibt gültig; kein erneuter Import erforderlich.

## Installation

In Titan den Kanal **Alpha** speichern, nach Updates suchen und **0.4.8-alpha.1** vorbereiten. In älteren Oberflächen liegt die Kanalwahl unter **Einstellungen → Updates & Kanäle**. Nach erfolgreicher Vorbereitung den Neustart bestätigen. Die Oberfläche zeigt anschließend **0.4.8**.

## Änderungen

- Kanalwahl, automatische Prüfung und Rollback auf einer gemeinsamen Update-Seite.
- Kompakte Aktivitätsübersicht und Status direkt im jeweiligen Bereich; wartende Aktionen werden korrekt von laufenden unterschieden.
- Systemupdates melden Angebotsprüfung, Sicherung, Download, Signaturprüfung, Schreiben und Neustartbereitschaft. Prozentwerte werden nur aus gemessenen Downloadbytes berechnet. Diese neue Fortschrittsanzeige gilt für Updates, die nach Installation dieser Version gestartet werden.
- RAM-Anzeige inklusive Cache mit getrennten Werten für geschätzten Bedarf, verfügbaren und freien Speicher, Cache und Kernel-Puffer. Proxmox kann eine andere Messgröße anzeigen; ein identischer Wert wird nicht versprochen.
- Abgelöste Plattform, Build-Rezepte und veraltete Dokumentation entfernt. Debian und signierte RAUC-A/B-Updates sind der aktive Systempfad.
- Mobile Aktivitätsdarstellung verbessert; Prüfergebnisse aktualisieren sich ohne ungespeicherte Einstellungen zu überschreiben.

## Prüfung und Grenzen

Veröffentlichung nur nach erfolgreichen Regressionstests, tatsächlichem QEMU-Start, NAS-Laufzeittests sowie Update vom veröffentlichten 0.4.6-alpha.1-Image auf diesen Kandidaten, Rollback und Fehler-Rückfall. Die Berichte `runtime-test.json` und `ab-test.json` dokumentieren den getesteten Stand. Der Wechsel von einer bereits installierten 0.4.7 wird nicht als separat getesteter VM-Zyklus behauptet.

Rollback wechselt das Betriebssystem, nicht Nutzdaten oder Datenbanken. Unabhängige Sicherungen bleiben erforderlich. Titan bleibt Alpha; Hardwaretests mit individuellen USB-Geräten, GPUs und zusätzlichen AppStores sind nicht vollständig abgeschlossen.

Für Neuinstallationen: [0.4.6-IMG herunterladen](https://github.com/ra5on/Titan/releases/download/v0.4.6-alpha.1/titan-0.4.6-alpha.1-amd64.img.xz), OVMF/UEFI verwenden, Secure Boot deaktivieren und danach den Alpha-Kanal nutzen. Dieses Release liefert ein Systemupdate ohne neuen IMG-Download.
