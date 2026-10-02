"""Curated deployment recipes. Remote metadata never becomes executable configuration."""
import json
import re
import time
import urllib.request
from .core import Error, integer

APPS = {
    "jellyfin": {"name": "Jellyfin", "description": "Deine Filme, Serien und Musik an einem Ort.",
                 "category": "Medien", "color": "#9564f5", "symbol": "▶", "port": 8096,
                 "image": "lscr.io/linuxserver/jellyfin:latest", "mount": "/data", "memory": "2g"},
    "syncthing": {"name": "Syncthing", "description": "Dateien zwischen deinen Geräten synchronisieren.",
                  "category": "Dateien", "color": "#43a9db", "symbol": "↻", "port": 8384,
                  "image": "lscr.io/linuxserver/syncthing:latest", "mount": "/data", "memory": "1g"},
    "nextcloud": {"name": "Nextcloud", "description": "Private Cloud für Dateien, Kalender und Kontakte.",
                  "category": "Dateien", "color": "#0082c9", "symbol": "☁", "port": 443,
                  "image": "lscr.io/linuxserver/nextcloud:latest", "mount": "/data", "memory": "2g",
                  "scheme": "https", "default_port": 8444, "note": "Nach Installation im Nextcloud-Assistenten Datenbank einrichten; SQLite eignet sich nur für kleine Installationen."},
    "heimdall": {"name": "Heimdall", "description": "Ein übersichtliches Dashboard für deine Dienste.",
                 "category": "Werkzeuge", "color": "#eaa655", "symbol": "H", "port": 80,
                 "image": "lscr.io/linuxserver/heimdall:latest", "mount": None, "memory": "512m", "default_port": 8080},
    "freshrss": {"name": "FreshRSS", "description": "Nachrichten und Blogs in deinem eigenen Feedreader lesen.",
                 "category": "Werkzeuge", "color": "#56ab8c", "symbol": "◔", "port": 80,
                 "image": "lscr.io/linuxserver/freshrss:latest", "mount": None, "memory": "512m", "default_port": 8082,
                 "verified": "2026-09-30", "note": "Nach dem Start im Einrichtungsassistenten ein Konto und die Datenbank einrichten. SQLite ist für die private Nutzung verfügbar."},
    "calibre-web": {"name": "Calibre-Web", "description": "Deine Calibre-Bibliothek im Browser lesen und verwalten.",
                    "category": "Medien", "color": "#877bcd", "symbol": "▤", "port": 8083,
                    "image": "lscr.io/linuxserver/calibre-web:latest", "mount": "/books", "memory": "1g",
                    "verified": "2026-09-30", "note": "Benötigt eine vorhandene Calibre-Bibliothek mit metadata.db. In der App /books wählen. Erstes Konto: admin / admin123; Passwort sofort ändern."},
    "prowlarr": {"name": "Prowlarr", "description": "Deine Medienindexer an einer zentralen Stelle verwalten.",
                 "category": "Medien", "color": "#e57938", "symbol": "P", "port": 9696,
                 "image": "lscr.io/linuxserver/prowlarr:latest", "mount": None, "memory": "1g",
                 "verified": "2026-09-30", "note": "Beim ersten Start Zugriffsschutz und deine Indexer einrichten. Zugangsdaten werden in der App verwaltet."},
    "radarr": {"name": "Radarr", "description": "Deine Filmsammlung organisieren und mit eigenen Quellen verbinden.",
               "category": "Medien", "color": "#cdb13e", "symbol": "R", "port": 7878,
               "image": "lscr.io/linuxserver/radarr:latest", "mount": "/movies", "memory": "1g",
               "verified": "2026-09-30", "note": "In Radarr /movies als Filmordner wählen und Zugriffsschutz einrichten. Indexer und Download-Dienste werden separat verbunden."},
    "sonarr": {"name": "Sonarr", "description": "Serienbibliotheken organisieren und neue Folgen aus eigenen Quellen beziehen.",
               "category": "Medien", "color": "#48a6c8", "symbol": "S", "port": 8989,
               "image": "lscr.io/linuxserver/sonarr:latest", "mount": "/data", "memory": "1g",
               "verified": "2026-10-01", "note": "Beim ersten Start Zugriffsschutz einrichten und einen Serienordner unter /data wählen. Indexer und Download-Client separat verbinden; dessen Downloadpfade müssen im Container erreichbar sein."},
    "lidarr": {"name": "Lidarr", "description": "Musiksammlungen verwalten und mit eigenen Indexern verbinden.",
               "category": "Medien", "color": "#42b495", "symbol": "L", "port": 8686,
               "image": "lscr.io/linuxserver/lidarr:latest", "mount": "/data", "memory": "1g",
               "verified": "2026-10-01", "note": "Zugriffsschutz einrichten und einen Musikordner unter /data wählen. Indexer und Download-Client separat verbinden; Downloadpfade gegebenenfalls in Lidarr zuordnen."},
    "bazarr": {"name": "Bazarr", "description": "Passende Untertitel für deine Filme und Serien verwalten.",
               "category": "Medien", "color": "#83a43d", "symbol": "B", "port": 6767,
               "image": "lscr.io/linuxserver/bazarr:latest", "mount": "/data", "memory": "1g",
               "verified": "2026-10-01", "note": "Im Assistenten Zugriffsschutz, Sprachen und Untertitelanbieter einrichten. Sonarr oder Radarr separat verbinden; deren Medienpfade auf die zugehörigen Ordner unter /data abbilden."},
    "dokuwiki": {"name": "DokuWiki", "description": "Ein eigenes Wiki für Anleitungen, Notizen und gemeinsames Wissen.",
                 "category": "Werkzeuge", "color": "#ca5f6e", "symbol": "D", "port": 80,
                 "image": "lscr.io/linuxserver/dokuwiki:latest", "mount": None, "memory": "512m", "default_port": 8084,
                 "verified": "2026-10-01", "note": "Nach dem ersten Start /install.php an die App-Adresse anhängen und Administrator sowie Zugriffsregeln einrichten. Danach den Container neu starten. Wiki und Einstellungen bleiben im Konfigurationsverzeichnis gespeichert; keine separate Datenbank nötig."},
    "kavita": {"name": "Kavita", "description": "Bücher, Comics und Manga im Browser lesen und mit deiner Familie teilen.",
               "category": "Medien", "color": "#45a36a", "symbol": "K", "port": 5000,
               "image": "lscr.io/linuxserver/kavita:latest", "mount": "/data", "memory": "1g", "default_port": 8085,
               "verified": "2026-10-01", "note": "Im Einrichtungsassistenten ein Administrator-Konto anlegen und Bibliotheken unter /data hinzufügen. Die App verwendet außen Port 8085 als Vorauswahl; Titan bleibt auf Port 5000 erreichbar."},
}

# Authentication fields are mandatory here even where an upstream image permits
# anonymous access. Only these local recipes may turn form inputs into settings.
_PASSWORD = {"key": "password", "label": "Passwort", "type": "password", "required": True,
             "min_length": 12, "max_length": 256,
             "help": "Mindestens 12 Zeichen. Wird nur in der privaten App-Konfiguration gespeichert."}
APPS.update({
    "qbittorrent": {"name": "qBittorrent", "description": "Downloads mit einer eigenen Weboberfläche verwalten.",
                    "category": "Downloads", "color": "#3e8ac6", "symbol": "q", "port": 8080,
                    "image": "lscr.io/linuxserver/qbittorrent:latest", "mount": "/downloads", "memory": "1g", "default_port": 8090,
                    "verified": "2026-10-01", "dynamic_web_port": True,
                    "install_schema": [{"key": "peer_port", "label": "Verbindungsport (TCP und UDP)", "type": "number", "default": 6881, "min": 1024, "max": 65535, "env": "TORRENTING_PORT"}],
                    "extra_ports": [{"option": "peer_port", "protocol": "tcp"}, {"option": "peer_port", "protocol": "udp"}],
                    "note": "Benutzer admin: das erste zufällige Passwort steht im App-Protokoll. Anschließend in qBittorrent ein eigenes Passwort setzen. Downloads liegen unter /downloads. Der Webport wird innen und außen passend gesetzt."},
    "transmission": {"name": "Transmission", "description": "Ein schlanker Download-Client mit geschützter Weboberfläche.",
                     "category": "Downloads", "color": "#bf4d4a", "symbol": "T", "port": 9091,
                     "image": "lscr.io/linuxserver/transmission:latest", "mount": "/downloads", "memory": "1g", "verified": "2026-10-01",
                     "install_schema": [{"key": "username", "label": "Benutzername", "type": "text", "required": True, "default": "admin", "max_length": 64, "env": "USER"},
                                        {**_PASSWORD, "env": "PASS"},
                                        {"key": "peer_port", "label": "Verbindungsport (TCP und UDP)", "type": "number", "default": 51413, "min": 1024, "max": 65535, "env": "PEERPORT"}],
                     "extra_ports": [{"option": "peer_port", "protocol": "tcp"}, {"option": "peer_port", "protocol": "udp"}],
                     "note": "Zugang wird bei der Installation festgelegt. Downloads unter /downloads. Zugangsdaten in der verwalteten Konfiguration belassen; nicht zusätzlich in settings.json ändern."},
    "code-server": {"name": "Code-Server", "description": "Dateien und Projekte mit VS Code im Browser bearbeiten.",
                    "category": "Werkzeuge", "color": "#328cc6", "symbol": "</>", "port": 8443,
                    "image": "lscr.io/linuxserver/code-server:latest", "mount": "/data", "memory": "2g", "verified": "2026-10-01",
                    "install_schema": [{**_PASSWORD, "env": "PASSWORD"}], "environment": {"DEFAULT_WORKSPACE": "/data"},
                    "note": "Passwort wird bei der Installation festgelegt. Arbeitsbereich /data; Zugriff nur auf den ausgewählten App-Datenordner. Erweiterungen und Einstellungen bleiben in /config gespeichert."},
    "librespeed": {"name": "LibreSpeed", "description": "Die Verbindung zwischen deinem Gerät und dem NAS messen.",
                   "category": "Netzwerk", "color": "#3f9c83", "symbol": "↔", "port": 80,
                   "image": "lscr.io/linuxserver/librespeed:latest", "mount": None, "memory": "512m", "default_port": 8091, "verified": "2026-10-01",
                   "install_schema": [{**_PASSWORD, "label": "Passwort für gespeicherte Ergebnisse", "env": "PASSWORD"}],
                   "environment": {"DB_TYPE": "sqlite"},
                   "note": "Misst die Strecke vom Browser zum NAS. Die Messseite ist ohne Anmeldung erreichbar; das gewählte Passwort schützt die Ergebnisdatenbank. SQLite benötigt keinen zusätzlichen Datenbankdienst."},
    "grocy": {"name": "Grocy", "description": "Vorräte, Einkäufe und Aufgaben im Haushalt organisieren.",
              "category": "Werkzeuge", "color": "#68a857", "symbol": "G", "port": 80,
              "image": "lscr.io/linuxserver/grocy:latest", "mount": None, "memory": "512m", "default_port": 9283, "verified": "2026-10-01",
              "note": "Erste Anmeldung admin / admin; Passwort sofort ändern. Nach einem App-Update die Startseite öffnen, damit notwendige Datenbankmigrationen ausgeführt werden."},
    "pairdrop": {"name": "PairDrop", "description": "Dateien direkt zwischen Geräten im Browser übertragen.",
                 "category": "Dateien", "color": "#56a9b9", "symbol": "⇄", "port": 3000,
                 "image": "lscr.io/linuxserver/pairdrop:latest", "mount": None, "config_mount": False, "memory": "512m", "verified": "2026-10-01",
                 "environment": {"RATE_LIMIT": "true", "WS_FALLBACK": "true"},
                 "note": "Überträgt Dateien zwischen Geräten, ohne sie als NAS-Dateien abzulegen. Keine Benutzerkonten oder persistente App-Datenbank. Websocket-Fallback und Anfragelimit sind aktiviert."},
    "jackett": {"name": "Jackett", "description": "Eigene Indexer mit Medien- und Download-Apps verbinden.",
                "category": "Downloads", "color": "#858383", "symbol": "J", "port": 9117,
                "image": "lscr.io/linuxserver/jackett:latest", "mount": "/downloads", "memory": "1g", "verified": "2026-10-01",
                "environment": {"AUTO_UPDATE": "false"},
                "note": "In der App Administrator-Passwort setzen und eigene Indexer verbinden. /downloads ist der Ablageordner für den Blackhole-Modus. Updates werden über Titan verwaltet."},
    "sabnzbd": {"name": "SABnzbd", "description": "Usenet-Downloads mit Warteschlange und Weboberfläche verwalten.",
                "category": "Downloads", "color": "#e6ac3a", "symbol": "SAB", "port": 8080,
                "image": "lscr.io/linuxserver/sabnzbd:latest", "mount": "/downloads", "memory": "1g", "default_port": 8092, "verified": "2026-10-01",
                "note": "Im Assistenten eigenen Usenet-Zugang und Zugriffsschutz einrichten. Fertige und temporäre Downloads in Unterordnern von /downloads ablegen, damit sie im persistenten Datenbereich bleiben."},
    "wikijs": {"name": "Wiki.js", "description": "Dokumentation und Wissen mit einem modernen Wiki organisieren.",
               "category": "Werkzeuge", "color": "#297acf", "symbol": "W", "port": 3000,
               "image": "lscr.io/linuxserver/wikijs:latest", "mount": "/data", "memory": "1g", "default_port": 3001, "verified": "2026-10-01",
               "environment": {"DB_TYPE": "sqlite"},
               "note": "Im ersten Einrichtungsassistenten Administrator und eigene App-Adresse festlegen. SQLite ist vorkonfiguriert und bleibt in /config gespeichert; kein separater Datenbankcontainer erforderlich."},
    "grav": {"name": "Grav", "description": "Eine eigene Website mit einem CMS ohne Datenbank erstellen.",
             "category": "Werkzeuge", "color": "#966bc0", "symbol": "G", "port": 80,
             "image": "lscr.io/linuxserver/grav:latest", "mount": None, "memory": "512m", "default_port": 8093, "verified": "2026-10-01",
             "note": "Das Admin-Plugin ist enthalten. /admin öffnen und das erste Administratorkonto einrichten. Inhalte und Einstellungen liegen im persistenten Konfigurationsverzeichnis."},
    "mstream": {"name": "mStream", "description": "Deine Musiksammlung auf eigene Geräte streamen.",
                "category": "Medien", "color": "#dd626f", "symbol": "♫", "port": 3000,
                "image": "lscr.io/linuxserver/mstream:latest", "mount": "/music", "memory": "1g", "default_port": 3002, "verified": "2026-10-01",
                "note": "Musikordner /music verwenden. Einstellungen und Benutzerzugang über die App beziehungsweise /config/config.json einrichten. Aktuelle Versionen unterstützen keine USER/PASSWORD-Umgebungsvariablen mehr."},
    "cops": {"name": "COPS", "description": "Calibre-Bücher als schlanken Web- und OPDS-Katalog bereitstellen.",
             "category": "Medien", "color": "#ab804f", "symbol": "C", "port": 80,
             "image": "lscr.io/linuxserver/cops:latest", "mount": "/books", "memory": "512m", "default_port": 8094, "verified": "2026-10-01",
             "install_schema": [{"key": "https_port", "label": "Zusätzlicher HTTPS-Port", "type": "number", "default": 9443, "min": 1024, "max": 65535,
                                  "help": "Zusätzlicher verschlüsselter App-Zugang. Zertifikat in der App-Konfiguration verwalten."}],
             "extra_ports": [{"option": "https_port", "target": 443, "protocol": "tcp"}],
             "note": "Benötigt eine Calibre-Bibliothek mit metadata.db unter /books. OPDS-Endpunkt /index.php/feed. Bibliotheks- und Zugangseinstellungen in /config/config/local.php konfigurieren; ohne eigenen Zugriffsschutz ist der Katalog lesbar."},
    "duplicati": {"name": "Duplicati", "description": "Verschlüsselte Sicherungen deiner Dateien auf externe Ziele planen.",
                  "category": "Sicherung", "color": "#4c9c4c", "symbol": "D", "port": 8200,
                  "image": "lscr.io/linuxserver/duplicati:latest", "mount": "/source", "memory": "1g", "verified": "2026-10-01",
                  "install_schema": [{**_PASSWORD, "env": "DUPLICATI__WEBSERVICE_PASSWORD"},
                                     {"key": "encryption_key", "label": "Schlüssel für App-Einstellungen", "type": "password", "required": True,
                                      "min_length": 12, "max_length": 256, "pattern": "[A-Za-z0-9]+", "env": "SETTINGS_ENCRYPTION_KEY",
                                      "help": "Mindestens 12 Buchstaben/Ziffern. Sicher aufbewahren: wird auch zum Wiederherstellen der App-Einstellungen benötigt."}],
                  "note": "Web-Passwort und Schlüssel bei Installation festlegen. /source ist der ausgewählte NAS-Ordner. Sicherungsziel in Duplicati als externen Dienst (z. B. SFTP oder S3) einrichten; ein lokaler /backups-Ordner wird von dieser Vorlage nicht eingebunden. Backup-Passphrase separat im Sicherungsassistenten wählen."},
})
APPS["syncthing"]["extra_ports"] = [{"port": 22000, "protocol": "tcp"}, {"port": 22000, "protocol": "udp"}, {"port": 21027, "protocol": "udp"}]
APPS["syncthing"]["note"] = "Beim ersten Start unter Aktionen → Einstellungen Benutzername und Passwort für die Weboberfläche setzen. Synchronisierte Ordner unter /data anlegen. TCP/UDP 22000 und UDP 21027 werden zusätzlich zum Webport veröffentlicht."

# These recipes need no privileged host access or separate database container.
# Local IDs must also be valid Compose project names; upstream image names may
# differ, as with changedetection.io. Remote data only supplies display metadata.
APPS.update({
    "changedetection": {"name": "ChangeDetection", "description": "Änderungen an Webseiten verfolgen und Benachrichtigungen erhalten.",
                        "category": "Werkzeuge", "color": "#50a184", "symbol": "Δ", "port": 5000,
                        "upstream_name": "changedetection.io", "image": "lscr.io/linuxserver/changedetection.io:latest",
                        "mount": None, "memory": "1g", "default_port": 8102, "verified": "2026-10-02",
                        "note": "Webseiten und Benachrichtigungen in der App einrichten. Passwortschutz unter Settings aktivieren. Der einfache Abruf benötigt keinen zusätzlichen Browserdienst; anspruchsvolle JavaScript-Seiten können einen separat einzurichtenden Playwright-Dienst benötigen."},
    "deluge": {"name": "Deluge", "description": "Torrents mit Warteschlange, Zeitplan und Weboberfläche verwalten.",
               "category": "Downloads", "color": "#4a91c9", "symbol": "D", "port": 8112,
               "image": "lscr.io/linuxserver/deluge:latest", "mount": "/downloads", "memory": "1g", "verified": "2026-10-02",
               "install_schema": [{"key": "peer_port", "label": "Verbindungsport (TCP und UDP)", "type": "number", "default": 6882, "min": 1024, "max": 65535,
                                   "help": "Wird auf den internen Port 6881 abgebildet. In Deluge unter Preferences → Network eingehenden Port 6881 wählen und zufällige Ports deaktivieren."}],
               "extra_ports": [{"option": "peer_port", "target": 6881, "protocol": "tcp"}, {"option": "peer_port", "target": 6881, "protocol": "udp"}],
               "note": "Passwort nach der ersten Anmeldung unter Preferences → Interface ändern. Downloads unter /downloads ablegen. Unter Preferences → Network eingehenden Port 6881 wählen und zufällige Ports deaktivieren; außen gilt der bei Installation gewählte Verbindungsport."},
    "emby": {"name": "Emby", "description": "Filme, Serien und Musik für deine Geräte bereitstellen.",
             "category": "Medien", "color": "#52b54b", "symbol": "E", "port": 8096,
             "image": "lscr.io/linuxserver/emby:latest", "mount": "/data", "memory": "2g", "default_port": 8097, "verified": "2026-10-02",
             "note": "Im Assistenten ein Konto und Medienbibliotheken unter /data einrichten. Einige Funktionen benötigen Emby Premiere. Diese Vorlage nutzt Software-Transkodierung; GPU-Geräte werden nicht eingebunden."},
    "lazylibrarian": {"name": "LazyLibrarian", "description": "Bücher und Hörbücher mit deinen Quellen und Download-Diensten organisieren.",
                      "category": "Medien", "color": "#ac805e", "symbol": "LL", "port": 5299,
                      "image": "lscr.io/linuxserver/lazylibrarian:latest", "mount": "/data", "memory": "1g", "verified": "2026-10-02",
                      "note": "Bibliothek und Downloads in getrennten Unterordnern von /data auswählen. Quellen und Download-Client separat verbinden. Zugriffsschutz unter Config → Interface einrichten; optionale Calibre-/FFmpeg-Erweiterungen sind nicht Bestandteil dieser Vorlage."},
    "mylar3": {"name": "Mylar3", "description": "Comicsammlungen und neue Ausgaben mit eigenen Quellen verwalten.",
               "category": "Medien", "color": "#997bb8", "symbol": "M3", "port": 8090,
               "image": "lscr.io/linuxserver/mylar3:latest", "mount": "/data", "memory": "1g", "default_port": 8095, "verified": "2026-10-02",
               "note": "Benötigt einen eigenen ComicVine-API-Schlüssel. Comicbibliothek und Downloadordner in getrennten Unterordnern von /data einrichten, Download-Client separat verbinden und Benutzername/Passwort in der App-Konfiguration setzen."},
    "nginx": {"name": "Nginx", "description": "Eigene Webseiten und kleine PHP-Anwendungen im Heimnetz bereitstellen.",
              "category": "Werkzeuge", "color": "#32944b", "symbol": "N", "port": 80,
              "image": "lscr.io/linuxserver/nginx:latest", "mount": None, "memory": "512m", "default_port": 8098, "verified": "2026-10-02",
              "note": "Webdateien im privaten App-Konfigurationsordner unter www ablegen. Nginx-, PHP- und Seitenkonfiguration liegen dort ebenfalls. Diese Vorlage veröffentlicht HTTP; sie enthält keine grafische Verwaltungsoberfläche und keinen voreingestellten Zugriffsschutz."},
    "nzbget": {"name": "NZBGet", "description": "Usenet-Dateien herunterladen, prüfen und entpacken.",
               "category": "Downloads", "color": "#5889b5", "symbol": "NZB", "port": 6789,
               "image": "lscr.io/linuxserver/nzbget:latest", "mount": "/downloads", "memory": "1g", "verified": "2026-10-02",
               "install_schema": [{"key": "username", "label": "Benutzername", "type": "text", "required": True, "default": "nzbget", "max_length": 64, "env": "NZBGET_USER"},
                                  {**_PASSWORD, "env": "NZBGET_PASS"}],
               "note": "Titan setzt die bei Installation gewählten Zugangsdaten und ersetzt damit den Image-Standardzugang. Eigenen Usenet-Server in NZBGet einrichten. Fertige und temporäre Downloads in Unterordnern von /downloads ablegen."},
    "nzbhydra2": {"name": "NZBHydra2", "description": "Mehrere Usenet-Indexer gemeinsam durchsuchen und Download-Apps verbinden.",
                  "category": "Downloads", "color": "#87a147", "symbol": "HY", "port": 5076,
                  "image": "lscr.io/linuxserver/nzbhydra2:latest", "mount": "/downloads", "memory": "1g", "verified": "2026-10-02",
                  "note": "Unter Config → Authorization eigene Benutzer und Anmeldeschutz einrichten. Eigene Indexer und Download-Dienste sind erforderlich. /downloads ist für optionale NZB-Dateien verfügbar; Konfiguration und Datenbank bleiben in /config gespeichert."},
    "ombi": {"name": "Ombi", "description": "Medienwünsche deiner Nutzer sammeln und mit deinen Mediensystemen verbinden.",
             "category": "Medien", "color": "#dd834f", "symbol": "O", "port": 3579,
             "image": "lscr.io/linuxserver/ombi:latest", "mount": None, "memory": "1g", "verified": "2026-10-02",
             "note": "Im Assistenten ein Administratorkonto anlegen. Anschließend einen vorhandenen Jellyfin-, Emby- oder Plex-Server sowie bei Bedarf Sonarr/Radarr verbinden. Ombi selbst stellt keine Medien bereit."},
    "raneto": {"name": "Raneto", "description": "Anleitungen und Wissen als übersichtliche Markdown-Seiten sammeln.",
               "category": "Werkzeuge", "color": "#618ea8", "symbol": "R", "port": 3000,
               "image": "lscr.io/linuxserver/raneto:latest", "mount": None, "memory": "512m", "default_port": 3003, "verified": "2026-10-02",
               "note": "Ersten Standardzugang sofort ändern: Benutzer werden in /config/config/config.js verwaltet. Markdown-Inhalte liegen in /config/content, Bilder in /config/images. Der Webeditor bearbeitet Inhalte; die Grundeinstellungen werden als Datei verwaltet."},
    "tautulli": {"name": "Tautulli", "description": "Nutzung, Wiedergaben und Benachrichtigungen deines Plex-Servers auswerten.",
                 "category": "Medien", "color": "#d5ab43", "symbol": "T", "port": 8181,
                 "image": "lscr.io/linuxserver/tautulli:latest", "mount": None, "memory": "1g", "verified": "2026-10-02",
                 "note": "Ein vorhandener Plex Media Server und dessen Konto sind erforderlich. Im Einrichtungsassistenten den eigenen Tautulli-Zugang anlegen und Plex verbinden. Plex-Protokollordner werden von dieser Vorlage nicht eingebunden."},
    "ubooquity": {"name": "Ubooquity", "description": "Bücher und Comics im Browser und per OPDS lesen.",
                  "category": "Medien", "color": "#b182bc", "symbol": "U", "port": 2202,
                  "image": "lscr.io/linuxserver/ubooquity:latest", "mount": "/files", "memory": "1g", "verified": "2026-10-02",
                  "environment": {"MAXMEM": "512"},
                  "install_schema": [{"key": "admin_port", "label": "Administrationsport", "type": "number", "default": 2203, "min": 1024, "max": 65535,
                                      "help": "Separater Zugang zur Einrichtung: /ubooquity/admin an die Adresse dieses Ports anhängen."}],
                  "extra_ports": [{"option": "admin_port", "target": 2203, "protocol": "tcp"}],
                  "note": "Zuerst den gewählten Administrationsport (Vorauswahl 2203) mit /ubooquity/admin öffnen und ein Passwort setzen. Unter /files stehen die ausgewählten NAS-Dateien bereit; dort Bücher-/Comic-Unterordner für die Bibliotheken auswählen. Leseroberfläche am Webport unter /ubooquity/ öffnen."},
    "resilio-sync": {"name": "Resilio Sync", "description": "Ordner direkt zwischen deinen Geräten synchronisieren.",
                     "category": "Dateien", "color": "#486dae", "symbol": "RS", "port": 8888,
                     "image": "lscr.io/linuxserver/resilio-sync:latest", "mount": "/sync", "memory": "1g", "verified": "2026-10-02",
                     "extra_ports": [{"port": 55555, "protocol": "tcp"}],
                     "note": "Im ersten Assistenten Konto und Gerätenamen einrichten. Synchronisierte Ordner ausschließlich unter /sync auswählen, damit sie im gewählten NAS-Datenordner bleiben. Funktionsumfang und Lizenzbedingungen von Resilio beachten."},
    "smokeping": {"name": "SmokePing", "description": "Netzwerklatenz und Paketverluste über längere Zeit als Diagramm verfolgen.",
                  "category": "Netzwerk", "color": "#729db0", "symbol": "SP", "port": 80,
                  "image": "lscr.io/linuxserver/smokeping:latest", "mount": "/data", "memory": "512m", "default_port": 8099, "verified": "2026-10-02",
                  "note": "Diagramme unter /smokeping/smokeping.cgi öffnen. Zielgeräte in der Datei Targets im App-Konfigurationsordner festlegen und die App neu starten. Erste Messwerte können etwa zehn Minuten benötigen. Der ausgewählte Datenordner speichert die Messhistorie."},
    "xbackbone": {"name": "XBackBone", "description": "Screenshots und Dateien hochladen, verwalten und als Links teilen.",
                  "category": "Dateien", "color": "#518ab8", "symbol": "XB", "port": 80,
                  "image": "lscr.io/linuxserver/xbackbone:latest", "mount": None, "memory": "1g", "default_port": 8101, "verified": "2026-10-02",
                  "note": "Im Assistenten ein Administratorkonto anlegen; für eine eigenständige Installation SQLite und lokalen Dateispeicher wählen. Uploads und Einstellungen bleiben im App-Konfigurationsordner gespeichert. Für ShareX und andere Clients anschließend einen eigenen Upload-Token erzeugen."},
    "pyload-ng": {"name": "pyLoad", "description": "Dateidownloads mit Warteschlange und passenden Anbieter-Erweiterungen verwalten.",
                  "category": "Downloads", "color": "#458fc4", "symbol": "py", "port": 8000,
                  "image": "lscr.io/linuxserver/pyload-ng:latest", "mount": "/downloads", "memory": "1g", "default_port": 8100, "verified": "2026-10-02",
                  "note": "Standardzugang nach der ersten Anmeldung ändern. Als Downloadordner /downloads wählen. Anbieter-Zugangsdaten bei Bedarf in pyLoad selbst einrichten; der optionale Click'N'Load-Port wird von dieser Vorlage nicht veröffentlicht."},
})

# Public first-login guidance only. User-selected passwords, API keys and the
# temporary passwords from container logs must never enter catalog responses.
# 'default' means a documented initial account, not the current app credentials.
_FIRST_LOGINS = {
    "jellyfin": ("setup", "Beim ersten Öffnen im Assistenten deinen eigenen Administratornamen und ein Passwort festlegen. Es gibt kein festes Standardpasswort."),
    "syncthing": ("setup", "Die neue Oberfläche ist zunächst ohne Anmeldung erreichbar. Unter Aktionen → Einstellungen → GUI deinen eigenen Benutzernamen und ein Passwort setzen."),
    "nextcloud": ("setup", "Im ersten Einrichtungsassistenten Administratorname und Passwort selbst festlegen. Für kleine Installationen kann SQLite gewählt werden; es gibt keine festen Titan-Zugangsdaten."),
    "heimdall": ("none", "Die Oberfläche ist zunächst ohne Anmeldung erreichbar. Es gibt keinen Standardzugang. Optionalen Zugriffsschutz nach der LinuxServer-Anleitung einrichten."),
    "freshrss": ("setup", "Im Einrichtungsassistenten Datenbank und erstes Benutzerkonto mit eigenem Passwort anlegen. SQLite ist ohne zusätzlichen Datenbankdienst verfügbar."),
    "calibre-web": ("default", "Zuerst /books als Calibre-Bibliothek mit metadata.db auswählen. Mit dem initialen Standardkonto anmelden und dessen Passwort sofort ändern.", "admin", "admin123"),
    "prowlarr": ("setup", "Beim ersten Öffnen die Authentifizierung aktivieren und eigenen Benutzernamen sowie Passwort festlegen. Es gibt kein festes Standardkonto."),
    "radarr": ("setup", "Beim ersten Öffnen die Authentifizierung aktivieren und eigenen Benutzernamen sowie Passwort festlegen. Es gibt kein festes Standardkonto."),
    "sonarr": ("setup", "Beim ersten Öffnen die Authentifizierung aktivieren und eigenen Benutzernamen sowie Passwort festlegen. Es gibt kein festes Standardkonto."),
    "lidarr": ("setup", "Beim ersten Öffnen die Authentifizierung aktivieren und eigenen Benutzernamen sowie Passwort festlegen. Es gibt kein festes Standardkonto."),
    "bazarr": ("setup", "Zunächst ohne Anmeldung öffnen. Unter Settings → General → Security die Authentifizierung aktivieren und eigenen Benutzernamen sowie Passwort setzen."),
    "dokuwiki": ("setup", "Nach dem ersten Start /install.php an die App-Adresse anhängen. Dort ein Administratorkonto mit eigenem Passwort anlegen und danach die App neu starten."),
    "kavita": ("setup", "Beim ersten Öffnen im Einrichtungsassistenten deinen eigenen Administratornamen und ein Passwort festlegen. Es gibt keinen Standardzugang."),
    "qbittorrent": ("generated", "Das temporäre Passwort für admin steht nach dem Start unter App verwalten → Protokoll. Danach unter Einstellungen → Weboberfläche einen eigenen Zugang setzen; andernfalls entsteht bei jedem Neustart ein neues Passwort.", "admin"),
    "transmission": ("install", "Mit dem bei der Titan-Installation dieser App festgelegten Benutzernamen und Passwort anmelden. Diese Vorlage verwendet keinen festen Standardzugang."),
    "code-server": ("install", "Das bei der Titan-Installation dieser App festgelegte Passwort eingeben. Die Code-Server-Anmeldung benötigt keinen Benutzernamen."),
    "librespeed": ("install", "Die Messseite benötigt keine Anmeldung. /results/stats.php mit dem bei der Titan-Installation festgelegten Passwort öffnen, um gespeicherte Ergebnisse einzusehen; kein Benutzername erforderlich."),
    "grocy": ("default", "Mit dem initialen Standardkonto anmelden und das Passwort sofort in den Benutzereinstellungen ändern.", "admin", "admin"),
    "pairdrop": ("none", "Keine Anmeldung und keine Standardzugangsdaten. Geräte öffnen die App und werden über Geräteauswahl beziehungsweise Kopplung verbunden."),
    "jackett": ("setup", "Zunächst ohne Anmeldung öffnen. In der Oberfläche ein Administrator-Passwort festlegen, bevor du Indexer-Zugangsdaten einträgst. Es gibt kein festes Standardkonto."),
    "sabnzbd": ("setup", "Im Einrichtungsassistenten deinen Usenet-Zugang festlegen. Unter Config → General → Security Benutzernamen und Passwort für die Weboberfläche einrichten; kein festes Standardkonto."),
    "wikijs": ("setup", "Beim ersten Öffnen im Assistenten Administrator-E-Mail-Adresse und eigenes Passwort festlegen. SQLite ist in der Titan-Vorlage bereits ausgewählt."),
    "grav": ("setup", "Nach dem Start /admin an die App-Adresse anhängen und dort das erste Administratorkonto mit eigenem Passwort erstellen."),
    "mstream": ("setup", "Die neue Konfiguration enthält zunächst kein Benutzerkonto. Benutzer mit eigenem Passwort in der App beziehungsweise in /config/config.json einrichten. Es gibt kein festes Standardpasswort."),
    "cops": ("none", "Der Bücherkatalog ist zunächst ohne Anmeldung lesbar. Es gibt keinen Standardzugang. Eigenen Zugriffsschutz in /config/config/local.php nach der offiziellen Anleitung einrichten."),
    "duplicati": ("install", "Mit dem bei der Titan-Installation festgelegten Web-Passwort anmelden; kein Benutzername erforderlich. Der Schlüssel für App-Einstellungen und die spätere Backup-Passphrase sind separate Angaben."),
    "changedetection": ("setup", "Die neue Oberfläche ist zunächst ohne Anmeldung erreichbar. Unter Settings → General im Passwortfeld ein eigenes Passwort setzen. Es gibt keinen festen Benutzernamen oder Standardzugang."),
    "deluge": ("default", "Mit dem initialen Standardpasswort anmelden; die Weboberfläche fragt üblicherweise nur nach dem Passwort. Unter Preferences → Interface → Password sofort ein eigenes Passwort setzen.", "admin", "deluge"),
    "emby": ("setup", "Beim ersten Öffnen im Assistenten dein eigenes Administratorkonto und Passwort erstellen. Es gibt keinen festen Standardzugang."),
    "lazylibrarian": ("setup", "Zunächst ohne Anmeldung öffnen. Unter Config → Interface → Access Control einen eigenen Web-Benutzernamen und ein Passwort setzen. Erst danach bei Bedarf Benutzerkonten aktivieren; sonst kann dort admin / admin als initiales Konto entstehen."),
    "mylar3": ("setup", "Zunächst ohne Anmeldung öffnen. Über das Zahnrad die Konfiguration öffnen und einen eigenen Benutzernamen sowie Passwort für die Weboberfläche festlegen."),
    "nginx": ("none", "Der Webserver hat keine grafische Anmeldung und kein Standardkonto. Veröffentlichte Seiten sind zunächst ohne Anmeldung erreichbar; Zugriffsschutz bei Bedarf in der Nginx-Konfiguration einrichten."),
    "nzbget": ("install", "Mit dem bei der Titan-Installation dieser App festgelegten Benutzernamen und Passwort anmelden. Titan ersetzt den Image-Standardzugang durch deine eigenen Angaben."),
    "nzbhydra2": ("setup", "Zunächst ohne Anmeldung öffnen. Unter Config → Authorization die Authentifizierung auswählen und eigene Benutzer mit Passwort anlegen. Es gibt kein festes Standardkonto."),
    "ombi": ("setup", "Im ersten Einrichtungsassistenten deinen eigenen Administratorzugang erstellen. Ein Plex-Konto kann alternativ eingebunden werden; es gibt keinen festen Standardzugang."),
    "raneto": ("default", "Mit dem initialen Standardkonto anmelden. Benutzername und Passwort sofort in /config/config/config.js ändern und die App neu starten; der Webeditor ändert diese Grundeinstellungen nicht.", "admin", "password"),
    "tautulli": ("setup", "Im ersten Assistenten einen eigenen Tautulli-Benutzernamen und ein Passwort erstellen und anschließend dein Plex-Konto verbinden. Es gibt keinen festen Standardzugang."),
    "ubooquity": ("setup", "Zuerst die Adresse des bei Installation gewählten Administrationsports (Vorauswahl 2203) mit /ubooquity/admin öffnen und dort ein eigenes Admin-Passwort setzen. Leserzugänge und Bibliotheken anschließend in dieser Verwaltung anlegen."),
    "resilio-sync": ("setup", "Beim ersten Öffnen deinen eigenen Benutzernamen und ein Passwort für die Weboberfläche festlegen und einen Gerätenamen wählen. Es gibt keinen festen Standardzugang."),
    "smokeping": ("none", "Die Diagrammseite /smokeping/smokeping.cgi ist zunächst ohne Anmeldung erreichbar. Es gibt keinen Standardzugang; optionalen HTTP-Zugriffsschutz in der App-Konfiguration einrichten."),
    "xbackbone": ("setup", "Im ersten Installationsassistenten SQLite, lokalen Speicher und dein eigenes Administratorkonto mit Passwort wählen. Es gibt keinen festen Standardzugang."),
    "pyload-ng": ("default", "Mit dem initialen Standardkonto anmelden und das Passwort sofort in der Benutzerverwaltung ändern.", "pyload", "pyload"),
}
for _app_id, _login in _FIRST_LOGINS.items():
    _recipe = APPS[_app_id]
    _recipe["first_login"] = {
        "mode": _login[0], "instructions": _login[1], "verified": "2026-10-02",
        "documentation": f"https://docs.linuxserver.io/images/docker-{_recipe.get('upstream_name', _app_id)}/#application-setup",
        **({"username": _login[2]} if len(_login) > 2 else {}),
        **({"password": _login[3]} if len(_login) > 3 else {}),
    }
_cache = {"time": 0, "images": {}, "error": None}


def validate_options(app_id, options=None):
    if app_id not in APPS:
        raise Error("App-Vorlage ist nicht verfügbar.")
    options = {} if options is None else options
    schema = APPS[app_id].get("install_schema", [])
    if not isinstance(options, dict) or set(options) - {field["key"] for field in schema}:
        raise Error("App-Einstellungen enthalten unbekannte Felder.")
    result = {}
    for field in schema:
        value = options.get(field["key"], field.get("default"))
        if value is None and not field.get("required"):
            continue
        if field["type"] == "number":
            value = integer(value, field["min"], field["max"])
        else:
            if not isinstance(value, str) or not field.get("min_length", 1) <= len(value) <= field["max_length"] or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise Error(f"{field['label']} ist erforderlich oder hat ein ungültiges Format.")
            if field["key"] == "username" and not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", value):
                raise Error("Benutzername darf nur Buchstaben, Ziffern und _.@- enthalten.")
            if field.get("pattern") and not re.fullmatch(field["pattern"], value):
                raise Error(f"{field['label']} darf nur Buchstaben und Ziffern enthalten.")
        result[field["key"]] = value
    return result


def published_ports(app_id, port, options=None, host_mode=False):
    """Return trusted publications, including configurable TCP/UDP peer ports."""
    options = validate_options(app_id, options)
    port = integer(port, 1 if host_mode else 1024, 65535)
    app = APPS[app_id]
    if host_mode and not app.get("dynamic_web_port") and port != app["port"]:
        raise Error(f"Im Host-Netzwerk verwendet diese App direkt Port {app['port']}; Portumleitung ist nur in Bridge-Netzwerken möglich.")
    result = [{"host": port, "target": port if app.get("dynamic_web_port") else app["port"], "protocol": "tcp"}]
    for extra in app.get("extra_ports", []):
        peer = options[extra["option"]] if "option" in extra else extra["port"]
        if peer == port:
            raise Error("Webport und Verbindungsport müssen verschieden sein.", 409)
        result.append({"host": peer, "target": extra.get("target", peer), "protocol": extra["protocol"]})
    if host_mode and any(item["host"] != item["target"] for item in result):
        raise Error("Im Host-Netzwerk müssen alle Verbindungsports den internen App-Ports entsprechen.")
    return result


def _image_metadata(images):
    """Keep optional remote display fields separate from local deployment recipes."""
    if not isinstance(images, list):
        raise ValueError("Invalid LinuxServer image list")
    metadata = {}
    upstream_ids = {recipe.get("upstream_name", app_id): app_id for app_id, recipe in APPS.items()}
    for item in images:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or item["name"] not in upstream_ids:
            continue
        version = item.get("version")
        architectures = item.get("architectures")
        metadata[upstream_ids[item["name"]]] = {
            "version": version if isinstance(version, str) and 0 < len(version) <= 128 else "latest",
            "deprecated": item.get("deprecated") is True,
            "architectures": [entry["arch"] for entry in architectures[:32]
                              if isinstance(entry, dict) and isinstance(entry.get("arch"), str)
                              and 0 < len(entry["arch"]) <= 32] if isinstance(architectures, list) else [],
        }
    return metadata


def catalog(refresh=False):
    if refresh or time.time() - _cache["time"] > 21600:
        try:
            request = urllib.request.Request(
                "https://api.linuxserver.io/api/v1/images?include_config=false&include_deprecated=false",
                headers={"User-Agent": "Titan/0.1"})
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read(8 * 1024 * 1024))
            images = data["data"]["repositories"]["linuxserver"]
            _cache.update(time=time.time(), images=_image_metadata(images), error=None)
        except Exception:
            _cache.update(time=time.time(), error="LinuxServer-Katalog momentan nicht erreichbar. Lokale Vorlagen bleiben verfügbar.")
    apps = []
    for app_id, recipe in APPS.items():
        remote = _cache["images"].get(app_id, {})
        public_recipe = {key: value for key, value in recipe.items() if key != "environment"}
        public_recipe["install_schema"] = [{key: value for key, value in field.items() if key != "env"}
                                           for field in recipe.get("install_schema", [])]
        apps.append({**public_recipe, "id": app_id, "version": remote.get("version", "latest"),
                     "deprecated": remote.get("deprecated", False),
                     "architectures": remote.get("architectures", []),
                     "documentation": f"https://docs.linuxserver.io/images/docker-{recipe.get('upstream_name', app_id)}/"})
    return {"apps": apps, "source": "LinuxServer.io", "error": _cache["error"]}


def compose(app_id, directory, uid, gid, port, data_path, options=None, network=None):
    if app_id not in APPS:
        raise Error("App-Vorlage ist nicht verfügbar.")
    app = APPS[app_id]
    options = validate_options(app_id, options)
    volumes = ([{"type": "bind", "source": f"{directory}/config", "target": "/config",
                 "bind": {"create_host_path": False, "selinux": "Z"}}] if app.get("config_mount", True) else [])
    if app["mount"]:
        volumes.append({"type": "bind", "source": str(data_path), "target": app["mount"],
                        "bind": {"create_host_path": False}})
    from .app_networks import apply_selection, selection
    network = selection(network)
    publications = published_ports(app_id, port, options, host_mode=network["mode"] == "host")
    ports = [f"{item['host']}:{item['target']}" + (f"/{item['protocol']}" if index else "")
             for index, item in enumerate(publications)]
    environment = {"PUID": str(uid), "PGID": str(gid), "TZ": "Europe/Berlin", **app.get("environment", {})}
    for field in app.get("install_schema", []):
        if field["key"] in options and "env" in field:
            # Compose expands '$' even in JSON string values. Escape it so the
            # user's password is passed literally rather than read from host env.
            environment[field["env"]] = str(options[field["key"]]).replace("$", "$$")
    if app.get("dynamic_web_port"):
        environment["WEBUI_PORT"] = str(port)
    return apply_selection({"services": {app_id: {
        "image": app["image"], "container_name": "titan-" + app_id,
        "environment": environment,
        "volumes": volumes, "ports": ports, "restart": "unless-stopped",
        "mem_limit": app["memory"], "cpus": 2,
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
        "labels": {"io.titan.managed": "true", "io.titan.app": app_id},
    }}}, app_id, network)
