# Historisches v0.4.0-ISO-Archiv

**Diese Seite beschreibt ausschließlich den früheren ISO-Weg von v0.4.0. Reguläre Titan-Releases liefern signierte OCI-Systemupdates. Ein neuer Installationsdownload wird bei Bedarf ausdrücklich als vollständige `.img.xz`-Datei veröffentlicht; neue ISO-Builds entfallen.** Für die aktuelle Installation und Proxmox-Tests [Installation](INSTALL.md) und [Testplan](TESTING.md) verwenden.

Das [öffentliche Release v0.4.0](https://github.com/ra5on/Titan/releases/tag/v0.4.0) enthält bereits geprüfte und signierte IMG-/ISO-Dateien. Seine ISO-Stücke, Helfer, Manifeste, Prüfsummen und Signaturen bleiben unverändert. Sie werden nicht nachträglich zu einem IMG-only-Manifest umgeschrieben. Für neue Releases gibt es weder ISO-Aufteilung noch einen Zusammenbau-Schritt.

Der damalige Release-Workflow erzeugte beide Medien aus **demselben signierten Titan-OCI-Digest**. Der zusätzliche Download enthält eine bootbare `.iso`, mit XZ komprimiert und wegen GitHubs Dateigrößengrenze in Stücke aufgeteilt. Nur beim historischen Archiv müssen alle Stücke samt `restore-iso.py`, `manifest.json`, `manifest.json.sig` und dem bereits vertrauten `release-public.pem` zusammen vorliegen. Python 3 und OpenSSL werden benötigt; `python3 restore-iso.py` prüft die Signatur und rekonstruiert die vollständige ISO. Einzelne Stücke sind keine bootbaren Installationsmedien.

## Historische Build- und Testverfahren

Die folgenden Abschnitte dokumentieren die vorhandenen Archivwerkzeuge und die für v0.4.0 erfolgten Nachweise. Sie sind keine Schritte der laufenden Update-Pipeline.

## Festgelegter Builder und Installer

Der Builder ist auf `quay.io/centos-bootc/bootc-image-builder@sha256:afeffdb5a7ab6bb9d0593b5765412c4d821a9492dbaf26bb5a494e27181d2019` festgelegt. Seine OCI-Metadaten nennen den Quellstand `a686afed6dde14fa5444a3d3be0f269acc783470`; darin wird `osbuild/images v0.251.0` verwendet. Dieser Stand unterstützt `anaconda-iso` als RPM-basierten Installer. Er braucht Anaconda ausschließlich auf dem Installationsmedium; das installierte System bleibt das vollständige uCore-HCI/Titan-Payload.

Die [gepinnten Builder-Quellen](https://github.com/osbuild/bootc-image-builder/blob/a686afed6dde14fa5444a3d3be0f269acc783470/bib/cmd/bootc-image-builder/legacy_iso.go) erzeugen ein Anaconda-Medium. Die [gepinnten Payload-Stufen](https://github.com/osbuild/images/blob/v0.251.0/pkg/manifest/anaconda_installer_iso_tree.go) kopieren den OCI-Container auf die ISO, installieren ihn mit `ostreecontainer` aus `/run/install/repo/container` und setzen mit `bootc switch --mutate-in-place` die ursprüngliche Registry-Referenz für spätere Updates. Die Installation benötigt keinen Netzwerkabruf dieses Systems.

Der historische Builder enthält keine eigene Fedora-44-Installerdefinition und verwendet seine Fedora-42-Paketliste gegen die Paketquellen des Fedora-44-Zielcontainers. Die relevanten Anaconda-/TUI-Pakete sind in [Fedora 44](https://packages.fedoraproject.org/pkgs/anaconda/anaconda-tui/fedora-44.html) vorhanden. Maßgeblich bleibt der tatsächliche ISO-Build mit anschließendem Offline-Installationstest; ein Quellenvergleich allein bestätigt keine uCore-Installation.

## Interaktive Datenträgerauswahl

`image/installer.toml` ersetzt den automatisch installierenden Standard-Kickstart vollständig. Es enthält Sprache, Tastatur, Netzwerk und gesperrtes Root-Login, jedoch keine automatische Plattenauswahl, Löschung oder Partitionierung. Anaconda muss diese Entscheidungen vom Benutzer erhalten. Der Builder ergänzt lediglich die eingebettete OCI-Quelle und den passenden Update-Digest.

`scripts/prepare-iso.py` prüft die beiden erzeugten Kickstart-Dateien und den eingebetteten OCI-Manifest-Digest. Der historische Builder exportiert Container-Layer aus dem lokalen Storage und verändert dabei deren Manifest. Deshalb ersetzte der v0.4.0-Release-Workflow dieses Verzeichnis vollständig durch die zuvor mit Signatur-/Registry-Policy und erhaltenen Digests geprüften OCI-Dateien. Jede Config und jeder Layer werden nochmals auf Größe und SHA-256 geprüft; der eingebettete Manifest-Digest muss weiterhin exakt dem veröffentlichten Systemimage entsprechen. Xorriso erhält die BIOS-/UEFI-Bootausrüstung, und der Anaconda-Medienprüfsummenwert wird nach jeder Änderung erneuert und geprüft. Eine ISO mit automatisch löschenden oder partitionierenden Kommandos wird verworfen. Der Installationsstart bestätigt auf der seriellen Konsole die lokale Offline-Payload; das ist ein Startnachweis und noch kein Nachweis abgeschlossener Installation.

## Getrennte CI-Nachweise

`scripts/smoke-iso.sh` läuft ausschließlich auf einem ausdrücklich bestätigten, entbehrlichen Actions-Runner. Es bootet zuerst die **unveränderte öffentliche ISO** unter UEFI und BIOS. Neue sparse virtuelle Disks müssen ohne Benutzereingaben unbeschrieben bleiben. Der Test automatisiert keine menschlichen Auswahl- oder Bestätigungsschritte.

Danach erzeugt `prepare-iso.py` eine weitere **nur intern verwendete Testkopie**. Nur diese Kopie enthält einen nicht interaktiven Kickstart, eingeschränkt auf `vda`, mit EFI, separatem Ext4-`/boot` und XFS-Root. QEMU erhält ausschließlich eine neu angelegte virtuelle Datei; keine reale Disk und kein Hostverzeichnis werden durchgereicht. Die QEMU-Netzwerkoption `restrict=on` erlaubt DHCP im isolierten Gastnetz und sperrt externe Verbindungen. Dadurch wird die Offline-Payload während der tatsächlichen Installation geprüft.

Nach abgeschlossener Installation wird das Installationsmedium entfernt. Das installierte Titan erhält einen separaten Overlay-Boot mit normalem Testnetz und durchläuft denselben HTTPS-/Setup-/Laufzeittest wie das IMG. Die Quelle bleibt unverändert. Ein fehlendes Nested-KVM wird im Runtime-Bericht ausdrücklich als übersprungen dokumentiert.

Im signierten Manifest bleiben die bisherigen IMG-Felder kompatibel. `iso.boot_test`, `iso.install_test`, `iso.system_boot_test` und `iso.runtime_test` halten die zusätzlichen Outcomes getrennt fest. Die ISO-Hashes umfassen jeden Downloadteil, den gesamten komprimierten Stream und die entpackte bootbare ISO. `SHA256SUMS` wird ebenfalls separat signiert.

Für das kombinierte v0.4.0-Release mussten alle sechs kritischen Outcomes `passed` sein, einschließlich der ISO-Prüfungen. Die Veröffentlichungsprüfung behält diese Regel für kombinierte Manifeste bei. Neue Update-Releases sowie ausdrücklich gewählte Installations-IMG-Releases verlangen stattdessen explizit bestandene Start- und Laufzeitprüfungen derselben signierten OCI-Version auf einer internen Testdisk. Fehlerdiagnosen werden als Actions-Artefakte erhalten; bestätigte Dienstfehler werden nicht als nutzbares Release veröffentlicht. Ein manueller Proxmox-Test erfolgt getrennt auf einer entbehrlichen VM mit dem geprüften Installationsimage und dem signierten Update-Kandidaten. Physische NAS-Hardware, SMB-/ZFS-Aktionen und die menschliche Laufwerksauswahl benötigen weiterhin den [Hardwaretest](TESTING.md).
