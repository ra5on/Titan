# Titan auf Debian 13

Titan besteht aus einer Python-Webanwendung, einem privilegierten Verwaltungsagenten und einer statischen Weboberfläche. Caddy stellt HTTPS auf Port 5000 bereit. Docker, Samba, QEMU/libvirt, noVNC und Dateisystemwerkzeuge gehören zum vollständigen Systemimage.

## System und Daten

Das UEFI-Image enthält eine EFI-Partition, einen gemeinsamen Bootbereich, zwei ext4-Systemslots mit je 16 GiB und einen persistenten ext4-Datenbereich. Nur der inaktive Systemslot wird beim Update beschrieben. GRUB verwaltet Startversuche und Rückfall; RAUC prüft signierte Bundles. Eine Gesundheitsprüfung bestätigt den neuen Systemstand erst nach dem Start.

NAS-Konfiguration, Benutzer, Freigaben sowie Docker- und VM-Daten liegen persistent. `/etc` verwendet eine Overlay-Ebene. Signierte Updates müssen den Systemkontenvertrag und das Datenschema erhalten. Ein Rollback setzt das Betriebssystem zurück, nicht Nutzdaten oder Datenbanken. Änderungen des gemeinsamen Bootlayouts brauchen ein neues Installationsimage.

## Verwaltung

Die Webanwendung prüft Sitzung, Rolle, CSRF und erlaubte Aktionen. Der Agent bietet fest definierte Operationen. Längere Änderungen laufen als Hintergrundaktionen weiter, auch wenn der Browser geschlossen wird. Aktionen werden serialisiert; Kontosperren besitzen einen getrennten Ausführungspfad.

Update-Fortschritt wird vom Agenten atomar unter `/run/titan` gespeichert und über eine schreibgeschützte Administrator-API gelesen. Nur Downloadwerte besitzen eine gemessene Prozentanzeige. Nach einem Agentenneustart werden zurückgebliebene laufende Vorgänge als unterbrochen angezeigt.

## Veröffentlichung

Der Debian-Build erzeugt RAUC-Bundle und optional ein Installationsimage. Signierte Metadaten binden Version, Kanal, Prüfsumme, Architektur und Testergebnisse. Echte QEMU-Tests prüfen Start, Laufzeit, Update, Rückfall und persistente Daten vor der Veröffentlichung. Eine lokale Testsuite ersetzt diesen Image-Test nicht.
