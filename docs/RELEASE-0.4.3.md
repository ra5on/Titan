> Historical predecessor release notes; this is not a Titan release.

# Titan v0.4.3 · Alpha · uCore · Systemupdate

[Signaturen und Testergebnisse](https://github.com/ra5on/Titan/releases/tag/v0.4.3)

Titan nutzt freie Kapazität der Systemplatte jetzt über eine geprüfte Erweiterung der vorhandenen Systempartition und ihres XFS-Dateisystems. Bei jedem Start läuft die Prüfung vor den Titan-Diensten. Nach einer Vergrößerung der virtuellen Systemdisk kann der Administrator die Kapazität auch im laufenden NAS über **Speicher → Systemplatte → Kapazität erweitern** übernehmen. Eine bereits vollständig genutzte Disk bleibt unverändert.

Die Kachel **Systemplatte** unterscheidet gesamte Disk, Systempartition, Dateisystem und für Dateien verfügbaren Platz. Sie zeigt zusätzlichen Platz hinter der Partition und innerhalb der Partition getrennt an. Vor einer manuellen Erweiterung wird der aktuelle Zustand neu geladen; die Bestätigung lautet **ERWEITERN**. Ein inzwischen geändertes Layout wird zurückgewiesen.

Die Erweiterung unterstützt das unveränderte Titan-GPT-/XFS-Systemlayout. Sie erhält den Partitionsanfang und die Disk-/Partitions-/Dateisystem-UUIDs. Boot-/EFI-Partitionen werden nicht erweitert. LUKS, LVM, RAID, Multipath, zusätzliche Datenpartitionen und unbekannte Layouts bleiben gesperrt; die Oberfläche erklärt den Grund. Die Funktion formatiert keine Platte und bietet keine Auswahl fremder Geräte. Verkleinern ist nicht vorgesehen.

**v0.4.3 wird über den signierten Update-Kanal verteilt und enthält kein neues Installations-IMG.** Das bestehende [v0.4.2-IMG](https://github.com/ra5on/Titan/releases/download/v0.4.2/titan-0.4.2-x86_64.img.xz) bleibt unverändert. Nach dessen Installation zuerst v0.4.3 in Titan vorbereiten und den NAS ausdrücklich neu starten. Erst der gestartete v0.4.3-Stand enthält die automatische Erweiterung. Auch nach einer späteren Vergrößerung in Proxmox genügt beim unterstützten Layout ein Titan-Neustart oder die neue manuelle Aktion.

Der verpflichtende Image-Test vergrößert ausschließlich ein entbehrliches QCOW-Overlay vor dem Erststart auf 32 GiB. Danach wächst dieses Overlay über QMP auf 36 GiB; Titan muss die tatsächliche Partition und XFS um die zusätzliche Kapazität erweitern. Der Test verlangt unveränderte Layout-IDs, identische Testdatei-Inhalte einschließlich SHA256 und wirkungslose Wiederholungen bei bereits ausgenutztem Platz. Das originale Raw-Image muss seinen SHA256 behalten. Boot-, Wachstums- und bisherige SMB-/Docker-/VM-Prüfungen müssen bestanden sein, bevor die Veröffentlichung freigegeben wird.

**Veröffentlichungsnachweis:** v0.4.3 hat am **2. Oktober 2026** im [Actions-Lauf 36984481129](https://github.com/ra5on/Titan/actions/runs/36984481129) den Image-Erststart und alle **zehn Laufzeitprüfungen** bestanden. Der geprüfte Source-Stand ist [a792e96c16da](https://github.com/ra5on/Titan/commit/a792e96c16daf510492db93bafa4f30d0d6ebca6); der [öffentliche Laufzeitbericht](https://github.com/ra5on/Titan/releases/download/v0.4.3/runtime-test.json) enthält die tatsächlichen Ergebnisse. Die reale XFS-Größe wuchs von 32.747.008.000 auf 37.041.975.296 Bytes; Partitionsanfang, UUIDs, Testdatei-SHA256 und originales Raw-Image blieben erhalten. Die öffentlichen Manifest-/Prüfsummensignaturen und GitHub-Asset-Digests wurden nach Veröffentlichung unabhängig geprüft.

**Titan bleibt Alpha.** Dieser Gasttest ersetzt keinen manuellen Proxmox-Test, keinen vollständigen OS-Update-/Neustart-/Rollback-Zyklus und keinen Hardware-/Dauerlauf. Der Import eines vorhandenen VM-Images bleibt ein Kopieren der Quelle; ein installiertes Gastbetriebssystem und die Bedienung seiner Browserkonsole sind weiterhin eigene Beta-Nachweise.

[Proxmox-Test einschließlich Systemdisk](https://github.com/ra5on/Titan/blob/main/docs/PROXMOX-TEST.md) · [Installation](https://github.com/ra5on/Titan/blob/main/docs/INSTALL.md) · [Beta-Kriterien](https://github.com/ra5on/Titan/blob/main/docs/BETA.md)
