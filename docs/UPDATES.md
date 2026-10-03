# Titan-Systemupdates und Rollback

Unter **Einstellungen → Updates & Rollback** den Kanal **Alpha** wählen und nach
Updates suchen. Beta und Stable bieten erst dann Versionen an, wenn entsprechende
Veröffentlichungen vorhanden sind. Der Alpha-Kanal berücksichtigt später auch
Beta- und Stable-Versionen.

Ein Update enthält Titan und den Debian-Systembereich einschließlich Kernel,
Docker und VM-Komponenten. Signatur, Prüfsummen und Kompatibilität werden vor der
Aktivierung geprüft. Titan beschreibt den inaktiven der beiden Systembereiche.
Der laufende Stand bleibt bis zum ausdrücklich bestätigten Neustart aktiv.

1. Update prüfen und vorbereiten.
2. Laufende virtuelle Maschinen geordnet herunterfahren.
3. „Neu starten“ wählen und mit **Ja, neu starten** bestätigen. Kein Wort abtippen.
4. Nach erfolgreicher Startprüfung erscheint der vorherige lokale Systemstand
   im Rollback-Dropdown. Für die Rückkehr auswählen, bestätigen und neu starten.

Direkt nach der ersten Installation ist das Dropdown noch leer. Es gibt einen
vorherigen Systemstand, sobald das erste Update erfolgreich gestartet wurde.
Automatische Updatesuche bzw. Vorbereitung löst keinen automatischen Neustart aus.

Benutzer, Freigaberechte, NAS-Einstellungen sowie App-, VM- und Nutzdaten bleiben
auf dem gemeinsamen Datenbereich. Rollback setzt diese Daten nicht zurück und
ersetzt kein Backup. Unveränderte Systemkonfigurationen folgen dem ausgewählten
Systemstand; lokale Änderungen unter `/etc` bleiben erhalten.

Wenn ein neuer Stand seinen Start nicht bestätigt, kann der Bootloader beim
nächsten Neustart auf den vorherigen gesunden Stand zurückgehen. Ein hängender
Gast benötigt dafür einen Reset in Proxmox. Die beiden Systembereiche liefern
keinen Schutz gegen einen Ausfall des gemeinsamen Datenträgers.

Der gemeinsame EFI-/GRUB-Startbereich wird durch diese Alpha-Systemupdates noch
nicht erneuert. Änderungen daran oder am Partitionslayout erfordern derzeit ein
neues Installationsimage. Normale kompatible Titan-/Debian-Versionen werden über
den Update-Kanal eingespielt.

[Installationsimage und Testgrenzen](TITAN-IMAGE.md). Eine bestehende RaNAS-/uCore-
Installation lässt sich damit nicht direkt auf Titan umstellen.
