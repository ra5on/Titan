# Titan 0.8.0 · Alpha

Vorabversion mit neuer Oberfläche und neuen Speicher- und Gerätefunktionen. Sie
erscheint im Alpha-Kanal; Installationen im Stable-Kanal erhalten sie nicht als
Update.

## Neue Oberfläche

- Startseite ohne Fensterverwaltung: installierte Apps als Symbole, drei
  Live-Kacheln für CPU, RAM und Speicher, feste Navigation am unteren Rand.
- App Store mit Empfehlung, Kategorien, Suche und einer Detailseite. Vor der
  Installation wählst du Speicherort, Port und RAM-Profil; Titan prüft vorab,
  ob der Arbeitsspeicher reicht, und zeigt danach die echten Installationsschritte.
- Detailseite für installierte Apps mit Protokoll, Neustart, Aktualisieren und
  Deinstallieren.
- Dateimanager mit Upload-Fortschritt, Abbrechen, Download, Umbenennen und
  Papierkorb.
- Virtuelle Maschinen: Start, Herunterfahren, Neustart, Konsole, neue VM aus
  ISO oder vorhandener QCOW2-/IMG-Festplatte und ISO-Upload.
- Einstellungen: System (Neustart, Ausschalten, Meldungen), Speicher,
  Freigaben mit Rechten pro Benutzer, Benutzer, Gruppen und App-Rechte,
  Sicherungen, Docker-Ansicht, Web-Terminal, Updates und das eigene Passwort.

## Speicher und Sicherung

- **Ganze Systemplatte nutzen:** Der interne Speicher lässt sich in den
  Einstellungen auf die volle Größe des Installationslaufwerks erweitern und
  steht dann für Dateien, Apps und virtuelle Maschinen bereit.
- **Neue Speicherbereiche:** leere Laufwerke als Ext4, XFS oder Btrfs einrichten
  oder mehrere zu einem ZFS-Verbund zusammenfassen. Formatiert wird erst nach
  Eingabe des genauen Laufwerkspfads beziehungsweise Namens.
- **Btrfs** steht für einzelne Laufwerke bereit. Verbünde aus mehreren Platten
  laufen weiterhin über ZFS.
- **USB-Laufwerke** werden beim Anstecken eingebunden (Ext4, XFS, Btrfs, FAT,
  exFAT, NTFS), erscheinen für Administratoren unter „Dateien“ und lassen sich
  als Sicherungsziel wählen. „Auswerfen“ hängt das Laufwerk sauber aus.
- **Sicherungen:** Ziel auf einer anderen Platte, Auswahl der Freigaben,
  Zeitplan, „Jetzt sichern“, Prüfen und Wiederherstellen in einen neuen Ordner.
- **Laufender Abgleich:** hält eine Freigabe im Minuten- bis Tagesrhythmus als
  Kopie auf einer zweiten Platte. Gelöschte Dateien bleiben im Ziel, sofern das
  Mitlöschen nicht ausdrücklich eingeschaltet ist. Ein Abgleich ersetzt keine
  Sicherung.
- **Speicherkontingent pro Benutzer** für Freigaben auf ZFS-Verbünden.

## Geräte durchreichen

- **Apps:** Grafikkarte (Intel und AMD über den Kerneltreiber, NVIDIA bei
  installiertem Treiber), KI-Beschleuniger und USB-Geräte pro App auswählen.
- **Virtuelle Maschinen:** USB-Geräte sowie Grafikkarten und Beschleuniger als
  ganzes PCI-Gerät durchreichen. Angeboten wird ein Gerät nur, wenn seine
  gesamte IOMMU-Gruppe mitgehen kann; die übrigen Funktionen derselben Karte
  werden automatisch mitgegeben. Voraussetzung ist aktiviertes VT-d
  beziehungsweise AMD-Vi im BIOS/UEFI.

## Lizenz

Der eigene Titan-Code steht ab dieser Version unter der
[PolyForm Noncommercial License 1.0.0](../LICENSE). Einzelheiten stehen in
[LICENSING.md](LICENSING.md).

## Unverändert

Agent-API und Datenbankschema bleiben kompatibel zu 0.7.0; neue Funktionen sind
zusätzliche Operationen. Die bisherige Oberfläche ist unter `/classic`
erreichbar. Dort liegen weiterhin Zwei-Faktor-Einrichtung und Anmeldeschutz,
Webzugriff (Ports, HTTPS), Benachrichtigungen, Plattentausch, Prüfläufe und
Snapshots, eigene Container, App-Sicherungen und die erweiterte VM-Verwaltung
(Snapshots, Netzwerke, zusätzliche Datenträger). Die eigene Fotos-Anwendung wird
nicht übernommen; für Fotos ist Immich aus dem App Store vorgesehen.

## Grenzen

- Automatisch geprüft sind alle Bereiche der neuen Oberfläche im Browser gegen
  die Demo sowie die neuen Systemfunktionen mit Unit-Tests.
- **Noch nicht auf echter Hardware geprüft:** USB-Laufwerke, laufender Abgleich,
  Btrfs-Laufwerke, PCI- und GPU-Durchreichen an VMs sowie Grafikkarten für Apps.
  Vor dem Einsatz mit wichtigen Daten auf dem eigenen System ausprobieren.
- Anmeldung, Ersteinrichtung und eine App-Installation über die neue Oberfläche
  sind bisher nur auf dem Alpha-Image von Hand zu prüfen.
- Der NVIDIA-Treiber ist nicht im Image enthalten. NVIDIA-Karten lassen sich an
  eine VM durchreichen; für Apps fehlt der Treiber noch.
- Kontingente gibt es nur auf ZFS, Btrfs nur für einzelne Laufwerke.
- Der Systemdienst vertraut weiterhin der Webanwendung; die getrennte Prüfung
  für Root-Aktionen im Systemdienst ist geplant.
