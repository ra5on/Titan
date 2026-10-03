# Eigene AppStores und Hardware-Erweiterungen

Verfügbar mit dem signierten Systemupdate **v0.4.7-alpha.1**. Das veröffentlichte 0.4.6-Installationsimage enthält diese Änderungen noch nicht; nach der Installation über den Alpha-Kanal aktualisieren.

Im App Store öffnet **AppStores** die Quellenverwaltung. Ein Administrator kann eine öffentliche JSON-Datei auf `raw.githubusercontent.com` hinzufügen und muss dem Herausgeber ausdrücklich vertrauen. Titan lädt maximal 1 MiB, erlaubt keine Weiterleitungen und speichert die geprüften Vorlagen lokal. Ein Store-Wechsel verändert keine installierte Anwendung. Entfernen ist erst nach Entfernung seiner Apps möglich; deren Daten bleiben bestehen.

Das erste Format unterstützt einen Container je App. Ports, Umgebungsvariablen, Speicherfreigabe und Bridge-/Host-/eigenes Docker-Netz werden vor der Installation eingestellt. Vorgaben stehen bereits im Formular. Geheimnisse werden erst dort eingegeben und separat mit privaten Dateirechten gespeichert. Zusätzliche Ports können einzeln geändert werden. Der Konfigurationsmount ist `/config`; `config_mount: false` deaktiviert ihn. Der Datenmount wird durch `mount` festgelegt, `null` deaktiviert ihn. NAS-Pfade kommen aus Titan, nicht aus dem fremden Store.

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

`login_note` ist verpflichtend: Standardzugang, eigenes Konto oder Ort eines automatisch erzeugten Passworts beschreiben. Der Hinweis erscheint vor der Installation. Pro Store maximal 100 Apps, insgesamt maximal 20 Stores. Titan unterstützt keine privilegierten Container, Docker-Socket-Mounts, freie Hostgeräte, Startskripte oder mehrteiligen Compose-Stacks aus diesem Format. Unbekannte Felder werden abgewiesen. Kataloge werden nicht automatisch aktualisiert. Store-Einträge bleiben auf der gemeinsamen Datenpartition über Systemupdates erhalten; das Konfigurations-Exportformat enthält sie derzeit nicht.

## CasaOS / ZimaOS als Referenz

Die offizielle [ZimaOS-Dokumentation](https://www.zimaspace.com/docs/developer/docker-app-publishing) beschreibt Docker Compose mit zusätzlichen `x-casaos`-Metadaten und Installationshinweisen. Das Bedienprinzip – Quellen hinzufügen, App wählen, Vorgaben prüfen, installieren – dient als Referenz. Titan verwendet eigenen Code und ein bewusst begrenztes Schema; CasaOS-/ZimaOS-Archive sind **nicht direkt importierbar**.

[CasaOS-AppManagement](https://github.com/IceWhaleTech/CasaOS-AppManagement/blob/main/LICENSE) und [CasaOS-AppStore](https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/LICENSE) führen Apache 2.0. Bei tatsächlicher Übernahme von Code oder Vorlagen sind unter anderem Lizenz-, Copyright- und gegebenenfalls NOTICE-Hinweise sowie Kennzeichnung von Änderungen zu erhalten. Die Titan-Nichtkommerziell-Lizenz ersetzt diese Fremdlizenzen nicht. Container, Logos und andere Assets haben eigene Bedingungen. Das öffentliche [ZimaOS-Repository](https://github.com/IceWhaleTech/ZimaOS) ist keine pauschale Lizenzfreigabe für alle ZimaOS-Komponenten. Für diese Erweiterung wurden keine fremden Implementierungen oder Logos übernommen.

## VM und GPU

IMG, RAW und QCOW2 werden über den bestehenden geprüften Image-Import als eigenständige virtuelle Disk kopiert; die Quelle bleibt erhalten. Der vorhandene VM-Typ verwendet Legacy-BIOS. UEFI-only-Gastimages benötigen eine noch ausstehende Firmware-Erweiterung und sind damit nicht automatisch bootfähig. P-/E-Kerne erscheinen nur, wenn Linux die Topologie meldet; Proxmox kann diese Information vor dem Gast verbergen.

Unter VM → Details → **USB-Geräte** können bis zu acht eindeutig erkannte Geräte ausgewählt werden. Änderungen erfordern eine ausgeschaltete VM. Speicher, Hubs und Netzwerkgeräte bleiben beim NAS. Doppelte Vendor-/Product-IDs werden abgewiesen; port-/seriennummernbasierte Zuordnung und Hotplug sind noch offen. Die Auswahl wird in libvirt gespeichert, beim Titan-Start der VM erneut geprüft und konkurrierende Zuordnungen werden abgewiesen. Externe Änderungen mit virsh oder Autostart umgehen diese zusätzliche Titan-Prüfung; libvirt prüft weiterhin die Geräteverfügbarkeit. In Proxmox muss das Gerät zuerst der Titan-VM zugewiesen werden. VM-Wiederherstellungen übernehmen keine USB-Zuordnungen.

Unter **Einstellungen → Systemkomponenten** zeigt Titan PCI-GPUs, Gerätekennung, gebundenen Kernel-Treiber und VFIO-Reservierung. Ein aktiver Treiber beweist keine funktionierende Medienbeschleunigung. Eine separate Treiberinstallation ist noch nicht implementiert; insbesondere NVIDIA benötigt einen zur GPU und zum Kernel passenden, getesteten Treiber im signierten Systemupdate. Kein Live-`apt install` verändert dafür den aktuellen A/B-Systemstand.

Die neuen Verwaltungswege sind Alpha. Tests mit realen USB-Geräten, GPU-Hardware und einem zusätzlichen Store-Container müssen vor Beta folgen.
