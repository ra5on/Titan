# Gemeinsame Speicherbereiche

Titan verwendet dieselben benannten Speicherbereiche für Apps, eigene Docker-Container, Freigaben, VM-Laufwerke und den Dateimanager. In den Auswahllisten stehen der Name, die freie Kapazität und der Zustand. Ein technischer Linux-Pfad muss für die normale Einrichtung nicht eingegeben werden.

Diese Beschreibung gilt für das gemeinsame Speichermodell im Quellstand von **0.5.3**. Die Freigabe und die tatsächlich ausgeführten Prüfungen beschreibt [QA-0.5.3](QA-0.5.3.md).

## Speicher einrichten und auswählen

Öffne **Speicher-Manager → Speicherbereiche**, um den internen Datenbereich und eingerichtete Laufwerke zu sehen. Zusätzliche Ext4-/XFS-Volumes und ZFS-Pools erscheinen mit ihrem eigenen Namen. Der Einrichtungsdialog legt das gewählte Dateisystem auf den ausdrücklich ausgewählten freien Laufwerken an; eine Formatierung löscht deren Inhalt und benötigt eine Bestätigung.

Unter **Speicher-Manager → Einstellungen → Standardspeicher** wählst du den Vorschlag für neue Daten. Anschließend **Standard speichern** anklicken. Dieser Vorschlag gilt für neue Apps, Container, Freigaben und virtuelle Laufwerke. Du kannst bei jeder Einrichtung ausdrücklich einen anderen geeigneten Bereich auswählen.

Ein Standardwechsel verschiebt keine vorhandenen Dateien, Apps, Datenbanken oder VM-Laufwerke. Bestehende Installationen behalten ihren gespeicherten Ort. Die technische Kennung eines Bereichs bleibt von seiner Anzeige in der Oberfläche getrennt.

| Bereich | Verwendung |
| --- | --- |
| **Interner Speicher** | Persistente NAS-Daten auf der Datenpartition: Dateien, Apps, Freigaben und VMs. |
| **Eigener Volume- oder Poolname** | Geeignete Dateibereiche eines eingerichteten Ext4-/XFS-Volumes oder ZFS-Pools. |
| **Registriertes externes Sicherungsziel** | Dateien und Sicherungen eines bereits eingerichteten externen Backupziels; kein allgemeiner Standardspeicher für Apps oder VMs. |

Titan übernimmt beliebige fremde Mounts nicht automatisch in diese Liste. Historische ZFS-Pools, deren Namen mit internen Datenverzeichnissen kollidieren, bleiben zum Lesen ihrer Dateien sichtbar, sind aber kein Ziel für neue App-, Freigaben- oder VM-Daten.

## Derselbe Name in allen Dialogen

- **App installieren:** Einen Speicherbereich auswählen. Titan legt Konfiguration, Datenbank und Nutzdaten der Paketdienste in diesem Bereich an. Wenn du einen vorhandenen Freigabeordner wählst, verwendet das Paket dessen Speicherbereich; die Freigabe selbst wird nicht verschoben.
- **Docker → Container erstellen:** Einen benannten Bereich für Containerdaten wählen. Titan erzeugt ein eigenes Datenverzeichnis. Alternativ kann ein vorhandenes Docker-Volume ausgewählt werden. Die beiden Varianten werden nicht gleichzeitig verwendet. Das Datenziel im Container, beispielsweise `/data`, ist eine gesonderte Einstellung.
- **Freigabe erstellen:** Den Speicherbereich auswählen und anschließend Benutzerrechte festlegen. Titan erzeugt den Freigabeordner im zugehörigen Freigabenbereich.
- **VM erstellen oder Laufwerk hinzufügen:** Das virtuelle Laufwerk bekommt einen eigenen Speicherbereich. Ein vorhandenes IMG-, RAW- oder QCOW2-Image kann über den Ordnerbrowser ausgewählt werden. Beim Import wird eine neue VM-Kopie angelegt; die Quelle bleibt erhalten.
- **Dateimanager:** Unter **NAS-Dateien** stehen die benannten Bereiche zur Verfügung. Der Ordnerbrowser beginnt im gewählten Datenbereich und bleibt darin. Freigaben behalten ihre eigene Zugriffsverwaltung.
- **Kopieren und Verschieben:** Den Zielbereich und einen darin vorhandenen Zielordner auswählen. Bestehende Dateien werden durch diese Auswahl nicht automatisch überschrieben.

Technische Pfade bleiben für Diagnose oder fortgeschrittene Einstellungen verfügbar. Sie ersetzen die serverseitige Prüfung des Speicherbereichs nicht.

## Wenn ein Laufwerk fehlt oder voll ist

Ein nicht erreichbarer Bereich bleibt mit **Nicht verfügbar** sichtbar. Titan leitet neue Daten dabei nicht auf den internen Speicher um. Das gilt auch dann, wenn der bisherige Standardspeicher gelöscht wurde oder seine gespeicherte Kennung nicht mehr bekannt ist. Du musst ausdrücklich einen erreichbaren anderen Bereich wählen oder das ursprüngliche Laufwerk wieder verbinden.

Bei **Voll** bleibt der Dateimanager zum Ansehen und Löschen nutzbar. Neue Apps, Freigaben und VM-Laufwerke sowie Kopier- und Verschiebeziele können dort nicht angelegt werden. Der für neue Daten vorgeschlagene Bereich wird weiterhin angezeigt; ein anderer Bereich wird erst nach deiner Auswahl benutzt.

Ein verschwundenes Laufwerk wird nicht durch ein leeres Verzeichnis auf der Systemplatte ersetzt. Vor dem Zugriff prüft Titan den tatsächlichen Mount und die gespeicherte Laufwerks- beziehungsweise Poolkennung. Ein neues Laufwerk mit demselben Namen wird dadurch nicht als das alte Laufwerk übernommen.

Freie Kapazität ist eine Momentaufnahme. Parallele App-Installationen, VM-Schreibvorgänge oder andere Benutzer können sie verändern. Auch bei einer gültigen Auswahl kann eine spätere Aktion scheitern, wenn inzwischen kein Platz mehr vorhanden ist; die Aktion zeigt dann einen Fehler.

## Sicherungsziele

Unter **Backups → Sicherung einrichten oder ändern** wählst du ein unabhängiges Sicherungsziel. Ein geeignetes zusätzliches Volume oder ein geeigneter Pool verwendet dafür seinen eigenen **backups**-Bereich. Du kannst auch einen vorhandenen Unterordner darin behalten. Der Stamm des Pools oder Volumes wird nicht als Backupziel angeboten. Der Backupbereich wird beim Speichern angelegt, falls er noch nicht existiert; die Anzeige eines Ordnerbrowsers legt ihn nicht an.

Der interne Speicher ist kein Backupziel. Ein Laufwerk wird ebenfalls ausgeschlossen, wenn es auf demselben Dateisystem wie NAS-Konfiguration, Freigaben oder installierte App-Daten liegt. Das wird beim Speichern und vor dem tatsächlichen Sicherungslauf erneut geprüft. Getrennte Namen oder Ordner auf demselben Dateisystem erzeugen keine unabhängige Sicherung.

Bereits konfigurierte externe Backupziele bleiben mit ihrem bestehenden Pfad erhalten. Sie benötigen eine verifizierte Einbindung, Schreibzugriff und passende private Unix-Dateirechte. Titan formatiert oder verbindet dafür kein fremdes Laufwerk automatisch.

Dateisicherungen, VM-Sicherungen und konsistente Sicherungen laufender App-Datenbanken haben unterschiedliche Anforderungen. Weitere Informationen: [Backups](BACKUPS.md) und [Speicher, Sicherung und Benachrichtigungen](STORAGE-BACKUP-MONITORING.md).

## Systemdateien und Rollback

**Interner Speicher** bezeichnet den gemeinsamen Datenbereich und niemals das Linux-Wurzelverzeichnis `/`. Der normale Web-Dateimanager erlaubt keine Bearbeitung der Betriebssystemdateien. Auch das Web-Terminal ist ein **Datenterminal** ohne Root- oder Sudo-Zugriff. Systemadministration erfolgt über einen dafür berechtigten SSH-Zugang.

Das A/B-Systemupdate schreibt den inaktiven Betriebssystembereich. Benutzerdaten, Freigaben, App-Daten und VM-Laufwerke bleiben im gemeinsamen Datenbereich beziehungsweise auf ihrem ausgewählten zusätzlichen Laufwerk. Ein Rollback wählt einen anderen Systemstand; es stellt diese Daten nicht auf einen früheren Inhalt zurück. Dafür wird eine unabhängige Datensicherung benötigt.

## Schnittstellen für Entwicklung und Prüfung

`GET /api/storage-locations` liefert den gemeinsamen Katalog und `default_storage`. Ressourcen verwenden stabile Kennungen wie `system`, `volume:fotos` oder `pool:archiv`. Zu jedem Eintrag gehören Anzeigename, Datenpfad, verfügbare Kapazität, Zustand und erlaubte Verwendungszwecke. Die historische Kennung `system` bleibt kompatibel und bezeichnet ausschließlich den internen Datenbereich.

Neue Installationen senden eine Kennung: Apps und eigene Container `storage_id`, VM-Laufwerke `storage`, Freigaben `storage`. Der Backenddienst löst diese Kennung für den jeweiligen Zweck auf. Unterverzeichnisse für Apps, Freigaben, VMs und Backups bleiben getrennt. Die Einstellung `storage_preferences_save` speichert nur den Vorschlag für neue Daten und führt keine Migration aus.

Vorhandene App- und VM-Datensätze behalten ihre bisherigen Pfade. Die Kompatibilitätsbehandlung und die gemeinsamen Prüfungen verhindern, dass ein Standardwechsel alte Datensätze neu zuordnet. Der Dateibrowser nutzt die bestehende `@system`-Schnittstelle innerhalb der geprüften Datenbereiche; sie gibt keinen Zugriff auf beliebige Systempfade.

Automatisierte Tests prüfen insbesondere Namen und Grenzen, nicht erreichbare oder volle Standardziele, unabhängige Backupziele, explizite Zielwechsel sowie unveränderte bestehende App- und VM-Pfade. Vor einer Beta-Freigabe müssen zusätzlich reale Laufwerke, Abziehen und Wiederverbinden, ein voller Datenbereich, Neustarts und die tatsächliche mobile Bedienung geprüft werden. Ein bestandener Quell- oder API-Test ist kein Nachweis dieser Hardware- und Browserprüfungen.
