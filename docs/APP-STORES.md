# Titan Apps und vorhandene Docker-Anwendungen

Ab Titan 0.5.8 bietet **Apps** eigene Docker-Compose-Anwendungen an. Ab 0.5.9 stehen **Cloudflare Tunnel, Immich, AdGuard Home und Tailscale** bereit. Der Katalog steht lokal bereit; Titan lädt beim Start keinen BigBear-Katalog und bietet keinen Import externer Stores an.

Bereits installierte Anwendungen und ihre gespeicherten Compose-Rezepte bleiben erhalten. Die Umstellung entfernt weder Container noch Konfiguration, Datenbanken oder Nutzdaten. Unter **Weitere installierte Apps → Verwalten** und unter **Docker** lassen sich diese Anwendungen weiter bedienen. Das bisherige Cloudflared-Web wird nicht für neue Installationen angeboten.

## Cloudflare Tunnel installieren

1. **Apps → Cloudflare Tunnel** öffnen. Ein Administrator kann die Installation starten.
2. Den Tunnel-Token aus der Connector-Einrichtung des Cloudflare-Kontos einfügen. Nur den Token verwenden, keinen Installationsbefehl oder Verwaltungs-API-Token. Eine öffentliche Titan-Adresse ist optional.
3. **Installieren & verbinden** wählen. Die Ansicht zeigt die tatsächlich ausgeführten Schritte: Docker prüfen, private Dateien und Compose erstellen, Image laden, Container erstellen und starten, Cloudflare-Verbindung prüfen, lokalen Zugang einrichten und öffentlichen Zugang prüfen.
4. Den öffentlichen Hostnamen in Cloudflare auf die angezeigte **Service URL** richten. Die HTTPS-Adresse anschließend in Titan unter **Öffentliche Route** mit **Adresse speichern & prüfen** übernehmen.

Ein zusätzliches Verwaltungspasswort wird nicht benötigt. Die Titan-Anmeldung schützt weiterhin die Weboberfläche. Der Connector verwendet das Host-Netz und das lokale HTTP-Ziel `http://127.0.0.1:5102`. Damit wird keine wechselnde Docker-Container-IP als Ziel verwendet.

Die Installation läuft auf dem NAS weiter, wenn das Fenster geschlossen wird. Nach erneutem Öffnen erscheinen der gespeicherte Verlauf und der aktuelle Laufzeitstatus. Ein fehlgeschlagener oder durch einen Dienstneustart unterbrochener Auftrag lässt sich mit **Einrichtung fortsetzen** erneut prüfen; private Wiederaufnahme-Eingaben werden nicht an den Browser zurückgegeben. Nach erfolgreichem Abschluss oder ausdrücklicher Deinstallation werden diese vorübergehenden Eingaben entfernt.

**Mit Cloudflare verbunden** bestätigt den Connector, **Öffentlicher Zugang geprüft** bestätigt zusätzlich die öffentliche Titan-Adresse. Ohne öffentliche Route können die ersten Schritte abgeschlossen sein, während die öffentliche Prüfung aussteht. Ein gestarteter Container oder abgeschlossener früherer Auftrag genügt nicht als Bereitschaftsnachweis.

Der Token wird privat gespeichert und nie wieder im Formular angezeigt. **Token ändern oder erneut verbinden** ersetzt ihn ausdrücklich. Details zu Route, Datenschutz und Diagnose: [Fernzugriff mit Cloudflare Tunnel](REMOTE-ACCESS.md).

## Immich installieren

**Apps → Immich → Einrichten** öffnen, einen verfügbaren lokalen Speicher und den Webport wählen. Titan installiert den freigegebenen Immich-Server und die passende Bilderkennung (3.3.0), PostgreSQL mit VectorChord und Valkey gemeinsam. Datenbank und Cache veröffentlichen keine eigenen Hostports. Das Datenbankpasswort wird einmalig erzeugt und bei einer Wiederaufnahme beibehalten.

Fotos, Datenbank, Modelle und Cache erhalten getrennte Ordner auf dem gewählten Speicher. Die Datenbank benötigt ein lokales Linux-Dateisystem; NFS/SMB sowie ungeeignete externe Dateisysteme werden abgewiesen. Vor einem Update Konfiguration einschließlich Datenbank und die Fotos sichern. Ein neues Rezept ersetzt einen vorhandenen Stack erst durch den ausdrücklichen Updateablauf.

Das ausgewogene Profil begrenzt die Container zusammen auf **6,25 GiB**, davon **2 GiB für PostgreSQL**. Zusätzlich berücksichtigt Titan die NAS-Reserve, laufende Apps/VMs und Installationsbedarf. Auf einem 8-GiB-Host verlangt die frische Installation konservativ etwa **7,75 GiB verfügbaren RAM**; bei weniger Kapazität wird vor dem Download gestoppt. **16 GiB Host-RAM** sind für den vollständigen Verbund praktikabler. Grenzen sind Obergrenzen, keine gemessene Nutzung. x86-Prozessoren müssen die von Immich 3 benötigten x86-64-v2-Funktionen unterstützen. Standardmäßig wird CPU-Bilderkennung eingerichtet; GPU-Treiber oder Hardwarebeschleunigung werden nicht automatisch installiert.

Nach bestätigter Bereitschaft aller Dienste Immich öffnen und im ersten Assistenten ein eigenes Administratorkonto anlegen. Grundlagen: [offizielle Compose-Anleitung](https://docs.immich.app/install/docker-compose/), [Systemanforderungen](https://docs.immich.app/install/requirements/), [Sicherung und Wiederherstellung](https://docs.immich.app/administration/backup-and-restore/).

## AdGuard Home installieren

**Apps → AdGuard Home → Einrichten** öffnen. Webport und DNS-Port sind vor dem Download sichtbar. DNS benötigt normalerweise **53/TCP und 53/UDP**. Titan prüft die tatsächliche Hostbelegung und reservierte App-Ports. Wenn beispielsweise Pi-hole oder ein Systemdienst Port 53 belegt, diesen gezielt umstellen oder eine andere Bindung planen; Titan deaktiviert weder `systemd-resolved` noch Host-DNS automatisch. Ein abweichender veröffentlichter DNS-Port ist für gewöhnliche Router-DNS-Felder nicht direkt geeignet.

Die App startet mit persistenten Konfigurations- und Arbeitsordnern. Im ersten AdGuard-Assistenten ein eigenes Konto erstellen, für die Weboberfläche **Alle Schnittstellen / interner Port 3000** und für DNS Port 53 wählen. Der im Titan-Formular gewählte Webport wird auf den internen Port 3000 umgesetzt. Anschließend die NAS-IP ausdrücklich im Router oder auf den gewünschten Clients als DNS-Server eintragen. Der Installationsstatus bestätigt zunächst die erreichbare Weboberfläche; die DNS-Einrichtung im Assistenten und die Clientauswahl bleiben erforderlich. DHCP und zusätzliche verschlüsselte DNS-Ports werden nicht automatisch eingerichtet. [Offizielle Docker-Anleitung](https://github.com/AdguardTeam/AdGuardHome/wiki/Docker).

## Tailscale und Heimnetzbereiche

**Apps → Tailscale → Einrichten** öffnen, einen Auth-Key aus dem eigenen Tailscale-Konto einfügen und einen Gerätenamen wählen. Der Schlüssel liegt in privaten App-Dateien und einer nur lesbar eingebundenen **0600-Datei**; er erscheint weder in Compose-Argumenten noch in der Container-Umgebung oder öffentlichen Statusmeldungen. Der persistente Zustandsordner erhält die Geräteidentität über Neustarts. Bei fehlgeschlagener Anmeldung kann der Auth-Key ausdrücklich ersetzt werden; andere gespeicherte Einstellungen werden dabei nicht still geändert.

- **NAS-IP zusätzlich freigeben**: optional eine private IP des NAS als einzelne `/32`- bzw. `/128`-Hostroute ankündigen. Auch diese Route im Tailscale-Konto freigeben. Danach wird das NAS über seine private LAN-IP erreicht; die Tailscale-IP des isolierten Containers ist kein automatischer Proxy für das NAS. Ohne NAS-IP und ohne Subnet-Routen stellt der Container keine NAS-Dienste bereit.
- **Heimnetz freigeben**: ausdrücklich aktivieren und bis zu acht private, nicht überlappende CIDR-Netze eintragen, beispielsweise `192.168.1.0/24`. Standardrouten, öffentliche Adressräume, Loopback und Link-Local sind ausgeschlossen.
- Die angekündigten Routen anschließend in der **Tailscale-Verwaltung freigeben** und passende Zugriffsregeln erlauben. Je nach Client muss die Nutzung von Subnet-Routen zusätzlich aktiviert werden. Eine erfolgreiche Anmeldung bestätigt diese externe Freigabe oder praktische Erreichbarkeit noch nicht.

Titan verwendet Tailscales **Userspace-Subnet-Router** in einem isolierten Compose-Netz. Er unterstützt TCP und UDP sowie eingeschränkt rekonstruierten Ping, jedoch keine beliebigen IP-Protokolle wie SCTP oder andere ICMP-Nachrichten. Es werden kein TUN-Gerät, `NET_ADMIN`, Hostnetz, Host-IP-Forwarding, Exit-Node oder Host-DNS eingerichtet. Docker verwaltet sein gewöhnliches Bridge-Netz; bestehende Regeln des Hosts und der Zielgeräte müssen den gewünschten Verkehr erlauben. [Docker-Parameter](https://tailscale.com/docs/features/containers/docker/docker-params), [Userspace-Grenzen](https://tailscale.com/docs/reference/kernel-vs-userspace-routers), [Routenfreigabe und Zugriff](https://tailscale.com/docs/features/subnet-routers).

## Tatsächliche Installationsschritte

Die drei neuen Apps verwenden denselben geschützten Hintergrundauftrag: **Docker prüfen → Speicher und Compose einrichten → Images laden → Container erstellen → Dienste starten → Betriebsbereitschaft prüfen → erste Einrichtung anzeigen**. Ein Schritt wird erst nach seiner tatsächlichen Prüfung abgeschlossen. Bleibt ein Dienst ungesund oder Tailscale unangemeldet, schlägt die Installation fehl; ein laufender Container gilt nicht allein als Erfolg.

Nach einem Fehler oder Dienstneustart lassen sich die geschützten Angaben mit **Einrichtung fortsetzen** wiederverwenden. Titan prüft Eigentum, gespeicherte Konfiguration, Speicher, Ports und RAM erneut. Geänderte fremde Einstellungen werden nicht übernommen. Der Verlauf bleibt sichtbar, während der aktuelle Laufzeitstatus getrennt aktualisiert wird; spätere Dienstprobleme machen einen historischen Auftrag nicht rückwirkend erfolgreich oder erfolglos. In der Demo sind Installation und Änderungen deaktiviert.

## Vorhandene Apps verwalten

Docker zeigt zusammengehörige Dienste eines verwalteten Compose-Pakets gemeinsam an. Details enthalten Status, tatsächlich gemessene Ressourcen, Protokolle und verfügbare Aktionen. Start, Stop und Neustart verwenden weiterhin das gespeicherte Rezept einer vorhandenen App; es wird nicht durch einen neuen Katalog ersetzt.

Deinstallation entfernt die verwalteten Container, behält aber die App-Konfiguration und Nutzdaten. App-Sicherungen stoppen alle beteiligten Dienste für einen konsistenten Dateistand. Separate Nutzdaten müssen ausdrücklich ausgewählt werden. Grenzen und Wiederherstellung: [App-Sicherungen](BACKUPS.md).

Gespeicherte Rezepte früherer externer Apps werden für die Verwaltung und ältere Systemstände aufbewahrt. Ihre Verfügbarkeit ist keine Freigabe für neue Installationen aus diesen Quellen. Persönliche Zugangsdaten erscheinen weiterhin nicht als normale öffentliche App-Einstellung.

## Netzwerk und Geräte vorhandener Anwendungen

Unter **Docker → Netzwerke** zeigt Titan vorhandene, eigene und von Apps verwendete Netze mit ihren Containerzuordnungen an. Ein eigenes Bridge-Netz lässt sich nur entfernen, wenn es weder von einem Container noch einem installierten App-Paket verwendet wird. Ein gestopptes Paket gibt seine Netzwerkzuordnung nicht automatisch frei.

Titan prüft private Subnetze gegen vorhandene Docker-Netze und Host-Routen. Interne Netze sind nur für Anwendungen geeignet, deren benötigte Verbindungen dadurch weiterhin möglich sind. Zusätzliche Macvlan-, Overlay- oder IPv6-Netze werden darüber nicht automatisch eingerichtet.

Die Geräteauswahl zeigt tatsächlich erkannte USB-, Grafik- und Beschleunigergeräte mit ihren Linux-Pfaden. Nach erneutem Anstecken seine Zuordnung prüfen. Ein fehlendes oder neu zugeordnetes Gerät verhindert einen neuen App-Start, bis die Auswahl korrigiert wurde; Stoppen und Entfernen bleiben möglich.

- Intel-/AMD-Grafik benötigt ein Rendergerät mit aktivem Treiber. AMD-Compute kann zusätzlich `/dev/kfd` benötigen.
- NVIDIA benötigt einen passenden Treiber und eine einsatzbereite NVIDIA Container Runtime.
- NPUs werden über vorhandene `/dev/accel/accel*`-Geräte erkannt.

Die Auswahl installiert keine Treiber und garantiert keine Unterstützung im Container-Image. In Proxmox muss die Hardware zuerst der Titan-VM zugewiesen werden. Physische Geräte werden von den automatisierten QEMU-Tests nicht abgenommen.

**App-Einstellungen → Geräte ändern** setzt eine gestoppte App voraus. Titan erstellt die verwalteten Container mit der neuen Zuordnung; gespeicherte Daten bleiben erhalten. Bei einem Fehler versucht Titan die vorherige Konfiguration wiederherzustellen. Einen gemeldeten Wiederherstellungsfehler über Status und Logs prüfen.

Für unterstützte manuell mit Titan erstellte Container bietet **Einstellungen & Geräte** eine neue Containerkonfiguration mit demselben Datenvolume an. Der vorherige Container bleibt zunächst gestoppt als Sicherung erhalten. Das gemeinsam genutzte Volume ist kein unabhängiges Backup.

## System-Rollback

Ein Betriebssystem-Rollback setzt App-Daten oder Geräteeinstellungen nicht zurück. Ältere Titan-Versionen sehen nur Rezepte, die sie verstehen; neuere Einträge und ihre Daten werden dabei nicht gelöscht. Vor einem Wechsel unabhängige Sicherungen behalten. Die Kompatibilitätsprüfung ersetzt keinen praktischen Rollback-Test mit den veröffentlichten Images.
