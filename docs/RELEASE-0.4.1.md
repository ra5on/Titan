> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.1 · Alpha · uCore

**[Systemimage direkt herunterladen (.img.xz)](https://github.com/ra5on/Titan/releases/download/v0.4.1/titan-0.4.1-x86_64.img.xz)** · [Signaturen und Testergebnisse](https://github.com/ra5on/Titan/releases/tag/v0.4.1)

Der App Store enthält jetzt **42 kuratierte LinuxServer.io-Vorlagen**. Neu sind unter anderem Deluge, Emby, ChangeDetection, NZBGet, NZBHydra2, Ombi, Tautulli, SmokePing und pyLoad NG. Die Vorlagen berücksichtigen dokumentierte Ports, Nutzdaten und erforderliche Optionen.

„Details & Anmeldung“ erklärt für jede App den ersten Zugang. Dokumentierte öffentliche Standardzugänge können kopiert werden. Apps mit Einrichtungsassistent oder selbst gewählten Zugangsdaten erhalten passende Hinweise. Bei qBittorrent führt der Hinweis direkt zum App-Protokoll mit dem temporär generierten Passwort. Eigene Passwörter werden nicht aus gespeicherten Optionen in die Oberfläche zurückgeladen.

Neue Veröffentlichungen enthalten ausschließlich das vollständige uCore-HCI/Titan-IMG, verlustfrei als eine `.img.xz` komprimiert. Die signierten ISO-Dateien von v0.4.0 bleiben im Archiv. README und Release-Beschreibung bieten einen direkten IMG-Download.

HTTPS-Erststart und Laufzeitprüfungen bleiben vor der Veröffentlichung Pflicht. Der authentifizierte Gasttest prüft zusätzlich, dass der ausgelieferte App Store alle 42 Vorlagen mit korrekten öffentlichen Anmeldehinweisen enthält; sein Bericht veröffentlicht ausschließlich Anzahl und Ergebnis. Auch die Updateprüfung akzeptiert ausschließlich Manifeste mit ausdrücklich bestandenen Boot- und Laufzeittests; fehlende oder unbekannte Ergebnisse blockieren die Bereitstellung. Historische signierte IMG/ISO-Manifeste bleiben kompatibel.

**Die Beta ist das nächste Ziel; dieser Stand bleibt Alpha.** Automatische Tests bestätigen den Erststart und den geprüften App-/VM-Lebenszyklus. Echte NAS-/Proxmox-Tests für SMB, Speicher, installierte VM-Gastsysteme mit Browserkonsole, Backup/Wiederherstellung und Update/Rollback stehen als eigene Freigabekriterien in [Beta](https://github.com/ra5on/Titan/blob/main/docs/BETA.md).

[Installation](https://github.com/ra5on/Titan/blob/main/docs/INSTALL.md) · [Testplan](https://github.com/ra5on/Titan/blob/main/docs/TESTING.md)
