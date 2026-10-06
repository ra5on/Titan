# Titan 0.4.9-alpha.1 · UEFI, integrierte Konsole und AppStores

Signiertes Debian-A/B-Systemupdate. Bestehende Titan-Installationen verwenden den **Alpha-Kanal** unter **Einstellungen → Updates & Rollback**. Nach Updates suchen, Version vorbereiten und anschließend den Neustart bestätigen. Die Oberfläche zeigt danach **0.4.9**. Kein neues IMG erforderlich.

## Änderungen

- Neue VMs bieten BIOS oder UEFI (Q35/OVMF, ohne Secure Boot). Vorhandene VMs behalten ihren Bootmodus. UEFI-Variablen bleiben bei VM-Entfernung erhalten und werden bei VM-Sicherung/Wiederherstellung mitgesichert, sofern bereits vorhanden. Ein belegter UEFI-Name wird nicht überschrieben.
- VNC-Konsole innerhalb der Titan-Oberfläche, mit bildschirmfüllendem Dialog auf Mobilgeräten. Schließen trennt die Verbindung. Die bereits bestehende Authentifizierung gilt weiterhin.
- Mobile Formulare, Manager-Navigation, Store-Auswahl, Bedienelemente und Umbrüche verbessert. Dashboard-Untertitel und Proxmox-Erklärung entfernt.
- LinuxServer.io ist der Standardstore mit 73 gebündelten Vorlagen und einer Aktualisierungsfunktion über die offizielle API. Katalog bleibt offline nutzbar. Standardports sind voneinander verschieden; Port, Datenfreigabe und Netzwerk sind vor Installation einstellbar.
- Mehrere Stores aktivieren/deaktivieren und nach Store filtern. Bekannte Quellen: CasaOS/IceWhale, BigBear und LinuxServer-Community. Titan-JSON, CasaOS-GitHub-Repositories und begrenzte GitHub-ZIP-Archive werden eingelesen. Große Repository-Bilder werden beim gezielten Import nicht geladen.
- Kompatible Einzelcontainer werden in Titan-Vorlagen übersetzt. Besondere Hostrechte, Geräte, mehrere Container oder mehrere erforderliche Datenziele werden nicht stillschweigend ausgelassen; ungeeignete Vorlagen erscheinen mit Grund. Installierte Apps bleiben beim Deaktivieren steuerbar.
- Die 42 bisherigen Vorlagen behalten ihre geprüften Anmeldehinweise. Bei automatisch importierten Vorlagen ohne geprüften Standardzugang zeigt Titan dies ausdrücklich und verlinkt direkt die Herausgeber-Anleitung. Es werden keine Standardpasswörter erfunden.

## Prüfung und Grenzen

Freigabe erfolgt erst nach Regressionstests, tatsächlichem Image-Start, NAS-Laufzeittests sowie Update vom veröffentlichten 0.4.6-Image, Rollback und Fehler-Rückfall. `runtime-test.json` und `ab-test.json` dokumentieren die tatsächlich ausgeführten Prüfungen. Die VM-Laufzeitprüfung erstellt eine UEFI-VM und eine BIOS-Image-Kopie, startet und stoppt beide und prüft den authentifizierten VNC-Transport. Ein installierter Gastbetriebssystem-Boot wird damit nicht behauptet.

Die Oberfläche wurde bei 390 Pixeln geprüft. Store-Import wurde an den öffentlichen Quellen geprüft; sämtliche externen Apps wurden nicht einzeln installiert und gestartet. Ein erfolgreicher Vorlagenimport ist keine Zusicherung, dass jede App ohne weitere appinterne Einrichtung funktioniert. Multi-Container-Stacks und zusätzliche Geräteanforderungen bleiben außerhalb dieses Importformats.

Titan bleibt Alpha. Rollback wechselt das Betriebssystem, nicht Nutzdaten oder App-Datenbanken. Neuinstallationen können weiterhin das [0.4.6-IMG](https://github.com/ra5on/Titan/releases/download/v0.4.6-alpha.1/titan-0.4.6-alpha.1-amd64.img.xz) verwenden und anschließend über Alpha aktualisieren.

Neue Store-Quellen werden getrennt vom bisherigen Titan-JSON-Katalog gespeichert, damit ältere Verwaltungsdienste nach einem Rollback weiter starten. Apps und UEFI-VMs, die erstmals mit neuen Funktionen eingerichtet wurden, können für ihre Verwaltung beziehungsweise Firmware die neuere Systemversion benötigen; ein Betriebssystem-Rollback konvertiert deren Konfigurationen nicht zurück.
