# Titan 0.8.5 · Stable

Diese Version stabilisiert die Vorbereitung und Aktivierung von Systemupdates.

- Neustarts aus dem Systemmenü und den Systemeinstellungen bestätigen den angezeigten nächsten Systemstand. Vorbereitete Updates und Rollbacks verwenden dadurch die richtige Versionskennung. Ändert sich die Auswahl nach Öffnen des Dialogs, bleibt eine erneute Bestätigung erforderlich.
- Bereits vorbereitete Updates, geplante Neustarts und eine unbestätigte Startprüfung erhalten unterschiedliche, verständliche Meldungen. Ein altes Updateangebot darf die aktuelle Sperre nicht übergehen.
- Nach einem Installationsversuch werden gespeicherte Angebote verworfen. Der aktuelle Systemstatus entscheidet, ob ein Neustart oder eine neue Prüfung nötig ist.
- Die Release-Abnahme startet mit dem unveränderten, geprüften 0.8.1-Installationsimage. Sie prüft signierte Release-Erkennung, Installation, Ablehnung einer erneuten Installation, Aktivierung, Datenerhalt, Rollback und Rückkehr nach einem absichtlich beschädigten Testslot. Die Prüfung der neuen Erstinstallation läuft separat.

## Installation

Das IMG ist für eine neue AMD64/UEFI-Installation vorgesehen. Eine neue virtuelle Maschine mit eigener Systemplatte ist der einfachste Weg, ein bestehendes Testsystem zu ersetzen, ohne dessen Platte zu überschreiben. Das signierte RAUC-Bundle dient bestehenden A/B-Installationen.

Ein schon vorbereiteter Stand muss auf dem bestehenden NAS zunächst aktiviert werden. Eine neue Veröffentlichung repariert den bereits laufenden alten Updater nicht rückwirkend. Laufende virtuelle Maschinen innerhalb von Titan müssen vor dem NAS-Neustart geordnet heruntergefahren werden; Updates erzwingen kein Ausschalten und keinen Neustart.

Cloudflare- und NVIDIA-Plugins sowie die übrigen bisher als Beta bezeichneten Einzelfunktionen behalten ihre Kennzeichnung. Cloudflared und NVIDIA-Treiber werden weiterhin erst bei Bedarf heruntergeladen.
