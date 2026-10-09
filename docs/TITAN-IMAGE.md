# Titan 0.7.0 · Debian 13 · A/B-System

[Titan 0.7.0 herunterladen](https://github.com/ra5on/Titan/releases/download/v0.7.0/titan-0.7.0-amd64.img.xz) · [Prüfsummen und Testberichte](https://github.com/ra5on/Titan/releases/tag/v0.7.0)

Titan 0.7.0 ist im Stable-Kanal veröffentlicht und in einer AMD64/UEFI-VM geprüft.
Teste deine konkrete Hardwarekonfiguration zunächst mit unabhängigen Sicherungen. Das Image ist für eine Neuinstallation bestimmt; es konvertiert
kein bestehendes anderes NAS-System und übernimmt dessen Daten nicht automatisch.

## Installation in Proxmox

- Die Datei `titan-<Version>-amd64.img.xz` herunterladen und mit `unxz` entpacken.
- Eine neue x86-64-VM mit UEFI/OVMF erstellen. Secure Boot zunächst deaktivieren.
- 8 GiB RAM und 2 CPUs zuweisen, CPU-Typ `host` verwenden. Für VMs
  innerhalb von Titan muss verschachtelte Virtualisierung verfügbar sein.
- Das entpackte IMG als VM-Festplatte importieren und als Startlaufwerk auswählen.
  Die virtuelle Platte ist 48 GiB groß. Sie vor dem Start auf mindestens 64 GiB
  beziehungsweise die gewünschte Kapazität vergrößern; Titan erweitert beim Start ausschließlich seine Datenpartition.
- Netzwerk per DHCP. Das veröffentlichte Image 0.7.0 ist unter `https://<NAS-IP>` erreichbar.
  Das lokale TLS-Zertifikat ist selbstsigniert. Den Administrator beim ersten
  Aufruf im eigenen Netz erstellen; es gibt kein vorgegebenes Kennwort.

Neuinstallationen verwenden `https://<NAS-IP>` auf Port 443 und leiten HTTP auf Port 80
automatisch dorthin weiter. Ein Update erhält einen bestehenden Webport.
**Einstellungen → Allgemein → Webzugriff** bietet HTTP oder HTTPS und eigene
Portnummern; HTTPS beinhaltet die HTTP-Weiterleitung mit Erhalt des aufgerufenen
Pfads. Die neue Adresse muss nach einer Änderung innerhalb von **120 Sekunden**
bestätigt werden, andernfalls wird die vorige Einstellung wiederhergestellt.

Die Systemplatte enthält EFI, Bootloader, zwei je 16 GiB große ext4-Systembereiche
und einen gemeinsamen ext4-Datenbereich. Auf der ersten Installation ist nur
System A eingerichtet. System B wird beim ersten vollständigen Update beschrieben.
Die gesamte verbleibende Kapazität steht dem Datenbereich zur Verfügung.

## Updates und Rollback

Unter **Einstellungen → Updates & Rollback** den Kanal Alpha, Beta oder Stable
wählen und nach Updates suchen. Titan 0.7.0 gehört zum Stable-Kanal. Ein separates
Webupdate ab Systembasis 0.6.1 aktualisiert nur die Oberfläche; [Details](WEB-CONTAINER.md).

Ein Update umfasst Titan, Debian, Kernel, Docker, VM-Komponenten und die übrigen
Pakete. Titan prüft das signierte Release und das RAUC-Updatepaket, schreibt den
inaktiven Systembereich und bietet danach einen Neustart an. Die Bestätigung
funktioniert per Schaltfläche; `NEUSTART` muss nicht abgetippt werden.
Automatische Suche bzw. Vorbereitung löst keinen automatischen Neustart aus.

Der gemeinsame EFI-/GRUB-Startbereich wird durch diese A/B-Systemupdates noch
nicht erneuert. Änderungen daran oder am Partitionslayout benötigen derzeit ein
neues Installationsimage. Normale kompatible Titan-/Debian-Versionen werden über
den Update-Kanal eingespielt.

Das Rollback-Dropdown zeigt verfügbare bestätigte lokale Systemstände. Direkt
nach der Installation gibt es noch keinen vorherigen Stand. Nach einem
bestätigten Update kann der vorherige Stand ausgewählt werden; auch der Rollback
wird erst beim ausdrücklich bestätigten Neustart aktiv.

Benutzer, Freigabenrechte, NAS-Konfiguration sowie App-, VM- und Nutzdaten bleiben
über den Versionswechsel hinweg erhalten. Unveränderte Systemkonfigurationen
folgen dem gewählten Debian-Systemstand; eigene Änderungen unter `/etc` bleiben
in einer gemeinsamen Overlay-Schicht erhalten. System-UIDs und -GIDs sind Teil
des signierten Kompatibilitätsvertrags und dürfen sich bei diesen Updates nicht ändern. Rollback ist keine Datenwiederherstellung
und ersetzt kein Backup. Die geteilten Daten müssen zum Schema 1 kompatibel bleiben;
inkompatible Systemupdates werden nicht angeboten. Eigene Änderungen außerhalb
der persistenten Verzeichnisse (beispielsweise unter `/usr` oder `/root`) gehören
zum jeweiligen Systemstand und werden nicht in den anderen Slot übernommen.
Nutzdaten deshalb in Freigaben oder eingebundenen Datenvolumes ablegen.

Der Bootloader versucht einen neuen Systemstand einmal. Erst eine erfolgreiche
Prüfung der NAS-Dienste bestätigt ihn dauerhaft. Bei einem fehlgeschlagenen Start
wählt der nächste Neustart den vorherigen gesunden Stand. Ein vollständig hängender
Gast benötigt einen Reset in Proxmox; diese Funktion ersetzt keinen Hardware-Watchdog.

## Prüfung und Grenzen

Ein Release wird nur veröffentlicht, wenn Boot, NAS-Laufzeittests und der echte
A/B-Wechsel samt Rückkehr auf den vorherigen Stand bestanden sind. Die Dateien
`runtime-test.json` und `ab-test.json` dokumentieren die tatsächlich ausgeführten
Prüfungen und gegebenenfalls übersprungene Prüfungen. Der A/B-Test verwendet einen
lokalen Test-Download statt einer bereits veröffentlichten GitHub-Version; die
RAUC-Signaturprüfung, Systeminstallation, Starts und Rollback-API laufen real.
Der Ausgangsstand ist eine private Kopie desselben Images mit einer älteren
signierten Versionskennung und einer abweichenden Test-Konfigurationsdatei.
Das prüft den vollständigen Partitionswechsel und die Persistenz, noch nicht
die Kompatibilität zwischen zwei unterschiedlich weiterentwickelten Releases.
Die vollständigen Nachweise für **0.7.0** stehen in [VERIFY-0.7.0.md](VERIFY-0.7.0.md).
Hardware-/USV-Tests, langfristiger Betrieb, echte installierte VM-Gastsysteme und
Wiederherstellung nach physischem Laufwerksverlust sind nicht abgenommen.
Secure Boot, BIOS-Start und ARM gehören nicht zum geprüften Zielumfang.
Das aktuelle Image enthält ZFS; Modul, Kernelzuordnung und Werkzeuge wurden im
laufenden System geprüft. Das ersetzt keine Prüfung echter Pools und Controller.

`SHA256SUMS` und `SHA256SUMS.sig` sind mit dem Titan-Release-Schlüssel signiert.
Den öffentlichen Schlüssel mit der separat vertrauten Datei
`packaging/release-public.pem` im Repository vergleichen; ein Schlüssel aus
derselben Downloadquelle allein ist kein unabhängiger Vertrauensnachweis.

## Historische Nachweise

Frühere tatsächlich ausgeführte Migrationen sind separat dokumentiert:
[0.4.6 → 0.4.7](https://github.com/ra5on/Titan/releases/download/v0.4.7-alpha.1/ab-test.json)
und [0.4.6 → 0.4.8](https://github.com/ra5on/Titan/releases/download/v0.4.8-alpha.1/ab-test.json).
Diese alten Ergebnisse werden nicht als Migrationsnachweis für 0.7.0 ausgegeben.
