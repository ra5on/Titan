# Titan 0.8.0 · Beta

Vorabversion mit neuer Oberfläche und neuen Speicher- und Gerätefunktionen. Sie
erscheint im Beta-Kanal; Installationen im Stable-Kanal erhalten sie nicht als
Update.

## Neue Oberfläche

- Startseite ohne Fensterverwaltung: installierte Apps als Symbole, drei
  Live-Kacheln für CPU, RAM und Speicher, feste Navigation am unteren Rand und
  oben links das Systemmenü mit Abmelden, Neustart und Ausschalten, jeweils
  mit Rückfrage.
- **Apps öffnen im Titan-Fenster** statt in einem neuen Browser-Tab; „Neuer
  Tab“ bleibt als Ausweg. Die Konsole einer virtuellen Maschine erscheint
  ebenfalls innerhalb von Titan.
- App Store mit Empfehlung, Kategorien, Suche und einer Detailseite. Vor der
  Installation wählst du Speicherort, Port und RAM-Profil; Titan prüft vorab,
  ob der Arbeitsspeicher reicht, und zeigt danach die echten Installationsschritte.
- Detailseite für installierte Apps mit Protokoll, Neustart, Aktualisieren und
  Deinstallieren. Port und weitere Einstellungen einer gestoppten App lassen
  sich dort nachträglich ändern; Titan legt die Container dabei aus der neuen
  Konfiguration neu an.
- **Neu im App Store:** Ollama mit Open WebUI für lokale Sprachmodelle, Pi-hole
  sowie Nextcloud mit Euro-Office. Alle Apps des Stores werden bei jeder
  Prüfung mit echtem Docker installiert.
- **Tailscale** kann das NAS zusätzlich als Exit Node anbieten. Die Auswahl
  wird nach jedem Start auf den laufenden Dienst angewendet, auch wenn sie
  erst nach der Installation geändert wurde.
- Dateimanager mit Upload-Fortschritt, Abbrechen, Download, Umbenennen und
  Papierkorb.
- Virtuelle Maschinen: Start, Herunterfahren, Neustart, Konsole, neue VM aus
  ISO oder vorhandener QCOW2-/IMG-Festplatte und ISO-Upload.
- Einstellungen: System (Neustart, Ausschalten, Meldungen), Speicher,
  Freigaben mit Rechten pro Benutzer, Benutzer, Gruppen und App-Rechte,
  Sicherungen, Fernzugriff, Docker-Ansicht, Web-Terminal, Updates und das
  eigene Passwort.
- **Darstellung pro Konto:** Transparenz per Schieberegler, Dock-Größe und
  Dock-Einträge (Werkzeuge, Apps, virtuelle Maschinen) sowie Kacheln, Apps und
  virtuelle Maschinen der Startseite.

## Speicher und Sicherung

- **Ganze Systemplatte nutzen:** Der interne Speicher lässt sich in den
  Einstellungen auf die volle Größe des Installationslaufwerks erweitern und
  steht dann für Dateien, Apps und virtuelle Maschinen bereit.
- **Neue Speicherbereiche:** leere Laufwerke als Ext4, XFS oder Btrfs einrichten
  oder mehrere zu einem ZFS-Verbund zusammenfassen. Formatiert wird erst nach
  Eingabe des genauen Laufwerkspfads beziehungsweise Namens.
- **Btrfs-Spiegel:** Zwei bis vier Laufwerke lassen sich zu einem Btrfs-Verbund
  zusammenfassen, der alles doppelt speichert; ein Laufwerk darf ausfallen.
  Unter Einstellungen → Speicher ersetzt „Laufwerk ersetzen“ ein fehlendes oder
  ein noch vorhandenes, fehlerhaftes Laufwerk, während die Daten erreichbar
  bleiben. Fehlt ein Laufwerk, hängt Titan den Verbund nicht stillschweigend
  mit nur einer Kopie ein, sondern erst mit dem bestätigten Austausch. Einmal
  im Monat liest Btrfs alle Daten und repariert stille Fehler aus der zweiten
  Kopie.
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

- **Apps:** Grafikkarte, KI-Beschleuniger und USB-Geräte pro App auswählen.
  Intel und AMD laufen mit den Kerneltreibern.
- **NVIDIA-Treiber auf Knopfdruck:** Unter Einstellungen → System installiert
  Titan den Treiber aus dem Paketarchiv von NVIDIA (offene Kernelmodule, auch
  für die RTX-50-Serie) samt Container-Laufzeit für Docker. Das Image selbst
  enthält den proprietären Treiber nicht. Nach einem Systemupdate baut Titan
  ihn im Hintergrund neu; dafür braucht das NAS Internet.
- **Virtuelle Maschinen:** USB-Geräte sowie Grafikkarten und Beschleuniger als
  ganzes PCI-Gerät durchreichen. Angeboten wird ein Gerät nur, wenn seine
  gesamte IOMMU-Gruppe mitgehen kann; die übrigen Funktionen derselben Karte
  werden automatisch mitgegeben. Voraussetzung ist aktiviertes VT-d
  beziehungsweise AMD-Vi im BIOS/UEFI; neue Installationen starten den Kernel
  mit eingeschaltetem IOMMU.

## Sicherheit

Root-Terminal und Root-Dateizugriff brauchen jetzt eine eigene Freigabe des
Systemdienstes. Er prüft dafür das Administrator-Passwort selbst gegen den
gespeicherten Hash, begrenzt die Freigabe auf höchstens 30 Minuten und bremst
Fehlversuche. Die Webanwendung allein kann keine Root-Aktion mehr auslösen.

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
  PCI- und GPU-Durchreichen an VMs sowie Grafikkarten für Apps.
  Vor dem Einsatz mit wichtigen Daten auf dem eigenen System ausprobieren.
- Btrfs-Laufwerke und der Btrfs-Spiegel samt Plattenausfall und Austausch
  laufen bei jeder Änderung mit dem echten Kernel und den echten
  Btrfs-Werkzeugen auf Testlaufwerken durch, aber noch nicht auf echten
  Festplatten. Ein Spiegel ersetzt keine Sicherung.
- Anmeldung, Ersteinrichtung und eine App-Installation über die neue Oberfläche
  sind bisher nur auf einem installierten Image von Hand zu prüfen.
- Apps im Titan-Fenster: Läuft Titan verschlüsselt (HTTPS) und die App
  unverschlüsselt, zeigen Browser sie nicht eingebettet an; manche Apps
  verbieten das Einbetten grundsätzlich. Von unterwegs erscheint eine App nur
  im Fenster, wenn im Fernzugriff eine öffentliche Adresse für sie eingerichtet
  ist. Ein Zugang zu allen Apps über die eine Titan-Adresse ist noch nicht
  enthalten.
- Die Installation des NVIDIA-Treibers ist mit den echten Paketen und dem Bau
  des Kernelmoduls geprüft, aber noch nie mit einer echten Karte gelaufen.
  Eine Karte gehört entweder dem NAS und seinen Apps oder einer virtuellen
  Maschine, nicht beiden zugleich.
- Kontingente gibt es nur auf ZFS. Der Btrfs-Verbund ist immer ein Spiegel mit
  zwei Kopien; RAID 5 und 6 bietet Titan mit Btrfs nicht an. Den Plattentausch
  für ZFS gibt es weiterhin in der bisherigen Oberfläche unter `/classic`.
- Die eigene Freigabe des Systemdienstes gilt für Root-Terminal und
  Root-Dateizugriff. Alle übrigen Verwaltungsaktionen prüft weiterhin die
  Webanwendung.
