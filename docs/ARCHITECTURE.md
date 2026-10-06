# Titan auf Debian 13

Titan besteht aus einer Python-Webanwendung, einem privilegierten Verwaltungsagenten und einer statischen Weboberfläche. Caddy stellt HTTPS auf Port 5000 bereit. Docker, Samba, QEMU/libvirt, noVNC und Dateisystemwerkzeuge gehören zum vollständigen Systemimage.

## System und Daten

Das UEFI-Image enthält eine EFI-Partition, einen gemeinsamen Bootbereich, zwei ext4-Systemslots mit je 16 GiB und einen persistenten ext4-Datenbereich. Nur der inaktive Systemslot wird beim Update beschrieben. GRUB verwaltet Startversuche und Rückfall; RAUC prüft signierte Bundles. Eine Gesundheitsprüfung bestätigt den neuen Systemstand erst nach dem Start.

NAS-Konfiguration, Benutzer, Freigaben sowie Docker- und VM-Daten liegen persistent. `/etc` verwendet eine Overlay-Ebene. Signierte Updates müssen den Systemkontenvertrag und das Datenschema erhalten. Ein Rollback setzt das Betriebssystem zurück, nicht Nutzdaten oder Datenbanken. Änderungen des gemeinsamen Bootlayouts brauchen ein neues Installationsimage.

Der gemeinsame Speicher-Katalog ordnet internen DATA-Bereich, Ext4-/XFS-Volumes
und ZFS-Pools über feste Kennungen zu. Namen, Kapazitäten und Verwendungszwecke
sind in allen Dialogen identisch. Mount, UUID beziehungsweise Pool-GUID und
Verzeichniseigentümer werden vor Änderungen geprüft. Neue Daten erhalten eigene
App-/Freigabe-/VM-/Backup-Namensräume; ein Standardwechsel verschiebt keine
bestehenden Daten. Ein fehlendes oder volles Ziel führt zu einem Fehler.

Die Datei-API beschränkt auch Webadministratoren auf verifizierte NAS-Daten und
persönliche Datenordner. OS-Verzeichnisse sind weder Startorte noch erlaubte
Ziele; Verknüpfungen können diese Grenze nicht umgehen. Das Datenterminal
läuft ohne Rootrechte. Das ist eine Grenze der Webverwaltung und keine Zusage,
dass ein gesonderter Unix-Rootzugang das System nicht verändern kann.

## Verwaltung

Die Webanwendung prüft Sitzung, Rolle, CSRF und erlaubte Aktionen. Der Agent bietet fest definierte Operationen. Längere Änderungen laufen als Hintergrundaktionen weiter, auch wenn der Browser geschlossen wird. Aktionen werden serialisiert; Kontosperren besitzen einen getrennten Ausführungspfad.

Update-Fortschritt wird vom Agenten atomar unter `/run/titan` gespeichert und über eine schreibgeschützte Administrator-API gelesen. Nur Downloadwerte besitzen eine gemessene Prozentanzeige. Nach einem Agentenneustart werden zurückgebliebene laufende Vorgänge als unterbrochen angezeigt.

## Veröffentlichung

Der Debian-Build erzeugt RAUC-Bundle und optional ein Installationsimage. Signierte Metadaten binden Version, Kanal, Prüfsumme, Architektur und Testergebnisse. Echte QEMU-Tests prüfen Start, Laufzeit, Update, Rückfall und persistente Daten vor der Veröffentlichung. Eine lokale Testsuite ersetzt diesen Image-Test nicht.

Der tägliche Debian-Wartungslauf verwendet signierte Inventare und einen
festgehaltenen Titan-Anwendungscommit. Aktueller Betriebssystem-Builder und
unveränderter App-Payload werden getrennt geprüft und im signierten Manifest
gebunden. Veröffentlichungen von Funktions- und Systempflegeversionen teilen
sich eine Release-Warteschlange. Die Oberfläche hat einen gemeinsamen Kanal,
Prüf-/Installationsweg und Zeitplan; der Neustart bleibt bestätigt.
