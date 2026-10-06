# Titan in Proxmox testen

Eine separate VM und entbehrliche Daten verwenden. Das aktuelle [Installationsimage](TITAN-IMAGE.md) benötigt UEFI/OVMF; Secure Boot bleibt zunächst deaktiviert. CPU-Typ `host` und verschachtelte Virtualisierung werden für VMs innerhalb von Titan benötigt.

1. Image importieren, starten, angezeigte HTTPS-Adresse auf Port 5000 öffnen und Administrator anlegen.
2. Unter Einstellungen → Updates & Rollback den Alpha-Kanal speichern und nach Updates suchen.
3. Vor dem Update Testdateien mit Prüfsummen, Benutzer und Freigaben anlegen. App- und VM-Daten notieren.
4. Systemimage vorbereiten. Downloadwerte, Signaturprüfung, Schreiben und Bereitschaft müssen nachvollziehbar sein. Neustart ausdrücklich bestätigen.
5. Nach dem Start Version, Anmeldung, SMB-Rechte und Testdaten prüfen. Rollback im Dropdown auswählen, vorbereiten und erneut starten. Daten danach erneut vergleichen.
6. Virtuelle Systemdisk vergrößern. Nach Neustart muss der Datenbereich die zusätzliche Kapazität nutzen; beide Systemslots behalten ihre feste Größe. Testdateien erneut prüfen.
7. RAM im Dashboard mit `free -b` und `/proc/meminfo` vergleichen. „Belegt inklusive Cache“ entspricht MemTotal minus MemFree; „Bedarf“ entspricht MemTotal minus MemAvailable. Proxmox kann zusätzlich VM-Hostaufwand erfassen.
8. Im Browser Seite wechseln, während eine Aktion läuft. Status muss unter Aktivität und im zugehörigen Bereich erreichbar bleiben. Fehlerdetails müssen nach einem Fehlschlag erhalten bleiben.

Version, VM-Konfiguration und konkrete Fehlertexte beim Testergebnis angeben. Rollback ersetzt keine Datensicherung.
