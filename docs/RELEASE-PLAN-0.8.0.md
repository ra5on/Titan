# Titan 0.8.0: Wiederherstellung und einfache Updates

Arbeitsbasis: 0.7.0, `e0b8a80`. Nutzerauftrag vom 10. Oktober 2026:
Ersatzhardware-Wiederherstellung und ein gemeinsamer Update-Button. Keine USV
vorhanden; USV-Hardwareabnahme ist keine Voraussetzung dieses Auftrags.

## Geplante Umsetzung und Abnahme

1. Ein Updateangebot für Titan. Beide signierten Veröffentlichungswege werden
   geprüft; der Nutzer wählt keinen technischen Updatebereich. Ein persistenter
   Auftrag aktualisiert zuerst die Oberfläche, setzt sich im neuen Prozess fort
   und bereitet anschließend den Systemstand für den bestätigten Neustart vor. Unterbrechungen, geänderte Angebote,
   Rechteentzug und Rückfall müssen sichtbar bleiben. Details und manuelles
   Rollback gehören in einen aufklappbaren Bereich.
2. Vollständige Wiederherstellung benötigt mehr als den bisherigen
   Konfigurationsimport: Konten/SMB, ACLs, Daten, Apps samt Datenbanken, VM-Disks
   und Dienstkonfiguration. Sicherungsumfang vorab inventarisieren; fehlende oder
   nicht unterstützte Datenträger dürfen nicht als vollständig gesichert gelten.
   Kalte Sicherung mit angehaltenen Schreibern, geprüfte Archivpfade und Metadaten,
   verifizierte Übertragung, genügend Zielplatz, unveränderte Quelle und
   Wiederanlauf nach Unterbrechung sind Pflicht.
3. Die frische Zielinstallation darf keine bestehenden Nutzdaten überschreiben.
   Herkunft, kompatibler Systemstand, Speicherzuordnung und Vollständigkeit werden
   vor Änderungen geprüft. Die bisherige sichere Same-Host-Prüfung wird nicht
   einfach abgeschaltet. Wiederherstellung muss auf einer getrennten frischen
   Testinstallation mit gelöschtem altem System und tatsächlichen Nutzdaten
   abgenommen werden.
4. Regression: gezielte Zustands-/Negativtests, vollständige Python/UI-Suiten,
   Browserprüfung des vereinfachten Ablaufs und Recovery-Dialogs sowie reale
   Container-/UEFI-/SMB-/Update-/Wiederherstellungstests auf isolierten Runnern.
5. Veröffentlichung erst nach den relevanten Gates. Bekannte Grenzen und
   verbleibende Hardwareprüfungen konkret dokumentieren; keine pauschale
   Behauptung, sämtliche Hardware oder Stromausfälle seien geprüft.

## Nicht durch eine Versionskennung gelöst

Reale Controller-/Plattenkompatibilität und Dauerbetrieb brauchen die konkrete
Zielhardware. Ein Test in QEMU ist davon getrennt zu berichten. Vorhandene
historische Backupformate bleiben lesbar; ein Teilbackup darf nicht nachträglich
als vollständige Disaster-Recovery-Sicherung bezeichnet werden.

## Arbeitsstand, noch keine Freigabe

Der gemeinsame manuelle Updateauftrag und die vereinfachte Seite sind implementiert.
Die Archivschicht für Recovery bewahrt Sparse-Dateien, Hardlinks, Dateirechte und
Xattrs und prüft Archivpfade sowie Prüfsummen vor der Extraktion.

Noch offen sind der vollständige Recovery-Hostablauf (konsistentes Anhalten,
Inventarisierung aller Speicher, Zielzuordnung einschließlich ZFS, Wiederanlauf
nach Unterbrechung), dessen Bedienoberfläche und die Abnahme auf einer getrennten
frischen Installation. Die Archivtests allein belegen keine vollständige
Wiederherstellung. Automatische Updates verwenden bislang weiterhin den
bestehenden Systemupdate-Zeitplan. Für diese Arbeit wurde noch kein Stable-Release
erstellt; Version und bestehende Releases bleiben unverändert.

### Lokale Prüfungen vom 10. Oktober

- Vollständige Python-Suite: 1962 Tests, erfolgreich, 12 übersprungen.
- Nachfolgende Änderungen zusätzlich gezielt geprüft: 20 gemeinsame
  Updateabläufe, 10 Archivtests, 17 HTTP-Tests und 73 bestehende Updatetests.
- Alle 80 JavaScript-Verhaltenstests erfolgreich.
- Browser: gemeinsame Suche in der isolierten Demo ausgeführt; die Oberfläche
  zeigte anschließend ausdrücklich den Demo-Status. Eine echte Installation
  und die Wiederherstellung eines vollständigen NAS sind damit nicht belegt.
