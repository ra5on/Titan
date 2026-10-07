# Titan 0.5.9 Alpha

Titan 0.5.9 ergänzt eigene Compose-Apps, überarbeitet Dateimanager und Konsolen und behebt flackernde Widgets und VM-Ansichten. Installationsimage und signiertes Update werden erst nach erfolgreichen Release-Prüfungen veröffentlicht. **Titan bleibt Alpha; zuerst mit Testdaten verwenden.**

## Apps

- **Immich:** vollständiger Verbund aus Server, Machine Learning, PostgreSQL und Valkey mit an feste Digests gebundenen Images. Die Datenbank erhält 2 GiB; die gesamten Rezeptlimits betragen 6,25 GiB. Lokaler Linux-Speicher und CPU-Anforderungen werden geprüft.
- **AdGuard Home:** eigenes Compose-Rezept, Prüfung von DNS- und Webports und tatsächlicher Webbereitschaft. Den Einrichtungsassistenten anschließend in AdGuard abschließen und Router beziehungsweise Clients auf den DNS-Server umstellen.
- **Tailscale:** Auth-Key, eigener Gerätename, optionales NAS-Ziel und Subnet-Routing für ausdrücklich gewählte private CIDRs. Das isolierte Userspace-Rezept verändert keine Host-Netzwerkeinstellungen. TCP und UDP werden unterstützt; Ping eingeschränkt, andere IP-Protokolle nicht. Routenfreigabe und Zugriffsregeln im Tailscale-Konto bleiben erforderlich.
- Alle vier eigenen Apps einschließlich **Cloudflare Tunnel** nutzen einen auf dem NAS gespeicherten Installationsverlauf. Fehler, tatsächliche Schritte und Wiederaufnahme bleiben sichtbar. Externe BigBear-Katalogdownloads bleiben entfernt; vorhandene ältere Apps und ihre Daten bleiben verwaltbar.

## Dateien und Desktop

- Widgets behalten beim Aktualisieren ihre Karten und Bedienelemente. Messwerte ändern sich innerhalb der vorhandenen Ansicht.
- Mehrere Dateien lassen sich per Drag-and-drop hochladen. Der Upload behält seinen Abbrechen-Button und den ursprünglich gewählten Zielordner, auch wenn die Ansicht wechselt.
- Private Teilstücke, serialisierter Abbruch und atomarer Abschluss verhindern sichtbare halbe Dateien und das Überschreiben vorhandener Ziele. Abbruch beendet auch die verbleibende Warteschlange; fertige Dateien bleiben erhalten.
- Kompakter Dateimanager mit optionalem Detailbereich, ausgeblendeter leerer Auswahlleiste und passenden Datei-/Ordneraktionen per Rechtsklick, Langdruck und Tastatur.
- Schnellaktionen in weiteren Anwendungen delegieren an vorhandene geprüfte Aktionen; deaktivierte Aktionen werden dadurch nicht freigeschaltet. Desktop-Verknüpfungen sind direkt aus Appfenstern erreichbar.
- Neue Anmeldung, kleinere Abstände, zusammenhängende Scrollbereiche und Entfernung nachweislich ungenutzter Frontendmodule, alter Store-Styles und Imports.

## VMs und Konsolen

- VM-Anzeigenamen erlauben Großbuchstaben, Leerzeichen und Umlaute. Interne Kennungen und Dateipfade bleiben getrennt und begrenzt. Das gilt auch beim Klonen und Wiederherstellen als neue VM.
- VM-Snapshots und Sicherungen sind für laufende VMs mit ausdrücklich bestätigtem geordnetem Herunterfahren erreichbar. Titan erzwingt kein Ausschalten.
- Ein vollständiger Datenträger-Snapshot lässt sich als neue, ausgeschaltete VM wiederherstellen: unabhängige QCOW2-Dateien, eigene UUID und MAC-Adressen sowie gesicherte UEFI-Variablen. Die Quelle bleibt erhalten. Gerätepässe werden nicht automatisch übernommen. Dies ist kein RAM-Snapshot.
- Aktualisierungen erhalten Ansicht, Auswahl und Scrollposition. Die aktive VM-Konsole bleibt verbunden und wird nicht bei jedem Poll aus dem Dokument entfernt. Fehler erhalten die letzte Ansicht und zeigen eine Meldung.
- Gemeinsame Gestaltung für Titan-Terminal und noVNC-Konsole, Dunkel-/Hellmodus, kompakte Werkzeugleisten, Textzwischenablage und passende Tastatur-/Kontextaktionen. Einzelne VM-Konsolen und das Terminal können auf den Desktop gelegt werden.

## Docker und Updates

- Kompakte Docker-Kennzahlen, verlässliche Fehlerzustände und keine veralteten Messwerte bei fehlgeschlagenen Abfragen.
- Späte Logantworten öffnen keine geschlossenen Details erneut. Eine ausdrücklich angeforderte Aktualisierung geht während eines laufenden Polls nicht verloren.
- Bei jeder erfolgreichen Admin-Anmeldung läuft eine Updateprüfung im Hintergrund. Verfügbare Updates werden gemeldet; normale Konten und eingebettete Appfenster starten keine zusätzliche Prüfung.

## Installation und Prüfgrenzen

AMD64, UEFI/OVMF, Secure Boot aus, mindestens 8 GiB RAM und 64 GiB Festplatte. Das entpackte Image ist 48 GiB groß. Neuinstallationen öffnen unter `https://<NAS-IP>`; bestehende Installationen behalten ihre Ports. Mehrere Apps, Immich und VMs benötigen zusätzlichen Arbeitsspeicher und Datenplatz.

Die lokale Demo simuliert Hostfunktionen. Automatisierte Tests prüfen unter anderem Upload-Abbruch und Zielkonflikte, VM-Snapshot-Export mit echten QCOW2-Testdateien, Namen, Zwischenablagegrenzen und Aktualisierungsrennen. Wegwerf-Runner prüfen Compose-Laufzeit und Fehlerpfade. Der Release-Workflow ergänzt Boot-, Laufzeit- und A/B-Update-/Rollback-Prüfungen; Berichte gehören zu den Release-Dateien.

Echte Cloudflare-/Tailscale-Konten, öffentliche Domains, Tailscale-Routenfreigaben, Gast-Zwischenablage und die eigene Hardware benötigen weiterhin praktische Abnahme. Ein System-Rollback setzt gemeinsame App-Daten und Datenbanken nicht zurück. Unabhängige Sicherungen behalten.

TitanOS diente ausschließlich als visuelle Orientierung. Code und Assets wurden nicht übernommen.

[README mit Screenshots](../README.md) · [Apps](APP-STORES.md) · [VMs](PACKAGES-AND-VMS.md) · [Release und Prüfberichte](https://github.com/ra5on/Titan/releases/tag/v0.5.9-alpha.1)
