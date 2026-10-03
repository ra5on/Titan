# Eigene AppStores und Hardware-Erweiterungen

Ab **0.4.9-alpha.1** ist LinuxServer.io der Standardstore mit 73 offline gebündelten Vorlagen. **AppStores** verwaltet mehrere Quellen, Aktivierung und manuelle Aktualisierung. Der Store-Filter zeigt eine oder alle aktiven Quellen. Deaktivieren verändert installierte Apps nicht.

Bekannte Quellen sind LinuxServer.io (offizielle API), CasaOS/IceWhale, BigBear und der LinuxServer-Community-Store. CasaOS-GitHub-Repositories werden über kleine Compose-Dateien eingelesen; Logos und große Repository-Archive sind dafür unnötig. Alternativ werden GitHub-ZIP-Archive von `codeload.github.com` und Titan-JSON von `raw.githubusercontent.com` unterstützt. Ein Administrator bestätigt beim Hinzufügen sein Vertrauen in den Herausgeber.

Downloads sind begrenzt: 8 MiB API-Daten, 1 MiB Titan-JSON, 96 MiB ZIP, 512 MiB deklarierter ZIP-Inhalt. Der gezielte Repository-Import begrenzt jede Vorlage auf 128 KiB und insgesamt 16 MiB. Keine Weiterleitungen, YAML-Aliase, beliebigen Hostpfade oder direkte Compose-Ausführung. Inkompatible Vorlagen werden mit Grund aufgelistet. Importierte Vorlagen behalten einen direkten Dokumentationslink; unbestätigte Anmeldedaten sind als solche erkennbar. Die bisherigen 42 Vorlagen behalten ihre geprüften Hinweise.

Das einfache Titan-Format unterstützt einen Container je App. Ab **0.4.11-alpha.1** übersetzt der CasaOS-Adapter auch Verbünde mit bis zu acht Containern, statischen Kommandos, Healthchecks und Abhängigkeiten in verwaltete Titan-Vorlagen. Verbünde verwenden ihr eigenes isoliertes Standardnetz; Einzelcontainer können andere unterstützte Netze verwenden. Ports, Umgebungsvariablen, Speicherfreigabe und Bridge-/Host-/eigenes Docker-Netz werden vor der Installation eingestellt. Vorgaben stehen bereits im Formular. Geheimnisse werden erst dort eingegeben und separat mit privaten Dateirechten gespeichert. Zusätzliche Ports können einzeln geändert werden. Der Konfigurationsmount ist `/config`; `config_mount: false` deaktiviert ihn. Der Datenmount wird durch `mount` festgelegt, `null` deaktiviert ihn. NAS-Pfade kommen aus Titan, nicht aus dem fremden Store.

## Format

Beispielstruktur; Image und Dokumentationsadresse durch die eigene getestete Anwendung ersetzen:

```json
{
  "schema": 1,
  "name": "Mein Store",
  "apps": [{
    "id": "meine-app",
    "name": "Meine App",
    "description": "Beschreibung der Anwendung",
    "image": "example/my-app:1.0",
    "port": 8080,
    "default_port": 8080,
    "mount": "/data",
    "memory": "1g",
    "documentation": "https://example.org/docs",
    "login_note": "Beim ersten Aufruf das eigene Administratorkonto anlegen.",
    "ports": [{"target": 9000, "published": 9000, "protocol": "udp"}],
    "settings": [{"env": "LANGUAGE", "label": "Sprache", "default": "de", "secret": false}]
  }]
}
```

`login_note` ist verpflichtend: Standardzugang, eigenes Konto oder Ort eines automatisch erzeugten Passworts beschreiben. Der Hinweis erscheint vor der Installation. Pro Store maximal 400 Apps, insgesamt maximal 20 Stores. Titan unterstützt keine privilegierten Container, Docker-Socket-Mounts, freie Hostgeräte, Startskripte oder ungeprüften Compose-Dateien aus diesem Format. Unbekannte Felder werden abgewiesen. Kataloge werden nicht automatisch aktualisiert. Store-Einträge bleiben auf der gemeinsamen Datenpartition über Systemupdates erhalten; das Konfigurations-Exportformat enthält sie derzeit nicht.

## CasaOS / ZimaOS als Referenz

Die offizielle [ZimaOS-Dokumentation](https://www.zimaspace.com/docs/developer/docker-app-publishing) beschreibt Docker Compose mit zusätzlichen `x-casaos`-Metadaten und Installationshinweisen. Das Bedienprinzip – Quellen hinzufügen, App wählen, Vorgaben prüfen, installieren – dient als Referenz. Titan verwendet eigenen Code und ein bewusst begrenztes Schema; Kompatible CasaOS-/ZimaOS-Vorlagen werden übersetzt; nicht unterstützte Hostrechte oder dynamische Kommandos werden mit Begründung ausgelassen.

[CasaOS-AppManagement](https://github.com/IceWhaleTech/CasaOS-AppManagement/blob/main/LICENSE) und [CasaOS-AppStore](https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/LICENSE) führen Apache 2.0. Bei tatsächlicher Übernahme von Code oder Vorlagen sind unter anderem Lizenz-, Copyright- und gegebenenfalls NOTICE-Hinweise sowie Kennzeichnung von Änderungen zu erhalten. Die Titan-Nichtkommerziell-Lizenz ersetzt diese Fremdlizenzen nicht. Container, Logos und andere Assets haben eigene Bedingungen. Das öffentliche [ZimaOS-Repository](https://github.com/IceWhaleTech/ZimaOS) ist keine pauschale Lizenzfreigabe für alle ZimaOS-Komponenten. Für diese Erweiterung wurden keine fremden Implementierungen oder Logos übernommen.

## VM und GPU

IMG, RAW und QCOW2 werden über den bestehenden geprüften Image-Import als eigenständige virtuelle Disk kopiert; die Quelle bleibt erhalten. Der vorhandene VM-Typ verwendet Legacy-BIOS. UEFI-only-Gastimages benötigen eine noch ausstehende Firmware-Erweiterung und sind damit nicht automatisch bootfähig. P-/E-Kerne erscheinen nur, wenn Linux die Topologie meldet; Proxmox kann diese Information vor dem Gast verbergen.

Unter VM → Details → **USB-Geräte** können bis zu acht eindeutig erkannte Geräte ausgewählt werden. Änderungen erfordern eine ausgeschaltete VM. Speicher, Hubs und Netzwerkgeräte bleiben beim NAS. Doppelte Vendor-/Product-IDs werden abgewiesen; port-/seriennummernbasierte Zuordnung und Hotplug sind noch offen. Die Auswahl wird in libvirt gespeichert, beim Titan-Start der VM erneut geprüft und konkurrierende Zuordnungen werden abgewiesen. Externe Änderungen mit virsh oder Autostart umgehen diese zusätzliche Titan-Prüfung; libvirt prüft weiterhin die Geräteverfügbarkeit. In Proxmox muss das Gerät zuerst der Titan-VM zugewiesen werden. VM-Wiederherstellungen übernehmen keine USB-Zuordnungen.

Unter **Einstellungen → Systemkomponenten** zeigt Titan PCI-GPUs, Gerätekennung, gebundenen Kernel-Treiber und VFIO-Reservierung. Ein aktiver Treiber beweist keine funktionierende Medienbeschleunigung. Eine separate Treiberinstallation ist noch nicht implementiert; insbesondere NVIDIA benötigt einen zur GPU und zum Kernel passenden, getesteten Treiber im signierten Systemupdate. Kein Live-`apt install` verändert dafür den aktuellen A/B-Systemstand.

Die neuen Verwaltungswege sind Alpha. Tests mit realen USB-Geräten, GPU-Hardware und einem zusätzlichen Store-Container müssen vor Beta folgen.

## Rollback-Kompatibilität

Neue Quellen liegen in `app-store-sources.json`. Ein vorhandenes `app-stores.json` wird beim ersten Zugriff übernommen, aber nicht mit neuen Formaten überschrieben. Ältere Systemversionen ignorieren die neue Datei und können ihren Verwaltungsdienst weiter starten. Neu importierte Apps benötigen zur Verwaltung die neuere Titan-Version; deren Container und Daten werden durch einen OS-Rollback nicht entfernt.

## USB/GPU und Speicher ab 0.4.11

Das Installationsformular bietet erkannte USB-/serielle Geräte sowie GPU-Rendergeräte einzeln an. NVIDIA setzt einen bereits installierten Treiber und eine funktionsfähige NVIDIA-Container-Runtime voraus. Geräte werden nicht durch privilegierte Container ersetzt. Ein abgezogenes Gerät verhindert neue Starts; Stoppen und Entfernen bleiben möglich. Physische Hardware ist in der QEMU-Releaseprüfung nicht verfügbar.

Importierte Mounts werden auf private Titan-App-Verzeichnisse abgebildet. Ein erkennbarer Nutzdaten-Mount (`/data`, `/media`, `/downloads`, `/files`, `/storage`) verwendet die gewählte Freigabe bzw. das eigene Datenverzeichnis; dieselbe Quellzuordnung bleibt im Verbund geteilt. Datenbanken und zusätzliche Konfigurations-Mounts erhalten getrennte private Unterordner.

Neue Vorlagen werden bei bereits hinzugefügten Stores erst nach **AppStore aktualisieren** eingelesen. Ab 0.4.11 werden erweiterte Quellen in einer eigenen Registry gespeichert; die vorherige Registry bleibt für den System-Rollback erhalten. Nach einem Rollback zeigt die ältere Oberfläche ihren bisherigen Store-Stand. Neue App-Daten bleiben auf der Datenpartition erhalten.
