> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.2 · Alpha · uCore

**[Systemimage direkt herunterladen (.img.xz)](https://github.com/ra5on/Titan/releases/download/v0.4.2/titan-0.4.2-x86_64.img.xz)** · [Signaturen und Testergebnisse](https://github.com/ra5on/Titan/releases/tag/v0.4.2)

Die Update-Seite zeigt den live gelesenen uCore-Systemstatus: laufende, vorbereitete und vorherige Bereitstellung sowie den nächsten Start. Der Administrator kann eine signierte vorherige Titan-Version als Rollback vorbereiten und den notwendigen Neustart direkt im NAS bestätigen. Die Bestätigungen beziehen sich auf den angezeigten Digest; laufende VMs und inzwischen geänderte Systemstände blockieren den Neustart. Die automatische Updateprüfung startet den NAS weiterhin nicht selbst neu.

Auf einer neuen Installation ist noch keine vorherige Titan-Version vorhanden. Für den echten Update-/Rollback-Test braucht es anschließend ein neueres signiertes Release. Nutzdaten und Containerkonfigurationen unter `/var` bleiben beim OS-Rollback erhalten und werden dadurch nicht zurückgesetzt.

Apps lassen sich weiterhin mit den Standardeinstellungen installieren. Zusätzlich stehen im Installationsdialog Netzwerkauswahl und weitere Optionen zur Verfügung: Bridge, Host oder ein eigenes Bridge-Netz, eine feste Container-IPv4 in einem passenden eigenen Netz sowie ein wählbarer NAS-Webport für Bridge. Eigene Bridge-Netze können über Titan angelegt und bei ausbleibender Nutzung entfernt werden.

Bei einer installierten App erscheinen tatsächliche Containeradressen, Netzname, Gateway und veröffentlichte Zugriffsadressen. Eine Container-IP ist eine interne Docker-Adresse. LAN-Zugriff erfolgt bei Bridge über die veröffentlichten NAS-Ports; Host teilt das Netzwerk des NAS. Eine öffentliche Internet-IP wird nicht aus einer internen Adresse abgeleitet oder durch eine externe Abfrage ermittelt.

Virtuelle Maschinen können aus einem vorhandenen eigenständigen `.qcow2`, `.raw` oder `.img` angelegt werden. Die Quelle lässt sich per Dateiauswahl oder vollständigem Pfad angeben; Format und virtuelle Größe erscheinen vor dem Anlegen. Titan erstellt eine eigene VM-Disk als Kopie und behält die Quelldatei. Laufende VM-Laufwerke, symbolische Links, Backing-Dateien und externe qcow2-Datendateien werden nicht als Importquelle übernommen.

Der Dateimanager erhält eine Explorer-Ansicht mit Orten links, Breadcrumbs, Vor-/Zurück/oben, gespeicherter Listen-/Symbolansicht, Mehrfachauswahl und Sortierung der aktuellen Seite. Ein Zeilenklick zeigt Vorschau und Eigenschaften; Name, Enter oder Doppelklick öffnet. Neue Dateien verwenden getrennte Felder für Namen und Endung. Die vorhandenen Dateiaktionen und Rechte bleiben erhalten; Kopieren/Verschieben bieten eine Ordnerauswahl.

Der erste neu eingerichtete Administrator bekommt ein eigenes verwaltetes SMB-Konto mit dem gewählten Benutzernamen und Passwort. Bei älteren Installationen kann die bisherige Administratoridentität ohne SMB-Passwort durch eine bestätigte eigene Passwortänderung auf ein eigenes Konto umgestellt werden. Freigabe-Zugriffsadressen, Kontozuordnung und Dienststatus erscheinen in Titan. Benutzer ohne Freigabenrecht dürfen die private Freigabe weder öffnen noch in der SMB-Freigabenliste sehen.

Die Veröffentlichung enthält auf ausdrücklichen Wunsch wieder ein vollständiges Installations-IMG für die Proxmox-Test-VM. Reguläre Folgeversionen bleiben Updates ohne neuen Installationsdownload. ISO-Dateien werden nicht gebaut. Boot- und Laufzeitprüfungen bleiben Voraussetzung: Der Gasttest prüft neben dem bisherigen Standard-App-Ablauf ein eigenes Bridge-Netz mit fester Heimdall-IP, tatsächliche Adressen und HTTP vor/nach erneutem Start. Er prüft außerdem eine VM-Kopie aus einem direkten Image-Pfad und SMB mit getrennten Schreib-/Lese-/unberechtigten Konten vom externen entbehrlichen Runner aus. Live-Updatezustand und falsche Rollback-/Neustartbestätigungen werden ohne Neustart des Prüfgasts kontrolliert. Berichte enthalten nur feste Prüfergebnisse; Passwörter und rohe SMB-Ausgaben werden nicht veröffentlicht.

**Dieser Stand bleibt Alpha.** Der wirkliche Update-/Rollback-Zyklus in Proxmox, sämtliche App-Vorlagen, SMB-/Speicherabläufe, ein installiertes VM-Gastsystem und der Dauerbetrieb sind weiterhin eigene Beta-Nachweise.

[Proxmox-Test für Updates und App-Netze](https://github.com/ra5on/Titan/blob/main/docs/PROXMOX-TEST.md) · [Installation](https://github.com/ra5on/Titan/blob/main/docs/INSTALL.md) · [Beta-Kriterien](https://github.com/ra5on/Titan/blob/main/docs/BETA.md)
