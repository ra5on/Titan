> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.0 · Alpha · uCore

Die neue Verwaltung ordnet Werkzeuge nach Aufgaben und bietet eine Suche. Die persönliche Übersicht bleibt anpassbar; Desktop und Mobilgeräte erhalten dieselben Funktionen mit passenden Navigations- und Dialogansichten. Speicherziele lassen sich als benannte Laufwerke oder Freigaben auswählen, Unterordner über einen Ordnerbrowser. Dienste erscheinen als kompakte Liste mit Status, Ressourcen, Protokollen und Steuerung im Detaildialog.

Der App Store wächst von 13 auf **26 kuratierte LinuxServer.io-Vorlagen**. Suche, Kategorien und Installationsstatus erleichtern die Auswahl. Unter anderem kommen qBittorrent, Transmission, Code-Server, LibreSpeed, Grocy, PairDrop und Duplicati hinzu. Die Installationsdialoge berücksichtigen zusätzliche TCP-/UDP-Ports und erforderliche Zugangsdaten. Eine gepflegte Vorlage ersetzt nicht den Einrichtungsassistenten oder einen individuellen Funktionstest der jeweiligen App.

Der Start des HTTPS-Proxys erhält eine eng begrenzte SELinux-Erlaubnis für Caddys Programmeinstieg. SELinux bleibt aktiv. Docker nutzt die passenden Einstellungen der uCore-Dienstdatei ohne doppelte Daemon-Optionen. Private App-Konfigurationen erhalten vor dem Containerstart die zu ihrem Container gehörende SELinux-Kennzeichnung. Die Bind-Mounts bleiben so konfiguriert, dass fehlende Hostverzeichnisse nicht automatisch angelegt werden. Fehlgeschlagene Dienstaufträge werden als Fehler ausgewiesen.

Titan erhält neben dem vollständigen IMG eine bootbare Offline-Installations-ISO. Beide enthalten dasselbe uCore-HCI/Titan-System samt Docker, Samba, QEMU/libvirt, Browserkonsole und Dateisystemwerkzeugen. Die ISO verlangt eine ausdrückliche Datenträgerauswahl im Installer. Das System muss während der Installation nicht aus dem Internet geladen werden.

Die Downloads sind verlustfrei komprimiert. Falls die ISO GitHubs Dateigrößengrenze überschreitet, werden nummerierte Stücke angeboten. Alle ISO-Dateien sowie `restore-iso.py`, `manifest.json`, `manifest.json.sig` und den bereits vertrauten `release-public.pem` in dasselbe Verzeichnis herunterladen. Mit Python 3 und OpenSSL erzeugt **`python3 restore-iso.py`** eine geprüfte echte `.iso` für Proxmox oder ein Installations-USB-Medium. Manifest und Prüfsummen binden IMG, alle ISO-Stücke und die vollständige ISO an den Release-Schlüssel.

Der Release-Workflow prüft IMG-Boot, HTTPS und Ersteinrichtung sowie Metriken, Docker und libvirt. Die Test-App muss ihre Webseite ausliefern; bei verfügbarem KVM werden zusätzlich Konsolendateien und eine authentifizierte VNC-Verbindung geprüft. Zusätzlich startet er die unveränderte ISO unter BIOS/UEFI ohne automatische Disk-Schreibzugriffe und installiert ausschließlich eine weitere CI-Kopie auf eine neu angelegte virtuelle Disk. Das daraus installierte Titan muss erneut HTTPS-/Setup- und Laufzeitprüfungen bestehen. Alle Outcomes werden getrennt signiert. Ein fehlender kritischer Nachweis blockiert die öffentliche Veröffentlichung, auch für Alpha; Testmedien und Diagnosen bleiben als Actions-Artefakte erhalten.

Der Stand bleibt **Alpha**. Ein bestandener CI-Lauf ersetzt die separaten NAS-/Proxmox-Hardwaretests, einen echten Gast-OS-/Konsolentest sowie Update/Rollback und SMB-/ZFS-Prüfungen nicht. Eine Beta-Freigabe erfolgt erst nach den dokumentierten Betriebsnachweisen.

[Installation](https://github.com/ra5on/Titan/blob/main/docs/INSTALL.md) · [ISO-Build](https://github.com/ra5on/Titan/blob/main/docs/ISO-BUILD.md) · [Testplan](https://github.com/ra5on/Titan/blob/main/docs/TESTING.md)
