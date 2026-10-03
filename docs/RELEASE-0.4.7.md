# Titan 0.4.7-alpha.1 · Systemupdate

Signiertes A/B-Systemupdate für Titan 0.4.6-alpha.1 auf Debian. Kein erneuter Image-Import erforderlich.

## Installation

1. In Titan **Einstellungen → Updates & Rollback** den Kanal **Alpha** wählen.
2. **Nach Updates suchen**, Version **0.4.7-alpha.1** prüfen und installieren.
3. Nach erfolgreicher Vorbereitung den Neustart bestätigen.
4. Anschließend zeigt die Oberfläche **0.4.7**; der Systemupdate-Status führt die vollständige Version **0.4.7-alpha.1**.

Die Rückkehr zu 0.4.6 ist nach bestätigtem Systemstart im Rollback-Dropdown verfügbar. Nutzdaten werden durch Rollback nicht zurückgesetzt. Erst in 0.4.7 hinzugefügte AppStores bleiben gespeichert, können unter 0.4.6 jedoch nicht verwaltet werden. Vor einem Rollback deren Apps gegebenenfalls stoppen.

## Enthaltene Änderungen

- Eigene AppStores im Titan-JSON-Format hinzufügen und entfernen; lokal gespeicherte, geprüfte Vorlagen mit Herkunftsanzeige.
- Zusätzliche Ports und Umgebungsvariablen einschließlich privater Passwortfelder vor der App-Installation einstellen. Netzwerk und Datenfreigabe bleiben auswählbar.
- USB-Geräte im VM-Dialog zuordnen und entfernen. Änderungen bei ausgeschalteter VM; keine NAS-Speicher, Hubs oder Netzwerkadapter, keine mehrdeutigen Gerätekennungen.
- PCI-GPUs, Modellnamen soweit verfügbar, aktiven Kernel-Treiber und VFIO-Zuordnung unter Systemkomponenten anzeigen.
- Angepasste Dialoge und korrigierte Debian-Bezeichnung. IMG-/QCOW2-Import und P-/E-Kernauswahl bleiben vorhanden.

Separate GPU-Treiberinstallation, UEFI-only-Gastimages und direkter Import kompletter CasaOS-/ZimaOS-Archive sind noch nicht umgesetzt. Details: [AppStores und Hardware](https://github.com/ra5on/Titan/blob/main/docs/APP-STORES.md).

## Prüfung und Alpha-Grenzen

Die Veröffentlichung setzt erfolgreiche Regressionstests, VM-Boot und NAS-Laufzeittests sowie den tatsächlichen Wechsel vom veröffentlichten **0.4.6-alpha.1-Image** auf 0.4.7 und zurück voraus. Der Test verwendet das per fest hinterlegter SHA256-Prüfsumme geprüfte alte Image mit unveränderter signierter Versionsidentität. Getestet werden Benutzer, Dateirechte, Testdateien, Plattenwachstum und Rückfall nach einem absichtlich fehlerhaften Start. `ab-test.json` und `runtime-test.json` enthalten die Ergebnisse. Nur der Downloadtransport des noch unveröffentlichten Kandidaten wird im Test lokal ersetzt; RAUC installiert und prüft das signierte Paket tatsächlich.

Tests mit realen USB-Geräten, GPUs und zusätzlichen Store-Anwendungen stehen noch aus. Das bleibt eine Alpha.

Für neue Installationen bleibt das [0.4.6-IMG](https://github.com/ra5on/Titan/releases/download/v0.4.6-alpha.1/titan-0.4.6-alpha.1-amd64.img.xz) verfügbar: **OVMF/UEFI, Secure Boot aus**, importierte Systemplatte als erstes Bootlaufwerk. Danach über den Alpha-Kanal aktualisieren. Dieses Release enthält bewusst kein neues Installationsimage.
