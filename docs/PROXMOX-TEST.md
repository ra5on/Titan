# Titan in Proxmox testen

Dieser Test verwendet eine eigene Titan-VM und entbehrliche Testdaten. Das [v0.4.2-IMG](https://github.com/ra5on/Titan/releases/download/v0.4.2/titan-0.4.2-x86_64.img.xz) enthält uCore-HCI und Titan einschließlich der neuen Update-/Rollback-Bedienung. Prüfsummen und Signaturen vor dem Import nach [Installation](INSTALL.md#download-und-datenträger) prüfen. Ein Testergebnis gehört immer zur gestarteten Version und zum OCI-Digest.

v0.4.3 ergänzt die automatische und manuelle Erweiterung der Systemdisk als signiertes Update. Dafür wird kein neues Installations-IMG gebaut. Die v0.4.2-Startbasis muss zuerst über Titan auf v0.4.3 aktualisiert und ausdrücklich neu gestartet werden; erst danach ist die neue Erweiterungsfunktion vorhanden.

## VM und erster Start

1. Das geprüfte `.img.xz` entpacken und als neue Systemdisk einer neuen VM importieren. UEFI/OVMF, eigene EFI-Disk, Q35, VirtIO-Disk, mindestens 4 GiB RAM und zwei CPUs sowie eine LAN-Bridge verwenden. Die Systemdisk muss die entpackte IMG-Größe behalten; für App-Daten zusätzliche Kapazität einplanen.
2. Für Gast-VMs innerhalb von Titan zusätzlich Nested-KVM auf dem Proxmox-Host und CPU-Typ `host` bereitstellen. Ohne KVM bleibt der NAS-Webzugang benutzbar; Gast-VM-Tests dann als übersprungen dokumentieren.
3. Titan starten, DHCP-Adresse ermitteln und `https://IP:5000` öffnen. Administrator anlegen, abmelden und wieder anmelden. In „Updates“ Version, gestarteten Digest und Systemstatus festhalten.
4. Auf einer frischen Installation muss die Oberfläche erklären, dass noch keine vorherige Version für einen Rollback existiert. Das ist der erwartete Zustand. Nach einem normalen Neustart erneut anmelden und Konfiguration, Apps und Dateien überprüfen.

Die [offizielle Proxmox-qm-Dokumentation](https://github.com/proxmox/pve-docs/blob/master/generated/qm.1-synopsis.adoc) beschreibt Diskimport und VM-Optionen. Die Web-Anmeldung richtet keinen Linux-Konsolenbenutzer ein. Bei nicht erreichbarer Oberfläche sichtbare Bootmeldungen mit Version und IP festhalten; weitere Diagnose steht in [Installation](INSTALL.md#diagnose).

## Systemdisk ab v0.4.3 erweitern

1. Der Titan-Test-VM eine Systemdisk zuweisen, die größer als das entpackte v0.4.2-IMG ist, beispielsweise 60 GiB. Version v0.4.3 über Titan vorbereiten, laufende Gast-VMs geordnet ausschalten und den NAS-Neustart bestätigen. Beim ersten Start dieses neuen OS-Stands muss die automatische Erweiterung den freien Endbereich übernehmen.
2. Unter **Speicher → Systemplatte** gesamte Disk, Systempartition, Dateisystem und **Für Dateien verfügbar** festhalten. Disk und Dateisystem müssen plausibel zur gewählten Größe passen. Boot-/EFI-Platz, GPT-Ausrichtung und XFS-Metadaten erklären einen kleinen Unterschied; die Dateisystemgröße soll nicht exakt der gesamten Diskgröße entsprechen. Keine zusätzliche Kapazität darf mehr zur Erweiterung angeboten werden.
3. Über den Dateimanager eine eigene kleine Testdatei unter `/var/tmp` erstellen, herunterladen und SHA256 auf dem Testclient festhalten. Bestehende Test-App-Konfiguration und Zugriffe ebenfalls dokumentieren. Keine produktiven Daten verwenden.
4. In Proxmox ausschließlich die richtige **Systemdisk dieser Titan-Test-VM** beispielsweise von 60 auf 80 GiB vergrößern. Daten- oder EFI-Disks nicht auswählen. Im laufenden Titan **Status aktualisieren** wählen. Sobald die neue Diskgröße sichtbar ist, muss die Kachel zusätzlichen nutzbaren Platz anzeigen. Falls der virtuelle Controller die neue Größe erst nach einem Neustart meldet, Titan kontrolliert neu starten; dann übernimmt die automatische Startprüfung die Erweiterung.
5. Wenn Titan die größere Disk im laufenden Betrieb erkennt, **Kapazität erweitern** wählen und im Dialog **Systemkapazität erweitern** mit **ERWEITERN** bestätigen. Der Auftrag muss sowohl Partition als auch XFS vergrößern. Danach Status erneut prüfen: etwa 20 GiB zusätzliche Dateisystemkapazität bei diesem Beispiel; bereits belegte Daten bleiben erhalten.
6. Testdatei erneut herunterladen und SHA256 vergleichen. App-Zugriff, Anmeldung und Freigaben prüfen; danach einmal vollständig neu starten und diese Prüfungen wiederholen. Bei bereits vollständig genutztem Platz darf eine Wiederholung keine weitere Änderung auslösen. Anschließend nur die eigene Testdatei entfernen.
7. Unbekannte oder zusammengesetzte Systemlayouts werden verständlich gesperrt. Solche Fehlerfälle nur mit separaten entbehrlichen VMs prüfen. Titan darf hier keine fremde Disk oder Boot-/EFI-Partition formatieren, verschieben oder erweitern.

Der automatische CI-Nachweis verwendet eine getrennte QEMU-Testdisk und ersetzt diese Proxmox-/Persistenzprüfung nicht. Systemdisk-Wachstum ist auch kein OS-Rollback: Eine größere Partition und Daten unter `/var` werden durch den Wechsel zur vorherigen Titan-Version nicht zurückgesetzt.

## App installieren und ihre Adressen prüfen

1. Zunächst eine einfache App wie Heimdall mit **Standard** installieren. Webseite öffnen, ersten Zugang aus dem App Store prüfen, stoppen/starten und nach einem NAS-Neustart erneut öffnen. Die Container-IP und die LAN-Zugriffsadresse in den App-Informationen vergleichen.
2. Die Test-App entfernen. Ihre Konfiguration bleibt dabei erhalten. Über den Installationsdialog ein **eigenes Bridge-Netz** mit einem freien privaten Subnetz und Gateway anlegen. Beispiel `172.30.241.0/24`, Gateway `172.30.241.1`; vorher prüfen, dass dieses Netz weder LAN/VPN noch vorhandene Docker-Netze überlappt.
3. App in diesem Netz mit fester IP, beispielsweise `172.30.241.10`, installieren. Einen freien veröffentlichten NAS-Port wählen. App-Informationen müssen den gewählten Netznamen, die tatsächlich zugewiesene Container-IP, Gateway und LAN-Zugriffsadresse zeigen. Webseite über den NAS-Port öffnen.
4. App stoppen/starten und NAS neu starten. Feste IP, Netzzuordnung, Zugriff und Konfiguration müssen erhalten bleiben. Das benutzte Netz darf sich nicht löschen lassen. Erst App entfernen, dann das freie Testnetz entfernen.
5. Falsche IP, Gateway-/Netzadresse als Container-IP, belegte IP, überlappendes Subnetz und einen reservierten oder belegten NAS-Port ausprobieren. Eine klare Fehlermeldung muss erscheinen; bestehende Apps müssen weiter funktionieren.
6. **Host** getrennt mit einer passenden Test-App ausprobieren: Sie benutzt NAS-Adressen und ihre eigenen Dienstports. Frei eingetragene Portweiterleitungen und eine eigene Container-IP gelten hier nicht. Die angezeigten Host-Zugriffsadressen gegen die tatsächliche App-Webseite prüfen. Anwendungen mit Port 80/443 können Konflikte mit anderen Host-Diensten verursachen; keine produktiven Dienste für den Test abschalten.

Eine Bridge-IP ist intern. Andere LAN-Geräte verwenden normalerweise die veröffentlichten NAS-Ports; Host teilt den Netzwerkraum des NAS. Eine öffentliche Internetadresse kann Titan hinter einem Router nicht allein aus Docker ableiten. Das wird als nicht ermittelt angezeigt. Diese Unterschiede beschreibt Docker für [Bridge](https://docs.docker.com/engine/network/drivers/bridge/) und [Host](https://docs.docker.com/engine/network/drivers/host/). Ein eigenes Bridge-Netz gibt einer App keine eigene DHCP-Adresse im physischen LAN.

## Dateimanager, vorhandene VM-Images und SMB

1. Im Dateimanager über die Orte und Breadcrumbs navigieren; Vor-/Zurück/oben und gespeicherte Listen-/Symbolansicht prüfen. Ein Zeilenklick zeigt Vorschau/Eigenschaften, Name/Enter/Doppelklick öffnet. Neue Datei mit getrenntem Namen und Endung erstellen, mehrere Einträge auswählen und vorhandene Kopier-/Verschiebe-/Papierkorbaktionen prüfen. Ordnerauswahl soll die Eingabe eines Zielpfads ersetzen. Sortierung gilt für die aktuelle Seite.
2. Eine eigene entbehrliche `.qcow2`, `.raw` oder `.img` bereitstellen und Inhalt beziehungsweise SHA256 festhalten. Beim Erstellen einer VM diese Quelle über die Dateiauswahl beziehungsweise mit ihrem vollständigen tatsächlichen Pfad wählen. Format und virtuelle Größe müssen erscheinen; die neue Disk darf nicht kleiner sein. Titan kopiert die Quelle in den ausgewählten verwalteten VM-Speicher. Danach Quellhash vergleichen, die neue VM starten und ihren eigenen Datenzustand prüfen.
3. Nur eigenständige Images ohne Backing-Dateien, Verschlüsselung oder externe Datendateien verwenden. Quelle und Pfad dürfen keine symbolischen Links enthalten. Ein gerade von einer laufenden VM benutztes Image muss beim Import blockiert werden; die VM vorher vollständig ausschalten. Das vergrößerte Laufwerk vergrößert Partitionen und Dateisysteme im Gast nicht automatisch.
4. Neu eingerichteter Administrator: SMB-Anmeldung mit demselben Benutzernamen und dem gewählten Passwort ausprobieren. Weitere Lese- und Schreibkonten erstellen, eine private Testfreigabe anlegen und die in Titan angezeigte Zugriffsadresse auf einem separaten Windows-/macOS-/Linux-Client öffnen. Schreibkonto muss schreiben/lesen, Lesekonto nur lesen können; Konto ohne Rechte darf die Freigabe nicht öffnen und nicht in der SMB-Freigabenliste sehen.
5. Beim Update einer älteren Installation kann das alte Administratorkonto noch die Dienstidentität ohne eigenen SMB-Zugang verwenden. Eigene Passwortänderung mit verifiziertem bisherigen Passwort durchführen und den angezeigten neuen SMB-Benutzernamen prüfen. Freigabenrechte anschließend erneut testen. Ein neues Image braucht diesen Migrationsschritt nicht.
6. Nach NAS-Neustart Datei-, VM- und SMB-Zuordnungen erneut kontrollieren. Bei Fehlern Web-Anmeldung und SMB-Anmeldung getrennt beschreiben; Betriebssystem, Benutzerrolle, Freigabe und genaue Meldung nennen.

## Update und Rollback wirklich ausführen

**Voraussetzung:** Das neuere signierte [v0.4.3-Alpha-Release](https://github.com/ra5on/Titan/releases/tag/v0.4.3) ist jetzt für eine v0.4.2-Installation verfügbar. Den Alpha-Kanal wählen; der folgende Test prüft v0.4.2→v0.4.3→v0.4.2. Der automatische Gasttest hat diesen vollständigen Zyklus noch nicht ausgeführt.

1. Kleine Testdatei, Freigabe und App-Konfiguration erstellen; Inhalt/Hash und Zugriffsrechte festhalten. Vor dem Test eine separate Sicherung beziehungsweise einen Proxmox-Snapshot der ausgeschalteten Test-VM anlegen. Der Snapshot ersetzt den Titan-Rollback-Test nicht.
2. In „Updates“ den Alpha-Kanal wählen, prüfen und das neuere angebotene signierte Systemimage vorbereiten. Den Auftrag bis zum Erfolg verfolgen. Die laufende Version muss unverändert bleiben; „Neustart erforderlich“ und die vorbereitete Version beziehungsweise ihr Digest müssen erscheinen. Kein automatischer Neustart darf erfolgen.
3. Eine laufende Gast-VM muss den Neustart in Titan blockieren. Gast-VM und Apps geordnet beenden, den geplanten Systemstand prüfen und den Neustartdialog ausdrücklich bestätigen. Kurz vor dem Neustart ist ein Verbindungsabbruch zu erwarten; nach erneutem Start dieselbe NAS-Adresse öffnen und anmelden.
4. Neue laufende Version und Digest prüfen. Die vorherige Bereitstellung muss jetzt sichtbar sein. Dateiinhalt, Rechte, Freigabe und App-Konfiguration erneut vergleichen. Eine Auswirkung auf persistente Daten ist unabhängig von der OS-Version zu bewerten.
5. Die angezeigte vorherige Titan-Version als Rollback vorbereiten und im Dialog `ROLLBACK` bestätigen. Erfolgreichen Auftrag und nächsten Systemstart prüfen. Wieder VMs/Apps geordnet beenden und den Neustart mit `NEUSTART` bestätigen.
6. Nach erneutem Start muss die frühere OS-Version laufen. Dateiinhalt, Rechte, Freigabe, App-Konfiguration und Anmeldung erneut vergleichen. `/var` wird durch den OS-Rollback nicht auf einen früheren Datenstand zurückgestellt; `/etc` folgt dagegen der früheren Bereitstellung. Insbesondere nach dem Update geänderte Freigaben/Systemkonfiguration und die Kompatibilität der Titan-Datenbank kontrollieren.
7. Fehlerfälle separat prüfen: falsche Bestätigung, inzwischen anderer Digest, schon vorbereitete Version und bereits geplanter Neustart. Die Oberfläche darf den Zustand nicht still überschreiben und keinen zweiten Neustart planen. Alpha-/Beta-/Stable-Wechsel dürfen keine ältere Version installieren.

Der automatische Image-Gasttest bestätigt Live-Status, keine vorherige Bereitstellung beim Erststart und die Ablehnung falscher Bestätigungen. Er führt diesen echten Mehrstart-Zyklus nicht aus. Erst dokumentierte Beobachtungen aus Proxmox zählen hier als Betriebsnachweis.

## Fehler zurückmelden

```text
Titan-Version / gestarteter OCI-Digest:
Datum / Proxmox-Version / CPU-Typ / RAM / Netzwerk:
Seite und Aktion:
Erwartet:
Beobachtet / genaue Fehlermeldung:
Auftragsstatus:
Reproduzierbare Schritte:
Status: bestanden | fehlgeschlagen | übersprungen | offen
```

Bei Problemen zuerst Version, betroffene Seite und Meldung aus dem Auftrag nennen. Keine Passwörter, App-API-Schlüssel oder persönliche Daten in Screenshots/Protokollen veröffentlichen. Die weiteren SMB-, Speicher-, Backup-, VM- und Dauerlauftests stehen im [allgemeinen Testplan](TESTING.md); die [Beta-Kriterien](BETA.md) bleiben gültig.
