# Titan-Systemupdates und Rollback

Unter **Systemsteuerung → Updates & Rollback** den Kanal **Alpha** wählen und nach
Updates suchen. Beta und Stable bieten erst dann Versionen an, wenn entsprechende
Veröffentlichungen vorhanden sind. Der Alpha-Kanal berücksichtigt später auch
Beta- und Stable-Versionen.

Es gibt **einen Update-Ablauf** für das gesamte NAS: eine Kanalwahl, eine
automatische Update-Regel sowie **Jetzt prüfen → Update vorbereiten → Neu
starten**. Neue Titan-Funktionen und Debian-Sicherheitskorrekturen werden als
signierte vollständige Systemstände angeboten. Ein Debian-Wartungsstand
behält die installierte Titan-Anwendung samt Oberfläche und Laufzeithelfern
auf ihrem eingefrorenen Quellstand. Ein Funktionsrelease aktualisiert Titan
und den passenden Systembereich gemeinsam. In den Versionsinformationen
werden Titan-Quellstand, Systemrevision und gemessene Paketänderungen getrennt
ausgewiesen; es gibt dafür keine zweite Update-Seite.

Ein Systemstand enthält den Debian-Systembereich einschließlich Kernel,
Docker und VM-Komponenten. Signatur, Prüfsummen und Kompatibilität werden vor der
Aktivierung geprüft. Titan beschreibt den inaktiven der beiden Systembereiche.
Der laufende Stand bleibt bis zum ausdrücklich bestätigten Neustart aktiv.

1. Update prüfen und vorbereiten.
2. Laufende virtuelle Maschinen geordnet herunterfahren.
3. „Neu starten“ wählen und mit **Ja, neu starten** bestätigen. Kein Wort abtippen.
4. Nach erfolgreicher Startprüfung erscheint der vorherige lokale Systemstand
   im Rollback-Dropdown. Für die Rückkehr auswählen, bestätigen und neu starten.

Direkt nach der ersten Installation ist das Dropdown noch leer. Es gibt einen
vorherigen Systemstand, sobald das erste Update erfolgreich gestartet wurde.
Automatische Updatesuche bzw. Vorbereitung löst keinen automatischen Neustart aus.
Die gemeinsame Automatik lässt sich täglich oder wöchentlich prüfen lassen.
**Manuell** meldet verfügbare Updates; **Automatisch im Wartungsfenster
vorbereiten** lädt und prüft den angebotenen Stand am gewählten Wochentag zur
gewählten Stunde der NAS-Zeitzone. Auch dann muss der Neustart bestätigt
werden. Die Hintergrundprüfung läuft bei geschlossenem Browser weiter.

Benutzer, Freigaberechte, NAS-Einstellungen sowie App-, VM- und Nutzdaten bleiben
auf dem gemeinsamen Datenbereich. Rollback setzt diese Daten nicht zurück und
ersetzt kein Backup. Unveränderte Systemkonfigurationen folgen dem ausgewählten
Systemstand; lokale Änderungen unter `/etc` bleiben erhalten. Ein Rollback
stellt auch die Debian-Paketversionen und damit den vorherigen Sicherheitsstand
wieder her, nicht nur die Titan-Oberfläche.

## Debian-Pflege und Freigabeprüfung

Der GitHub-Workflow **Debian security and package maintenance** prüft täglich
um **03:17 Uhr, Europe/Berlin** die offiziellen Debian-13-Quellen einschließlich
des Sicherheitsarchivs. GitHub berücksichtigt die Sommer-/Winterzeit; der
Start kann sich durch die Runner-Warteschlange verzögern. Die Prüfung läuft
in einem neuen Container auf einem Build-Runner und verändert keine Pakete
auf einem installierten NAS. Die automatische NAS-Updatesuche ist davon
unabhängig und folgt der oben gewählten gemeinsamen Regel.

Grundlage sind bereits veröffentlichte **signierte** Systemmanifest- und
Paketinventar-Dateien. Je Alpha, Beta und Stable werden die zwei jüngsten
veröffentlichten Titan-Quellstände gepflegt; mehrere Debian-Revisionen desselben
Quellstands gelten dabei als ein Stand. Ein Sicherheitsbuild verwendet den
exakten bisherigen Titan-Commit. Anwendungspaket und App-Installationsprüfungen
werden aus diesem Commit gebaut, während der aktuelle Systembuilder Debian
und die Systemkomponenten erneuert. Beide Quellstände werden signiert festgehalten.

Nur neuere, vertrauenswürdige offizielle Debian-Paketversionen lösen einen
Wartungsbuild aus. Der fertige Stand enthält die gemessene vollständige
Paketliste und eine begrenzte Vorschau der Änderungen. Unveränderte Pakete
führen zu keiner zusätzlichen Wartungsveröffentlichung. Vor Veröffentlichung
müssen die vollständigen Start- und Laufzeitprüfungen sowie echte Update-,
Rollback- und Fehler-Rückfalltests in einer wegwerfbaren VM bestehen. Für
Wartungsstände wird der zuvor veröffentlichte, signierte Systembundle als
Testbasis anhand seines Prüfsummennachweises und seiner eingebetteten Identität
geprüft. Eine fehlende Prüfung blockiert die Freigabe.

Ältere Releases ohne signiertes Paketinventar sind noch keine geeignete
Wartungsbasis. Die tägliche Pflege beginnt für einen Titan-Quellstand erst,
wenn dessen erste vollständige Freigabe mit Inventar veröffentlicht wurde.
Der neue Ablauf veröffentlicht zunächst ausschließlich signierte
Update-Bundles; ein intern erzeugtes Testimage wird nicht als neues
Installationsimage angeboten.

Wenn ein neuer Stand seinen Start nicht bestätigt, kann der Bootloader beim
nächsten Neustart auf den vorherigen gesunden Stand zurückgehen. Ein hängender
Gast benötigt dafür einen Reset in Proxmox. Die beiden Systembereiche liefern
keinen Schutz gegen einen Ausfall des gemeinsamen Datenträgers.

Der gemeinsame EFI-/GRUB-Startbereich wird durch diese Alpha-Systemupdates noch
nicht erneuert. Änderungen daran oder am Partitionslayout erfordern derzeit ein
neues Installationsimage. Normale kompatible Titan-/Debian-Versionen werden über
den Update-Kanal eingespielt.

[Installationsimage und Testgrenzen](TITAN-IMAGE.md). Eine bestehende anderes NAS-
Installation lässt sich damit nicht direkt auf Titan umstellen.

## Status in der Oberfläche

Kanalwahl, automatische Prüfung, Vorbereitung und Rollback sind unter **Systemsteuerung → Updates & Rollback** zusammengeführt. Im jeweiligen Bereich erscheint der aktuelle Vorgang mit Zustand und zuletzt ausgeführten Aktionen.

Ein Systemupdate meldet Angebotsprüfung, Konfigurationssicherung, Download, Signaturprüfung, Schreiben des inaktiven Slots und Bereitschaft zum Neustart. Download-Prozentwerte entstehen aus tatsächlich übertragenen Bytes und der signierten Gesamtgröße. Andere Phasen zeigen Status und Dauer ohne geschätzten Fortschrittsbalken. Fehler und unterbrochene Ausführungen sind unterscheidbar; vor einem erneuten Versuch den Systemstatus prüfen.
