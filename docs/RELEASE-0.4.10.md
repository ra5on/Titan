# Titan 0.4.10-alpha.1 · VM-Einstellungen und anpassbares Hauptmenü

Systemupdate im Alpha-Kanal unter **Einstellungen → Updates & Rollback**. Version vorbereiten und den Neustart bestätigen. Kein neues Image erforderlich.

- Ein gelöschter VM-Name kann wieder genutzt werden. Behaltene Laufwerke und UEFI-Variablen werden nicht überschrieben; bei Namenskollisionen bekommt die neue Instanz eigene interne Dateinamen. Die alten Dateien bleiben am bisherigen Ort und können über den Dateimanager oder Image-Import weiterverwendet werden. Aktive Namen bleiben gesperrt.
- Starten/Herunterfahren, Neustart, Einstellungen und Konsole sind zustandsabhängig direkt sichtbar. **Weitere Aktionen & Details** führt deutlich sichtbar zu USB, Medien, Sicherungen und weiteren Aktionen.
- BIOS und UEFI bei ausgeschalteter VM wechseln, Bootreihenfolge Festplatte/CD/DVD/Netzwerk ändern. Der Wechsel behält Laufwerk, UUID, Controller und vorhandene UEFI-Variablen. Er konvertiert kein Gastsystem: Das Betriebssystem muss den gewählten Startmodus unterstützen. Secure Boot bleibt deaktiviert.
- Vorhandene libvirt-Netze (NAT, isoliert, geroutet), bestehende Bridges, direkte macvtap-Anbindung oder keine Netzwerkkarte auswählen. VirtIO/E1000, eigene Unicast-MAC-Adresse und verbundenes/getrenntes Netzwerkkabel einstellen. Änderungen benötigen eine ausgeschaltete VM. Die NAS-Uplink-Konfiguration wird nicht verändert; neue Host-Bridges werden hier nicht angelegt. MAC-Doppelungen mit anderen VMs werden abgelehnt.
- Macvtap gibt der VM eine eigene LAN-Anbindung; direkter NAS-zu-Gast-Verkehr ist dabei eingeschränkt. Einen Docker-Hostmodus gibt es für diese VM-Anbindungen nicht. IP-Adressen werden im Gastsystem beziehungsweise per DHCP eingestellt.
- Hauptmenü mit installierten Docker-Apps: **Anordnen**, Icons ziehen, mit Pfeilen verschieben oder einer Ordner-Auswahl zuweisen. Mittiges Ablegen auf einer App gruppiert sie in einem Ordner. Ordner öffnen, umbenennen und auflösen. Eine Ordnerebene; Positionen und Gruppen werden pro Webkonto auf dem NAS gespeichert und nach Neuladen wiederhergestellt. Mobile Bedienung über Griff, Pfeile und Auswahl.

Die Veröffentlichung bleibt an Regressionstests, tatsächlichen Systemstart, VM/VNC-Laufzeit, Update vom veröffentlichten 0.4.6-Image sowie Rollback und Fehlstart-Rückfall gebunden. Der VM-Test prüft zusätzlich Firmwarewechsel, Start an einer vorhandenen Bridge und erneute Erstellung mit gleichem Namen ohne Änderung des alten Laufwerks. Reale macvtap-LAN-Anbindung, Gastbetriebssystem-Konvertierung und physische Netzwerkhardware sind nicht Teil des automatisierten Tests.

Technische Grundlagen: [libvirt-Domain-XML](https://www.libvirt.org/formatdomain.html#network-interfaces) und [Firmware-Auswahl](https://www.libvirt.org/formatdomain.html#bios-bootloader).

Titan bleibt Alpha. Betriebssystem-Rollback setzt Nutzdaten, Apps und Menü-Einstellungen nicht zurück. Ältere Versionen können neuere VM-Instanzdateinamen nicht verwalten; die VM-Dateien bleiben erhalten und sind nach Rückkehr zur neuen Version wieder verwaltbar.
