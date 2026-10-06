# RAM-Schutz für Apps und virtuelle Maschinen

Titan zeigt weiterhin den gesamten belegten RAM einschließlich Dateicache. Ob
eine weitere Installation sicher gestartet werden kann, entscheidet hingegen
der aktuelle `MemAvailable`-Wert, die tatsächliche Kernel-Speicherwartezeit und
ein getrenntes Budget für Containergrenzen und aktive virtuelle Maschinen.
Swap wird angezeigt, erhöht aber das Startbudget nicht.

Die NAS-Reserve beträgt mindestens 512 MiB und höchstens 1 GiB, abhängig von der
RAM-Kapazität. Bei einer Installation kommen 512 MiB für Download/Entpacken hinzu.
Die Obergrenzen laufender Container sowie der vollständig zugewiesene RAM aller
aktiven libvirt-VMs zählen zum Kapazitätsbudget. Für jede VM werden zusätzlich
mindestens 256 MiB oder fünf Prozent als QEMU-Overhead angesetzt. Pausierte VMs
belegen weiterhin ihr Budget; der aktuelle Balloon-/RSS-Wert reduziert es nicht.
Auch manuell angelegte Docker-Container benötigen vor Start oder Neustart eine
endliche RAM-Grenze. Eine aktive Container-ID wird im Budget nur einmal gezählt.
Ein laufender Container ohne messbare, endliche Grenze blockiert zusätzliche
App-, Container- und VM-Starts, bis seine Grenze gesetzt oder er gestoppt wurde.
Titan ändert bestehende Containergrenzen dafür nicht ungefragt.

Neue Installationen verwenden das Profil **Ausgewogen**. Nextcloud installiert
Datenbank, Redis und Cron gemeinsam; Euro-Office ist ein bewusst auswählbarer
Zusatz. Nextcloud ohne Office hat im ausgewogenen Profil zusammen 3,75 GiB
Container-Obergrenzen. Auf einem 8-GiB-NAS sind dafür vor einer Neuinstallation
einschließlich Reserven mindestens 5,25 GiB verfügbarer RAM erforderlich.
Euro-Office erhöht das Paketbudget um 4 GiB. Das vollständige Paket benötigt damit
9,25 GiB einschließlich NAS-/Installationsreserve und passt nicht sicher auf ein
8-GiB-System. In diesem Fall vorerst ohne Office installieren oder mehr RAM
zuweisen. Obergrenzen sind ausdrücklich **kein gemessener Verbrauch**.

Nextclouds PHP-Requests behalten mindestens 512 MiB; Apache-Parallelität und
Datenbankarbeitsspeicher werden begrenzt. Office erhält seine dokumentierte
Mindestkapazität. Bestehende Installationen ohne neue Profilfelder bleiben im
Profil **Bisherige Installation** mit ihrer bisherigen Office-Auswahl. Ein
Systemupdate entfernt oder deaktiviert keine bestehenden Dienste ungefragt.

Vor Download und Start prüft der Agent frische Messwerte. Starts und
Installationen teilen eine Konfigurationssperre und eine gemeinsame
Ressourcenfreigabe; Dateiübersichten, Status und das Stoppen anderer Apps bleiben
bedienbar. Bei tatsächlichem Engpass wird die neue Aktion verständlich abgelehnt.
Laufende Apps und VMs werden dadurch nicht automatisch beendet. Unlesbare
RAM-Daten oder ein installierter, aber nicht erreichbarer libvirt-Dienst bedeuten
einen unbekannten Bedarf und verhindern zusätzliche Starts. Ohne `virsh` werden
keine libvirt-VMs angenommen.

Die Reserven verhindern die von Titan gesteuerte Überbuchung; sie ersetzen
keinen Lasttest. Prozesse außerhalb der Titan-Verwaltung und manuelle
Docker/libvirt-Kommandos können zusätzliche Last erzeugen. Bei der Abnahme auf
dem 8-GiB-Testsystem sollten Dateiübersichten während einer Nextcloud-Installation,
gleichzeitige App-/VM-Starts, Auslastung unter Last sowie Fehler und Stoppen nach
einer fehlgeschlagenen Installation geprüft werden.

Technische Quellen: [Linux MemAvailable](https://docs.kernel.org/filesystems/proc.html),
[Linux Speicherdruck](https://docs.kernel.org/accounting/psi.html),
[Nextcloud PHP-Konfiguration](https://docs.nextcloud.com/server/stable/admin_manual/installation/php_configuration.html),
[Euro-Office Docker-Anforderungen](https://euro-office.github.io/documentation/installation/docker/),
[libvirt aktive und pausierte Domains](https://www.libvirt.org/manpages/virsh.html).
