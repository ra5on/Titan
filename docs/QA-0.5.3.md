# Prüfnachweis · Titan 0.5.3 Alpha

Stand: 4. Oktober 2026. Diese Version ist in Prüfung und noch nicht als
signiertes Systemupdate veröffentlicht. Nach der Veröffentlichung werden hier
die tatsächlich ausgeführten GitHub- und Gastprüfungen verlinkt.

## Lokale Prüfungen

Gezielte Regressionen prüfen gemeinsame Speicherkennungen, mount- und
UUID-/GUID-gebundene Zugriffe, unveränderte Bestandsdaten, Offline-Sperren,
Standardauswahl, App-Pakete samt Datenbank und Cache, Docker-Datenordner sowie
Sicherungsziele. Ein echter temporärer TAR-Test prüft die Sicherung einer
ausgelagerten App-Konfiguration. Terminal und eigene Dienste werden auf die
neuen Privilegiengrenzen geprüft. Anmeldeschutz umfasst persistente Sperren,
Passwort-/TOTP-Fehler, HTTP-Status 429 und verbleibende Wartezeit.

Pipeline-Tests prüfen echte Ed25519-Signaturen, signierte Paketinventare,
eingefrorene Anwendungsquellen in einem erzeugten Debian-Paket und die
Release-Identität. Die abschließende vollständige lokale Python-Suite ist mit
1.480 Tests grün abgeschlossen; davon wurde ein Test wegen fehlender lokaler
Ext4-Werkzeuge übersprungen. Alle 44 JavaScript-Verhaltenssuiten sowie die
Syntaxprüfungen für 41 JavaScript-Dateien und die Bash-Skripte sind bestanden.
Nach diesem Prüflauf sind keine weiteren Quellkorrekturen vorgesehen.

## Browserprüfung

Für diesen Durchlauf steht kein steuerbarer Browser zur Verfügung. Die
JavaScript-Tests bestätigen Dropdowns, gespeicherte Auswahl, Offline-/Voll-Status,
Navigation und den gemeinsamen Updateablauf. Die neue Darstellung wurde in
diesem Durchlauf nicht tatsächlich auf Desktop oder Mobilgeräten bedient.
Die Bilder im README stammen aus der geprüften 0.5.2-Demo; sie belegen nicht
die neuen 0.5.3-Dialoge.

## Erforderliche Release-Prüfungen

Vor Veröffentlichung müssen die GitHub-CI, alle vier echten App-Pakete,
Debian-Boot/HTTPS/SMB/Docker/VM-Konsole sowie die neue echte Prüfung des
Anmeldeschutzes, der NAS-Datengrenze, des geladenen ZFS-Moduls samt
Speichergrenze und der Start-Sperre älterer eigener Rootdienste bestehen. Dazu
gehören die Gates `storage_components` und `custom_service_containment`.
Die echten GitHub- und Gastprüfungen stehen noch aus. Der separate A/B-Lauf muss
Update, Neustart, manuellen Rollback, Rückfall nach einem fehlerhaften Start
und Erhalt der Nutzdaten ausgehend vom veröffentlichten Installationsimage
bestätigen. Erst diese erfolgreichen Nachweise erlauben die Veröffentlichung.
Die tatsächliche Browser- und Mobilabnahme bleibt zusätzlich offen.

Zusätzliche ZFS-/Ext4-/XFS-Datenträger, reale USB-/GPU-Geräte und langfristiger
Lastbetrieb bleiben Bestandteil der Abnahme auf dem eigenen NAS. Betriebssystem-
Rollback ist keine Wiederherstellung von App-Datenbanken.
