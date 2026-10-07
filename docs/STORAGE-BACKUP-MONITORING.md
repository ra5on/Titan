# Speicher, Sicherung und Benachrichtigungen

Der Speichermanager trennt **Speicherbereiche**, **Laufwerke** und **Zustand & Zeitpläne**. Die Systemplatte bleibt sichtbar. Belegung wird nur für erreichbare, eingerichtete Dateisysteme angezeigt; ein fehlendes Datenlaufwerk bekommt keine erfundenen Messwerte der Systemplatte.

## Regelmäßige Prüfungen

Unter **Zustand & Zeitpläne → Zeitplan hinzufügen** kannst du folgende Aufgaben planen:

- Einen kurzen oder ausführlichen SMART-Selbsttest für ein erkanntes physisches Laufwerk. Ob ein Laufwerk den Test unterstützt, bestimmt dessen Firmware beziehungsweise der Controller. Ein gestarteter Selbsttest ist noch kein abgeschlossenes positives Testergebnis. Das Ergebnis findest du unter **Laufwerke → Zustand ansehen**.
- Eine ZFS-Datenprüfung (Scrub) für einen eingerichteten Pool. Die Prüfung startet im Hintergrund; den Verlauf zeigt der ZFS-Prüfstatus.
- Regelmäßige ZFS-Wiederherstellungspunkte mit einer Anzahl aufzubewahrender Versionen. Titan entfernt ausschließlich Punkte, die der jeweilige Zeitplan selbst erstellt hat. Manuelle Punkte und Punkte anderer Zeitpläne bleiben erhalten. Von Klonen oder Holds benötigte Punkte werden nicht erzwungen gelöscht.

Zeitpläne gelten in der lokalen Zeitzone des NAS. Titan startet einen fälligen Zeitplan pro Kalendertag höchstens einmal. Ein Fehler wird gespeichert und löst keine sofortige Wiederholungsschleife aus. Der Verwaltungsdienst und die Webverwaltung müssen laufen; nach einem längeren ausgeschalteten Zustand wird kein historischer Testlauf erfunden.

## ZFS-Wiederherstellung

**Wiederherstellen** erstellt einen neuen ZFS-Speicherbereich als Klon des ausgewählten Punkts. So kannst du die alten Daten ansehen und als Freigabe bereitstellen, während die aktuellen Dateien erhalten bleiben. Der neue Bereich braucht einen freien Namen und liegt innerhalb des verwalteten NAS-Datenbereichs. Eine Wiederherstellung schreibt keine bestehenden Dateien über.

Ein ZFS-Klon teilt zunächst die Datenblöcke mit dem ursprünglichen Stand; zusätzliche Änderungen benötigen neuen Speicherplatz. Die verwendeten Funktionen sind in den offiziellen [OpenZFS-Befehlen für Snapshots](https://openzfs.github.io/openzfs-docs/man/master/8/zfs-snapshot.8.html) und [Klone](https://openzfs.github.io/openzfs-docs/man/master/8/zfs-clone.8.html) beschrieben.

Ein Klon benötigt seinen ursprünglichen Wiederherstellungspunkt. Das Löschen dieses Punkts wird von ZFS verweigert, solange die Abhängigkeit besteht. Titan verwendet keine rekursiven oder erzwungenen Löschoptionen.

Ext4 und XFS erhalten keine vorgetäuschte ZFS-Snapshot-Funktion. Für diese Dateisysteme und als unabhängige zweite Kopie gibt es die versionierte Datensicherung.

## Datensicherung

Unter **Backups → Sicherung einrichten oder ändern** führt ein Assistent durch Inhalt, Ziel, Zeitplan und Aufbewahrung. Du kannst Freigaben, NAS-Konfiguration mit Benutzern und Berechtigungen sowie installierte Apps auswählen. Für jede App enthält die Auswahl Konfiguration, interne Datenbanken und gespeicherte Zugangsdaten. **Nutzdaten zusätzlich sichern** nimmt den zugeordneten App-Datenordner ausdrücklich hinzu. Ohne diesen Schalter bleiben externe Nutzdaten ausgeschlossen.

Apps verwenden dasselbe ausgewählte unabhängige Sicherungsziel und denselben täglichen oder wöchentlichen Zeitplan wie die übrigen ausgewählten Inhalte. Vor dem Lesen stoppt Titan alle Dienste der ausgewählten Apps. Nach dem Sicherungslauf werden ausschließlich die zuvor laufenden Dienste wieder gestartet; zuvor gestoppte oder einmalig abgeschlossene Dienste bleiben gestoppt. Fehlende oder pausierte Container müssen vor einer Sicherung repariert beziehungsweise fortgesetzt oder gestoppt werden. Bei sehr großen App-Nutzdaten dauert diese Unterbrechung entsprechend länger.

Als Ziel dienen separat eingehängte externe Laufwerke oder bereits eingehängte Netzlaufwerke unter `/mnt`, `/media` oder deren unterstützten Aliasverzeichnissen. Das Ziel muss private Unix-Dateirechte ermöglichen; ein beliebiges Windows-Netzlaufwerk ohne diese Rechte wird nicht als sicheres Sicherungsziel akzeptiert. Titan mountet oder formatiert dafür keine Laufwerke automatisch. Systemplatte, virtuelle Dateisysteme, schreibgeschützte Ziele und Überschneidungen mit den Quelldaten werden abgelehnt. Ein verschwundenes Ziel wird nicht durch ein Verzeichnis auf der Systemplatte ersetzt.

Unter **Gesicherte Versionen → Dateien ansehen** kannst du den Sicherungsinhalt durchsuchen. Die Dateiansicht enthält ausschließlich Freigabedaten; Konfiguration, Passworthashes und zweite Faktoren erscheinen dort nicht. Ausgewählte Dateien und Ordner werden in einen **neuen Ordner** einer Zielfreigabe geschrieben und übernehmen deren Zugriffsrechte. Vorhandene Dateien bleiben erhalten. Vor dem Schreiben prüft Titan die vollständige Archivstruktur und Prüfsumme. Links, Spezialdateien und unsichere Pfade werden abgelehnt.

Eine Konfigurationssicherung enthält vertrauliche Zugangsdaten in geschützten Dateien. Wiederherstellung dieser Konfiguration ist ein eigener Vorgang und beendet bestehende Websitzungen. Ein Systemrollback stellt keine Nutzdaten, Dateisicherungen oder App-Datenbanken zurück. Laufende Datenbanken brauchen eine konsistente, anwendungsspezifische Sicherung.

**App wiederherstellen** ist eine eigene Administratoraktion unter **Gesicherte Versionen**. Zuerst das gesamte noch installierte App-Paket stoppen. Titan prüft Prüfsumme, vollständige Archivstruktur, aktuelle Vorlage, Ports und die tatsächlich verwendeten sowie lokal verfügbaren Image-IDs. Ein Versionswechsel, eine fehlende Vorlage oder ein fehlender Container wird nicht automatisch übergangen. Die Wiederherstellung setzt Konfiguration, interne Datenbanken und die dazugehörigen Zugangsdaten gemeinsam ein; gesicherte Nutzdaten nur nach zusätzlicher Auswahl. Unix-Eigentümer und Dateirechte bleiben erhalten. Container werden aus der geprüften Titan-Vorlage ohne Image-Download neu angelegt und bleiben gestoppt.

Der vorherige Konfigurations- beziehungsweise Datenordner bleibt als `.titan-before-restore-*` neben seinem bisherigen Ort erhalten. Das private Verzeichnis `/var/lib/titan-agent/app-restore-recovery-*` enthält vorherige Optionen, Compose-Konfiguration und die zugehörigen Ordnerpfade. Es ist keine unabhängige zweite Sicherung und benötigt zusätzlichen freien Speicher. Bei einem Fehler versucht Titan, diesen vorherigen Stand wieder einzusetzen. Eine unterbrochene oder unvollständig zurückgesetzte Wiederherstellung behält einen privaten `restore-pending.json`-Marker; Start und Änderungen bleiben gesperrt, bis der Administrator die lokale Rücksetzung anhand des Recovery-Verzeichnisses abschließt. Stoppen und Entfernen der Container bleiben zur Fehlerbehebung verfügbar. Recovery-Dateien und alte Ordner werden nicht automatisch gelöscht.

Die Dateiansicht einer gemischten Sicherung zeigt ausschließlich Freigabedaten. App-Konfiguration, Datenbanken und Zugangsdaten sind dort nicht durchsuchbar. Delegierte Backup-Benutzer erhalten weder App-Sicherungen noch gemischte Archive mit App-Inhalten. Die Demo bietet keine echte App-Sicherung oder Wiederherstellung an.

## Ressourcen und Meldungen

Der Ressourcenmonitor zeigt CPU- und RAM-Verlauf sowie Netzwerk- und Laufwerksaktivität aus echten Linux-Zählerdifferenzen. Partitionen, Loop-Geräte, Docker-Schnittstellen und Host-Bridges werden nicht zusätzlich in die aggregierten Raten eingerechnet. Bei nicht unterstützten virtuellen Netzwerktopologien kann die Auswahl der erfassten Netzwerkanschlüsse eingeschränkt sein. Ein Neustart oder ein zurückgesetzter Zähler erzeugt eine Messlücke statt einer falschen Nullmessung. Der Messverlauf wird im Speicher des Verwaltungsdiensts gehalten; nach dessen Neustart beginnt er neu.

**Meldungen** bietet Prioritätsfilter sowie aktuelle, unbestätigte und behobene Ereignisse. **Bereich öffnen** führt zum betroffenen Speicher-, App-, VM-, Backup- oder Einstellungsbereich. Bestätigen entfernt die Ursache einer Warnung nicht.

Optional kannst du SMTP-Benachrichtigungen einrichten. Unterstützt werden STARTTLS und direkte TLS-Verbindungen mit Zertifikatsprüfung. SMTP-Passwörter liegen ausschließlich im geschützten Zustand des Verwaltungsdiensts und werden über die Einstellungs-API nicht zurückgegeben. Sie werden nicht in den Konfigurationsexport aufgenommen; nach einer vollständigen Neueinrichtung müssen sie erneut hinterlegt werden. Neue Störungen und höhere Prioritäten werden gebündelt; die gleiche anhaltende Störung erzeugt keine E-Mail bei jeder Prüfung. **Testnachricht senden** verwendet die zuvor gespeicherten Einstellungen. In der Demo wird kein SMTP-Server kontaktiert.

## Prüfung auf echter Hardware

Die automatisierten Tests prüfen Auswahl, Aufbewahrung, sichere Zielpfade, tatsächliche Dateiinhalte, Berechtigungsübergabe, Prüfsummen, SMTP-TLS und Zählerdifferenzen. Vor einer Beta-Freigabe sollten zusätzlich reale USB- und Netzlaufwerke, SMART-fähige Laufwerke, ein ZFS-Scrub, Neustarts während geplanter Aufgaben, die Zustellung über einen echten SMTP-Server sowie Mobilgeräte geprüft werden.
