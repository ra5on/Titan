# Backups und Meldungen · Alpha

Titan 0.2.0 bietet externe Sicherungen und kontrollierte Wiederherstellungen. Die Verfahren wurden mit temporären Daten und gemockten Hostbefehlen geprüft. Die Debian-, Samba- und libvirt-Integration muss noch auf Testhardware geprüft werden.

## Sicherungsziel

Unter **Backups** ein bereits eingehängtes, beschreibbares Dateisystem unter `/mnt` oder `/media` auswählen. Titan mountet oder formatiert keine Laufwerke. Die Systemplatte, Freigaben und ineinander verschachtelte Quell-/Zielpfade werden abgelehnt. Das Ziel muss private Unix-Dateirechte unterstützen, beispielsweise ext4, XFS oder Btrfs; FAT ist für vertrauliche Konfigurationssicherungen ungeeignet.

Jede Installation besitzt einen eigenen Bereich unter `.titan-backups/`. Archive, Konfigurationen und Passworthashes sind rootgeschützt. Ein verschwundenes Ziel verursacht einen Fehler; es wird nicht ersatzweise auf die Systemplatte geschrieben. VM- und Datensicherungen verwenden dasselbe ausgewählte Ziel. Bei einem Zielwechsel werden nur die Sicherungen auf dem aktuell ausgewählten Laufwerk angezeigt.

## Inhalt und Zeitplan

Die ausgewählten Freigaben werden vollständig gesichert. NAS-Konfiguration umfasst Webkonten mit Passworthashes, Rollen und Sperren, Titan-Einstellungen, verwaltete Linux-UIDs, SMB-Zugangsdaten sowie Freigabenrechte und Verwaltungsmetadaten. Websitzungen und laufende Aufträge werden ausgeschlossen. App-Konfigurationsverzeichnisse, Containerdatenbanken, VM-Disks, TLS-Schlüssel, GitHub-Lesetoken und das vollständige Debian-System sind nicht Bestandteil dieser Konfigurationssicherung. Im zentralen Backup-Assistenten können installierte Apps zusätzlich ausgewählt werden. Ihre Konfiguration, internen Datenbanken und Zugangsdaten werden dann gemeinsam nach dem Stoppen aller Paketdienste auf das getrennte Sicherungsziel geschrieben. App-Nutzdaten sind ausschließlich mit **Nutzdaten zusätzlich sichern** enthalten. Die bisherige lokale Sicherung in der App-Verwaltung bleibt für Kompatibilität und Updates erhalten; sie ersetzt keinen externen Sicherungslauf.

Tägliche oder wöchentliche Sicherung im gewählten Stundenfenster aktivieren. Die Uhrzeit verwendet die Zeitzone des NAS; der Webdienst muss laufen. Es gibt einen Versuch pro Fenster und keine fortlaufende Wiederholung bei fehlendem Laufwerk. Verpasste Fenster werden nicht nachgeholt. Die Aufbewahrung entfernt nur erkannte eigene Datensicherungen nach einem erfolgreichen Lauf; VM-Sicherungen werden davon nicht gelöscht.

Freigaben werden während eines Backups nicht vollständig eingefroren. Für konsistente Datenbanken oder gleichzeitig geänderte Dateien die betreffende Anwendung vorher anhalten. Die Archivprüfung erkennt Übertragungsfehler anhand SHA-256 und überprüft die Archivpfade; sie ersetzt keine regelmäßig erprobte Wiederherstellung oder verschlüsselte Offline-Sicherung.

Ausgewählte Apps werden für den gesamten Sicherungslauf angehalten. Danach startet Titan nur die zuvor laufenden Dienste wieder. App-Auswahl, ausdrücklich eingeschlossene Nutzdaten, Ziel und Zeitplan stehen in der Zusammenfassung des Assistenten. Große Nutzdaten können entsprechend längere Unterbrechungen verursachen.

## Wiederherstellung

**Dateien wiederherstellen** prüft zunächst das Archiv und erstellt einen neuen Ordner in der gewählten Zielfreigabe. Darunter liegen die gesicherten Freigaben. Bestehende Dateien werden nicht überschrieben. Die aktuellen Leser-/Schreiberrechte der Zielfreigabe werden auf die wiederhergestellten Dateien angewendet. Anschließend Inhalt im Dateimanager kontrollieren.

**App wiederherstellen** setzt ausschließlich eine weiterhin installierte, vollständig gestoppte App mit passender Vorlage und identischen tatsächlichen sowie lokal verfügbaren Images zurück. Konfiguration, Datenbanken und gespeicherte Zugangsdaten gehören zusammen; Nutzdaten werden nur nach zusätzlicher Auswahl zurückgesetzt. Unix-Rechte und Eigentümer bleiben erhalten. Die bisherigen Ordner und privaten Optionen bleiben für eine Rücksetzung erhalten, und die neu angelegten Container bleiben gestoppt. Ein Versionswechsel oder eine unvollständige Rücksetzung sperrt den Start. Ablauf, Recovery-Verzeichnisse und Grenzen stehen unter [Speicher, Sicherung und Benachrichtigungen](STORAGE-BACKUP-MONITORING.md).

**Konfiguration exportieren** erzeugt einen privaten Prüfexport auf dem NAS; er wird nicht im Browser heruntergeladen. Der Export enthält Passworthashes und muss vertraulich bleiben.

**NAS-Konfiguration wiederherstellen** benötigt die vollständige Backup-ID als Bestätigung. Es werden nur Sicherungen desselben Hosts mit weiterhin passenden Linux-UIDs, vorhandenen Datenpfaden und passenden Appinstallationen übernommen. Webdienst und SMB werden kurz angehalten; vorher wird der aktuelle Stand für eine Rücksetzung gesichert. Sitzungen enden, danach erfolgt die Anmeldung mit einem aktiven Konto und dem Passwort aus der Sicherung. Bei unvollständiger Rücksetzung bleibt SMB zum Schutz der Daten angehalten; eine private Recovery-Kopie unter `/var/lib/titan-agent/restore-recovery-*` bleibt für die lokale Fehlerbehebung erhalten. Keine Benutzer-UIDs, Datenordner oder Pools werden neu angelegt oder umgewidmet. Das Ergebnis erscheint unter Backups/Meldungen.

**VM sichern** ist nur für eine vollständig ausgeschaltete, von Titan verwaltete VM möglich. Gesichert werden Definition und eigenständige QCOW2-Disk; externe Backing-Dateien und Datenfiles werden abgelehnt. Wiederherstellung verwendet einen neuen Namen, eine neue UUID, eine neue Disk und frisch aufgebaute Standardgeräte mit NAT/BIOS. Hostpfade und Geräte aus einem Archiv werden nicht übernommen. Entfernen einer VM bewahrt ihre Disk.

## Lokale Meldungen

Die Prüfung läuft etwa alle fünf Minuten; **Jetzt prüfen** fordert eine aktuelle Prüfung an. Titan meldet ab 90 % belegtem Speicher eine Warnung, ab 97 % einen Fehler, SMART-Gesundheitsfehler, Laufwerkstemperaturen ab 55 °C, nicht gesunde ZFS-Pools, Backupfehler und installierte, inaktive Dienste. Nicht unterstützte SMART-Abfragen bleiben als unbekannt erkennbar. Dienste werden über ihren tatsächlichen systemd-Zustand geprüft.

Meldungen erscheinen mit Glockenindikator in der Oberfläche. Bestätigen markiert eine Meldung als gelesen; der Fehler bleibt sichtbar, bis seine Ursache behoben ist. Behobene Fehler bleiben im Verlauf. E-Mail, Push-Nachrichten und USV-Anbindung sind noch nicht implementiert.
