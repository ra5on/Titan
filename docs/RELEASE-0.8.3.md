# Titan 0.8.3 · Stable

Ein gemeinsamer Desktop für Alltag und Verwaltung. Optionale Dienste und
Treiber lassen sich als Plugins im Appstore nachinstallieren. Titan selbst
bleibt im Stable-Kanal; einzelne noch nicht umfassend auf echter Hardware
erprobte Plugins tragen ein Beta-Kennzeichen.

## Ein Desktop

Sicherheit mit Zwei-Faktor-Anmeldung, Webzugriff, Meldungen und E-Mail,
Systemdienste, Docker-Verwaltung, Sicherungen, Speicherwartung und Updates
sind in die gemeinsame Oberfläche integriert. Alte `/classic`-Lesezeichen
führen in diesen Desktop. Die bisherige Desktop-Shell wird nicht mehr geladen.

VMs bieten Sicherungen, Klone, Wiederherstellung als neue VM und eine
ISO-Bibliothek. Der Dateimanager ergänzt Dateierstellung, Textbearbeitung mit
Schutz vor gleichzeitigen Änderungen, Kopieren, Verschieben und
Papierkorb-Wiederherstellung. Administratoren können Datenbereiche direkt
öffnen und nach erneuter Anmeldung den zeitlich begrenzten Root-Modus für
Systemdateien und Terminal aktivieren. Root-Rechte enden mit der Freigabe.

## Plugins im Appstore

- **Cloudflare Tunnel · Beta:** Ein eigener Debian-Dienst ersetzt auf Wunsch
  den bisherigen Titan-Docker-Tunnel. Die Binärdatei wird erst bei Installation
  geladen und anhand ihrer SHA-256-Summe geprüft. Token, Plugin-Dateien und
  Einstellungen liegen im persistenten Bereich. Installation, Updateprüfung,
  Aktualisierung, Start, Stopp und Deinstallation sind im Appstore verfügbar.
  Beim ausdrücklich gewählten Umstieg wird der bisherige Docker-Tunnel erst
  nach bestätigter neuer Verbindung gestoppt. Eine fehlgeschlagene Einrichtung
  setzt die geänderten lokalen Dateien und Dienste zurück.
- **NVIDIA-Treiber · Beta:** Installation, Updateprüfung, Aktualisierung und
  Entfernung über den Appstore. NVIDIA-Pakete gehören nicht zum Basisimage.
  Nach Bestätigung der NVIDIA-Lizenzbedingungen lädt Titan sie aus dem
  offiziellen Paketarchiv und baut das Kernelmodul. Laufende GPU-Apps müssen
  vor Update oder Entfernung gestoppt werden. Docker startet zum Abschluss
  neu. Eine unterbrochene Paketänderung erfordert gegebenenfalls Reparatur oder
  Neustart; sie ist keine atomare Transaktion.

Die Plugins sind feste, von Titan verwaltete Erweiterungen. Beliebige Skripte
aus fremden Quellen lassen sich über diese Schnittstelle nicht installieren.

## Cloudflare-Zieladresse

In der öffentlichen Route im Cloudflare-Konto muss für das native Plugin
**Typ HTTP** und **URL `127.0.0.1:5102`** stehen. Die öffentliche Titan-Adresse
bleibt HTTPS. Kein HTTP-Host-Header mit der internen NAS-IP wird benötigt.
Eine NAS-IP mit HTTPS spricht einen anderen lokalen Zugang an und kann eine
leere Antwort liefern. Der Tunnel-Token erlaubt Titan nicht, diese Route im
Cloudflare-Konto selbst zu ändern.

Unter **Einstellungen → Fernzugriff → Verbindung prüfen** wird separat geprüft,
ob die öffentliche Adresse tatsächlich Titan erreicht. Ein laufender Dienst
allein gilt dafür nicht als Bestätigung. Die Deinstallation entfernt den
lokalen Dienst und Token; den Tunnel im Cloudflare-Konto entfernt der Benutzer
bei Bedarf separat.

## Update und Grenzen

Bestehende Debian-A/B-Installationen benötigen das vollständige signierte
Systemupdate. Ein reines Oberflächenupdate reicht für die neuen Plugin-APIs
und den Komponentenhelfer nicht aus. Installierte NVIDIA-Treiber werden nach
einem Systemwechsel für den neuen Kernel erneut eingerichtet; dafür wird
Internetzugang benötigt.

Diese Version wird deshalb ausschließlich als vollständiges Systemupdate
angeboten. Ältere Web-Updater erhalten keinen separaten Download der neuen
Oberfläche. Der vorbereitete Stand 0.8.2 wurde vor der Veröffentlichung
gestoppt; sein bereits reservierter Git-Tag wird nicht nachträglich verändert.

USB-Automount, laufender Abgleich, Btrfs-Spiegel und USB-/PCI-Durchreichung
behalten ihre individuellen Beta-Kennzeichen. Ein erfolgreicher öffentlicher
Cloudflare-Zugang mit Benutzerkonto und die GPU-Nutzung auf der konkreten
NAS-Hardware müssen praktisch geprüft werden. Es wird kein Code und kein
Design-Asset aus dem UmbrelOS-basierten TitanOS-Fork übernommen.
