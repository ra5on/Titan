# Titan 0.5.0 Alpha · Verwaltung und Wiederherstellung

Titan bleibt Alpha. Die zehn geplanten Bereiche sind umgesetzt; die Beta-Freigabe erfolgt erst nach dem eigenen Test auf dem NAS.

## Die zehn Bereiche

1. **Desktop und Fenster:** freies Drag-and-Drop mit sichtbarem Ziel, gespeicherte Verknüpfungen und Fenster, kompakte Bedienelemente und an die Bildschirmbreite angepasste Ansichten.
2. **Dateimanager:** Ordnerfavoriten, Unterordnersuche mit Typ-, Größen- und Datumsfiltern sowie vollständigen Fundorten. Auf dem Handy scrollt die Dateiliste in einer Fläche; Werkzeugleiste und Auswahlaktionen bleiben oben erreichbar. Löschbestätigungen verwenden Ja/Nein.
3. **Benutzer und Gruppen:** vererbte Freigabe- und Anwendungsrechte, ausdrücklich gesetzte Benutzerrechte, private persönliche Ordner und tatsächlich durchgesetzte ZFS-Benutzerquoten. Ext4/XFS-Quoten werden ohne eingerichtetes Kernel-Quota-Backend nicht angeboten.
4. **Speichermanager:** Systemplatte, eingerichtete Speicherbereiche, Laufwerke und Wartung mit SMART-Tests, geplanten ZFS-Scrubs/Snapshots und Aufbewahrung. Ein ZFS-Snapshot wird als zusätzlicher Klon geöffnet, damit Originaldaten erhalten bleiben.
5. **Paketzentrum:** Dienststatus und Abhängigkeiten, Diagnose, Reparatur, Port-/Paket-Einstellungen, dienstbezogene Protokolle und Aktualisierung mit vorheriger Konfigurations-/Datenbanksicherung. Die vier Titan-Pakete bleiben Immich, AdGuard Home, Pi-hole und Nextcloud + Euro-Office.
6. **VM-Verwaltung:** Detailbereiche Konsole, Hardware, Netzwerk und Sicherungen. Zusätzliche Festplatten und Netzwerkkarten, kalte Klone und Snapshots sowie Gastagent-Kanal und Gast-IP-Adressen. Externe Archive erfassen alle verwalteten Laufwerke und UEFI-Variablen; alte Einzellaufwerk-Archive bleiben lesbar.
7. **Datensicherung:** Assistent mit Inhalt, Ziel, Zeitplan und Prüfung; gesicherte Versionen durchsuchen und ausgewählte Dateien oder Ordner in einen neuen Zielordner wiederherstellen. Delegierte Backup-Benutzer erhalten ausschließlich Zugriff auf vollständig lesbare Quellen und beschreibbare Ziele, einschließlich einer erneuten Prüfung bei Ausführung.
8. **Sicherheit:** optionale Zwei-Faktor-Anmeldung, einmal verwendbare Wiederherstellungscodes, Sitzungsübersicht/-widerruf und Anmeldeverlauf. Rechte werden auch für wartende Verwaltungsaufträge erneut geprüft.
9. **Ressourcen und Meldungen:** CPU/RAM-, Netzwerk- und Datenträgerverlauf aus realen Systemzählern; nur vorhandene Messwerte erscheinen. Priorisierte Meldungen führen direkt zum betroffenen Bereich. Optionaler SMTP-Versand unterstützt TLS/STARTTLS und einen Testversand.
10. **Prüfung und Dokumentation:** zusätzliche HTTP-, Rechte-, Datei-, Paket-, VM- und UI-Regressionen, reale QEMU-Laufwerksprüfungen, Demo-Screenshots in der README sowie eine nachvollziehbare manuelle Beta-Checkliste.

## Dokumente direkt in Titan bearbeiten

Nach Installation von **Nextcloud + Euro-Office** kann der Dateimanager Word-, Tabellen- und Präsentationsformate über **In Office öffnen** direkt in einem integrierten Editor öffnen. Dokumente bleiben in ihrer ursprünglichen NAS-Freigabe. Der lokale Dokumentserver erhält einen zeitlich begrenzten Dateizugang; Rückschreiben erfordert eine signierte Antwort, aktuelle Zugriffsrechte und dieselbe Dateirevision. Externe Änderungen werden nicht überschrieben. Der normale Texteditor bleibt für andere Textdateien verfügbar.

Der Editor unterstützt Dokumente bis 16 MiB. DOCX/XLSX/PPTX, ODF, RTF und CSV erhalten beim Speichern ihr ursprüngliches Format; bei Bedarf wird der lokale Konverter verwendet. Alte DOC/XLS/PPT-Dateien werden schreibgeschützt geöffnet. Die Demo enthält keinen Dokumentserver und kennzeichnet die fehlende Installation. Das Paket-Laufzeitexperiment prüft echten Dokumentabruf, Konvertierung und Rückschreiben mit Euro-Office; interaktive Editorbedienung und Zusammenarbeit müssen auf dem NAS getestet werden.

Technischer Hintergrund: [Dokument-Callbacks](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/) und [lokale Konvertierung](https://api.onlyoffice.com/docs/docs-api/additional-api/conversion-api/request/).

## Grenzen vor der Beta

- Snapshots, Klone und Hardwareänderungen benötigen vollständig ausgeschaltete VMs. RAM-Zustand und laufende Gastsysteme werden nicht eingefroren. Der Gastagent benötigt zusätzlich die Installation und Aktivierung im Gastbetriebssystem.
- Datensicherungen sind versionsbasierte Archive, keine laufende Replikation. App-Datenbanken benötigen eine konsistente Paket-/App-Sicherung; Fotos und sonstige externe Nutzdaten zusätzlich als Freigabe sichern.
- SMART, ZFS-Wartung, echte USB-/GPU-Geräte und SMTP-Zustellung müssen auf geeigneter Hardware beziehungsweise mit einem eigenen Mailserver geprüft werden.
- Ein Rollback auf Systemversionen vor 0.5.0 erhält die Konfiguration, aber diese älteren Versionen können die neue Zwei-Faktor-Anmeldung noch nicht prüfen. Titan zeigt den Sicherheitswechsel im Rollback-Dialog an.
- Browserprüfungen mit schmalem Viewport ersetzen keinen Test auf einem echten iPhone/Safari oder Android-Gerät. Die Bilder zeigen die isolierte Demo mit Beispieldaten.

[Prüfnachweis](QA-0.5.0.md) · [Beta-Testplan](BETA.md) · [Gruppen und Sicherheit](IDENTITY-SECURITY.md) · [Speicher, Sicherungen und Meldungen](STORAGE-BACKUP-MONITORING.md) · [Paket- und VM-Verwaltung](PACKAGES-AND-VMS.md)
