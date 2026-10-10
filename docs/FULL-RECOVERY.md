# Vollständige Wiederherstellung

**Entwicklungsstand, noch nicht als Stable abgenommen.** Die neuen Funktionen
liegen im Entwicklungszweig. Ein erfolgreich gebautes Rettungsmedium allein
belegt weder seinen Bootvorgang noch einen wiederhergestellten, nutzbaren NAS.

Titan erstellt eine kalte Sicherung des Systemlaufwerks und aller lokalen
Datenlaufwerke. Dabei bleiben die vollständigen Dateisysteme einschließlich
Konten, Rechten, ACLs, erweiterten Attributen, Datenbanken, VM-Dateien und
ZFS-Metadaten erhalten. Es handelt sich um eine komprimierte Laufwerkskopie;
Laufzeit und Platzbedarf hängen deshalb von den gesamten Laufwerken ab.

## Ablauf

1. In **Datensicherung** ein separates ext4- oder XFS-Sicherungslaufwerk wählen.
2. **Rettungsplan vorbereiten** öffnen und die aufgeführten Laufwerke prüfen.
   Den heruntergeladenen ZIP-Plan auf das Sicherungslaufwerk kopieren.
3. VMs geordnet herunterfahren, anschließend den NAS herunterfahren. Vom
   passenden Titan-Rettungsmedium auf einem separaten USB-Stick starten.
4. **Vollständig sichern** wählen, Sicherungslaufwerk und ZIP-Plan auswählen.
   Alle Quelllaufwerke müssen vorhanden und unbenutzt sein. Erst dieser Schritt
   erstellt die eigentliche Sicherung; der ZIP-Plan enthält keine Nutzdaten.
5. Für die Wiederherstellung die Originalplatten abtrennen und leere Ersatzplatten
   anschließen. Vom Rettungsmedium starten und **Auf Ersatzplatten wiederherstellen**
   wählen. Jede Quelle einer eigenen Ersatzplatte zuordnen. Ersatzplatten dürfen
   größer sein, müssen aber dieselbe logische Sektorgröße verwenden.
6. Nach erfolgreichem Zurücklesen aller Platten ausschalten, Rettungsmedium
   entfernen und vom wiederhergestellten Systemlaufwerk starten.

Die Sicherung enthält auch Kennwörter und Schlüssel. Sie ist nicht verschlüsselt;
das Sicherungslaufwerk muss entsprechend geschützt aufbewahrt werden. Netzwerk-
oder durchgereichte VM-Laufwerke sind kein Bestandteil einer lokalen Plattenkopie.
Der Planexport verweigert eine Vollständigkeitszusage, wenn solche Quellen,
fehlende Datenpfade oder unvollständige Speicherverbünde erkannt werden.

## Unterbrechungen und Schutz der Originale

Alle Archive werden vor dem ersten Schreibzugriff vollständig geprüft. Original-
und Sicherungslaufwerke sind als Restore-Ziele gesperrt. Die tatsächlichen
Blockgeräte bleiben während des Transfers exklusiv geöffnet; Größe, Sektorgröße,
Kennung und Nutzung werden vorab geprüft.

Während der Übertragung werden die ersten und letzten MiB jeder Platte
zurückgehalten. Dadurch steht auch die GPT-Sicherungstabelle erst bereit, wenn
alle Daten übertragen und zurückgelesen wurden. Die Systemplatte wird zuletzt
freigegeben. Das private Journal auf dem Sicherungslaufwerk bindet eine
Wiederaufnahme an genau dieselbe Sicherung und dieselben Zielkennungen.

Nach einer Unterbrechung dieselbe Sicherung und Zielzuordnung erneut wählen.
Titan prüft die Sicherung erneut und wiederholt den Transfer. Ein vorhandenes
Erfolgsjournal ersetzt keine Prüfung: Auch dann werden die Zielplatten erneut
mit den gespeicherten Prüfsummen verglichen.

## Getrennte Nachweise

- Lokale Tests prüfen Archivkorruption, unveränderte Originale, unterbrochenen
  Transfer, Wiederaufnahme, Primär-/Sicherungs-GPT, kurze Schreibvorgänge sowie
  mehrdeutige, fehlende und ausgetauschte Ziele.
- HTTP-Tests prüfen Administratorrechte, unveränderte Planinhalte, Download,
  Cache-Schutz und die Ablehnung zusätzlicher Parameter.
- `Recovery medium acceptance` baut ein eigenes UEFI-Rettungs-ISO und prüft echte
  virtuelle Blockgeräte, geänderte Kennungen, VirtIO-/SCSI-Wechsel, größere Ziele,
  Dateirechte, SQLite und QCOW2. Ein Fehlschlag bleibt ein Fehlschlag; ein
  ISO-Build ohne anschließenden Boot-/Restore-Erfolg reicht nicht.
- `Unpublished NAS image acceptance` baut und prüft den NAS getrennt, einschließlich
  A/B-Update und Rückfall. Er erstellt keine Veröffentlichung und keinen Release-Tag.
- Die abschließende Produktabnahme muss den wiederhergestellten NAS booten und
  dort Anmeldung, SMB-Rechte, Anwendungen und einen echten VM-Gast benutzen.
  Die Freigabeprüfung verlangt diese Nachweise für dieselben Image-, Rettungsmedium-
  und Katalog-Prüfsummen. Der derzeitige reine Rettungsmedium-Test erfüllt diese
  weitergehende Abnahme ausdrücklich noch nicht.
