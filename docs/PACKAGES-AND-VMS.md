# Paketzentrum und VM-Verwaltung

## Eigene Apps und bestehende Pakete

Neue Installationen im Appcenter sind für Cloudflare Tunnel, Immich, AdGuard
Home und Tailscale freigegeben. Vorhandene Pi-hole- und Nextcloud-/Euro-Office-
Installationen bleiben verwaltbar; sie sind keine neu angebotenen Apps.
Datenbank, Cache, Hintergrundaufgaben und gegebenenfalls Office gehören zur
jeweiligen Paketinstallation. Der Paketstatus prüft jeden Dienst: Ein laufender Hauptcontainer
allein ist kein Beleg für ein funktionierendes Paket. Der einmalige
Office-Einrichtungscontainer gilt nach erfolgreichem Ende als abgeschlossen.

Im Paketdialog stehen Übersicht, Einstellungen und Protokolle zur Verfügung.
Protokolle können für jeden Dienst geladen werden; gespeicherte Zugangsschlüssel
werden ausgeblendet. Diagnose prüft Datenordner, Netzwerk, Geräte und Dienste.
Reparieren erstellt fehlende Container erneut und prüft die Office-Verbindung.
Gespeicherte Daten und generierte Schlüssel bleiben erhalten.

Ports und die NAS-Adresse des Office-Pakets können bei vollständig gestopptem
Paket verändert werden. Konten und Passwörter werden in der jeweiligen App
verwaltet, weil Startumgebungsvariablen bereits angelegte Nextcloud- und
Datenbankkonten nicht zuverlässig verändern.

Titan verwendet freigegebene Paketvorlagen und übernimmt beim Update alle
zugehörigen Dienste gemeinsam. Die installierte Definition wird mit einem
Digest in den geschützten Verwaltungsdaten festgehalten. Eine spätere
Titan-Version darf eine neue Vorlage anbieten, ohne dass die bisherige
Installation als fremder Container behandelt wird. Veränderte Definitionen ohne
passenden Digest werden weiter blockiert.

Vor Einstellungen und Paketupdates wird eine kalte Sicherung des privaten
App-Verzeichnisses erstellt. Sie enthält Konfiguration, interne Datenbanken und
Verbindungsschlüssel. Fotos, Dokumente und andere Nutzdaten im separat gewählten
Datenordner gehören nicht zu dieser Sicherung und müssen zusätzlich über die
Dateisicherung gesichert werden. Ein fehlgeschlagenes Update startet nach einer
möglichen Datenbankmigration keine älteren Images automatisch. Diagnose und
Reparatur bleiben verfügbar; der Pfad der vorherigen Sicherung wird angezeigt.

Das Euro-Office-Paket stellt dem privilegierten Office-Gateway eine verifizierte
interne Containeradresse und den Verbindungsschlüssel bereit. Der Schlüssel
besitzt keine öffentliche HTTP-Leseroute. Die Dokumentintegration prüft
Dateiberechtigungen und Revisionen beim Öffnen und beim Speichern. Bei einer
ODF-Datei wird ein vom Editor geliefertes OOXML-Ergebnis vor dem Speichern zurück
in das ursprüngliche Format konvertiert.

## VM-Register

Die Maschinenübersicht verwendet kompakte Kacheln mit Name, Status, CPU live und
**RAM auf NAS (RSS)**. RSS ist der gemessene residente Speicher des VM-Prozesses
einschließlich Verwaltungsaufwand; er unterscheidet sich vom konfigurierten
Gast-RAM und der Belegung im Gast. Die Werte aktualisieren sich alle fünf
Sekunden. Fehlende Messungen werden als unbekannt angezeigt; ausgeschaltete VMs
zeigen keine veraltete CPU-/RAM-Auslastung.

Ein Klick auf eine Kachel öffnet die Details in der nutzbaren Fensterfläche.
Eine zusätzliche dauerhaft sichtbare Maschinenliste entfällt. **Zurück** erhält
Suchbegriff und Filter und stellt den Fokus auf die ausgewählte VM wieder her.
Kachelraster und Details passen sich an die tatsächliche Fensterbreite an.

Die Detailansicht trennt Konsole, Hardware, Netzwerk und Sicherungen. Die
Browserkonsole verbindet sich direkt; sie öffnet keinen separaten Tab.
Gastagent, zusätzliche Festplatten und Netzwerkkarten werden im ausgeschalteten
Zustand eingerichtet. Bis zu acht verwaltete qcow2-Laufwerke und acht
Netzwerkkarten werden pro VM unterstützt. Das Trennen eines Laufwerks erhält die
Image-Datei.

Anzeigenamen dürfen Großbuchstaben, Leerzeichen und Umlaute enthalten und bis
zu 96 sichtbare Zeichen lang sein. Sie werden als Titel getrennt vom internen
libvirt-Namen gespeichert. Beim Bearbeiten bleibt die UUID mitsamt Laufwerken
erhalten; hierfür die VM vorher ausschalten. Auch Klone und Wiederherstellungen
dürfen solche Anzeigenamen verwenden. Interne Namen bleiben auf sichere,
begrenzte Zeichen beschränkt und werden bei Bedarf automatisch erzeugt.

## Terminal und VM-Konsole

Das Terminal bietet Kopieren, Einfügen, Alles markieren, Bildschirm leeren,
Befehl abbrechen und Vollbild. Strg+C kopiert eine Auswahl oder geht ohne
Auswahl als Abbruch an die Shell. Strg+Umschalt+C kopiert; Strg+V,
Strg+Umschalt+V oder Umschalt+Einfg fügt ein. Rechtsklick, langes Drücken und
Umschalt+F10 öffnen das Schnellmenü. **Auf Desktop** legt eine Verknüpfung zum
Terminal an. Die Sitzung beginnt mit **Verbinden** und endet beim Schließen
des Appfensters oder beim Abmelden; Minimieren erhält sie.

In der VM-Konsole bleiben Strg+C und Strg+V Tastenkombinationen des Gastes.
Strg+Umschalt+C/V und die Zwischenablage-Schaltflächen übertragen Text zwischen
Browser und Gast. **Einfügen** überträgt den Text in die Gast-Zwischenablage;
anschließend Strg+V im Gast verwenden oder über das Schnellmenü an ihn senden.
Die gemeinsame Zwischenablage benötigt Unterstützung durch das Gastsystem und
funktioniert häufig nicht in reinen Textkonsolen. Ist die Browser-Zwischenablage
auf HTTP oder durch verweigerte Freigabe nicht verfügbar, steht ein Textdialog
bereit. Pro Übertragung sind höchstens 64 KiB UTF-8-Text erlaubt.

Das Menü bietet zusätzlich Gast-Tastenkombinationen, Einpassen und Vollbild.
Mit **Gast-Rechtsklick verwenden** gehen Rechtsklick und Touchgesten wieder an
den Gast; Titans Menü bleibt über **···** in der Werkzeugleiste erreichbar.
**Konsole auf Desktop** in den VM-Details legt einen Link zur betreffenden VM
an. Eine ausgeschaltete oder entfernte VM wird dadurch nicht gestartet.
Der Dunkel-/Hellmodus folgt der persönlichen Desktop-Einstellung. Der
Terminalinhalt und die Gastanzeige behalten ihre eigenen Bildschirmfarben.

Eine Aktualisierung derselben laufenden VM-Konsole erhält das verbundene
iframe im Dokument. Dadurch bleibt die VNC-Sitzung erhalten. Das Wechseln zu
einem anderen Detailtab oder das Schließen des VM-Fensters beendet sie.

Der optionale VirtIO-Gastagent-Kanal benötigt zusätzlich den Dienst
`qemu-guest-agent` im Gast. Wenn er antwortet, erscheinen Gast-IP-Adressen und
Herunterfahren über den Agent wird angeboten. Ein fehlender Agent verhindert
den normalen VM-Start und die reguläre ACPI-Abschaltung nicht.

Ein Klon kopiert alle Laufwerke in eigenständige qcow2-Dateien, übernimmt
UEFI-Variablen in eine eigene Datei und bekommt eine neue UUID sowie neue
MAC-Adressen. Exklusive USB-/Hostgeräte werden nicht übernommen. IP-Adresse und
Rechnername innerhalb des Gastes können trotzdem identisch sein und sollten vor
dem ersten gemeinsamen Start angepasst werden.

## Snapshot und Sicherung

Snapshots sind **kalte Laufwerks-Snapshots bei vollständig ausgeschalteter VM**.
Titan erfasst alle verwalteten Laufwerke sowie inaktive VM-Konfiguration und
UEFI-Variablen. RAM und laufende Gastprozesse werden nicht gespeichert. Es wird
kein laufendes Dateisystem eingefroren und kein Live-Snapshot als konsistent
ausgegeben.

**Als neue VM wiederherstellen** kopiert den gewählten Snapshot in eigene
qcow2-Dateien im ausgewählten Speicher. Die ursprüngliche VM, ihre aktuellen
Laufwerksinhalte und ihre Snapshots bleiben erhalten. Die neue VM verwendet eine
eigene UUID, neue MAC-Adressen und die zum Snapshot gehörenden UEFI-Variablen;
exklusive USB-/PCI-Geräte werden nicht übernommen. Sie bleibt ausgeschaltet.
Gast-IP und Rechnernamen vor dem ersten Start prüfen. Bei einem Kopierfehler
werden nur die neu angelegten Dateien bereinigt; das Original wird nie auf den
Snapshot zurückgesetzt.

Für eine laufende VM sind **Snapshot erstellen** und **Extern sichern** erreichbar.
Im jeweiligen Formular das geordnete Herunterfahren ausdrücklich bestätigen.
Titan wartet höchstens 120 Sekunden auf den ausgeschalteten Zustand und bricht
bei einem Timeout ab. Es erfolgt kein erzwungenes Ausschalten. Eine pausierte VM
zuerst fortsetzen oder im Gast herunterfahren. Nach der Sicherung bleibt die VM
ausgeschaltet.

Die Laufwerksanzahl kann nicht verändert werden, solange Snapshots vorhanden
sind. Zuerst diese Snapshots entfernen oder einen unabhängigen Klon anlegen.
Snapshots liegen intern in denselben qcow2-Dateien und schützen nicht vor dem
Ausfall des NAS-Laufwerks. Die externe VM-Archivierung erfasst alle verwalteten
Laufwerke, VM-XML und UEFI-Variablen gemeinsam. Ältere Sicherungen mit einem
Laufwerk bleiben lesbar. Die Wiederherstellung schreibt neue Dateien in den
gewählten VM-Speicher, erzeugt eine neue UUID und übernimmt keine fremden
Hostpfade oder exklusiven USB-/PCI-Geräte aus dem Archiv.

## Verifikation

`tests/test_vm_extensions.py` arbeitet mit echten `qemu-img`- und
`qemu-io`-Dateien. Es prüft Mehrdisk-Snapshot/Wiederherstellung, unabhängiges
Klonen, Rücknahme eines Fehlers auf dem zweiten Laufwerk, UEFI-Variablen,
Metadatenprüfung und Verweigerung laufender Änderungen. Die übrigen VM- und
Pakettests prüfen libvirt- und Docker-Verwaltung sowie Protokollschutz. Ein
echtes Gastbetriebssystem, Browser-Tastatur/Maus und physische Geräte bleiben
Teil des manuellen Betatests. `tests/test_vm_names.py` und die VM-Tests prüfen
Anzeigenamen ohne Änderungen an internen Kennungen. Die UI-Tests für Terminal,
Konsole, Desktoplinks und Admin-Login-Updateprüfung verwenden simulierte
Sitzungen; sie bestätigen keine echte Gast-Zwischenablage oder Tailnet-Verbindung.

Der GitHub-Workflow `App package runtime checks` wählt die Prüfungen passend
zum eingefrorenen Produktstand. Für aktuelle native Stände prüft er den
Cloudflare-Installer und eine unabhängige Compose-Laufzeitvorlage. Das ist kein
Nachweis einer echten Immich-, AdGuard- oder Tailscale-Kontoeinrichtung.
Die bisherigen Legacy-App-Prüfungen bleiben für ältere Produktstände erhalten.
Für Nextcloud/Office kann
`scripts/smoke-office-gateway.py` zusätzlich Titans echten HTTP-Gateway mit
temporären Dokumenten: Der laufende Dokumentserver lädt ein Dokument über die
Docker-Bridge, konvertiert es über seine [Conversion API](https://api.onlyoffice.com/docs/docs-api/additional-api/conversion-api/request/),
und ein signierter Callback schreibt das Ergebnis mit Revisionsprüfung zurück.
Der Test prüft zudem den JavaScript-/Dokumentproxy, erhaltene Dateirechte,
abgewiesene Signaturen und die Rückkonvertierung eines ODT-Originals. Dieser
Test ersetzt keinen manuellen Test der interaktiven Bearbeitung und
Zusammenarbeit im Browser.
