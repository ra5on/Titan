# Benutzer, Gruppen und Sicherheitszentrum

Titan verwaltet persönliche Web- und SMB-Identitäten. Gruppenrechte gelten
serverseitig und werden bei Freigaben in die bestehenden Samba-Konfigurationen
und POSIX-ACLs übertragen. Webrechte werden bei jeder Anfrage und erneut vor
der Ausführung wartender Verwaltungsaktionen geprüft.

## Gruppen und wirksame Rechte

Unter **Benutzer → Gruppen und Rechte** lassen sich Gruppen erstellen,
Mitglieder auswählen und Anwendungen oder Freigaben zuweisen. Unter
**Benutzer bearbeiten → Rechte und Ordner** werden die wirksamen Rechte samt
Herkunft angezeigt. Ein ausdrücklich gesetztes Benutzerrecht überschreibt
Gruppenregeln. Ein Verweigern in einer Gruppe hat innerhalb der Gruppen
Vorrang; bei Freigaben gewinnt ansonsten Schreiben vor Lesen.

Ohne Gruppenregel dürfen normale Benutzer ihre freigegebenen Dateien nutzen.
Apps/Docker, VM-Verwaltung und Datensicherung sind standardmäßig gesperrt.
Administratoren behalten vollständigen Webzugriff. Apps/Docker und
VM-Verwaltung sind umfassende Verwaltungsberechtigungen für vertrauenswürdige
Benutzer, keine isolierten Mandanten. Systemupdates, Kontoänderungen,
Datenterminal und Konfigurationsexport bleiben Administratoraufgaben.
Delegierte Datensicherung ist zusätzlich auf die lesbaren Freigaben des
Benutzers beschränkt. Nur Sicherungen mit vollständig zugänglichen Quellen
werden angezeigt; Wiederherstellen verlangt Schreibrechte auf der
Zielfreigabe. Konfigurationssicherung und das Ändern globaler Backup-Zeitpläne
bleiben Administratoraufgaben. Diese Grenzen werden vor Annahme eines
Auftrags, vor seiner Ausführung und noch einmal im Root-Backuphelper geprüft.

Die bestehenden SMB-Rechte werden als Basis erhalten. Das Entfernen eines
Gruppenmitglieds entfernt dessen ausschließlich aus dieser Gruppe entstandene
Rechte. Die App-Dienstidentität `titan-files` erhält keine persönlichen
Gruppenrechte und keinen SMB-Login. Ältere Webadministratoren mit dieser
Dienstidentität richten zunächst über einen verifizierten Passwortwechsel
eine persönliche SMB-Identität ein.

## Persönliche Ordner und Quoten

Der persönliche Ordner wird auf ausdrückliche Auswahl als eigene, private
SMB-Freigabe angelegt. Andere Benutzer oder Gruppen können ihm nicht zugeordnet
werden. Administratoren können ihn weiterhin über den Dateimanager verwalten.
Beim Löschen eines Kontos bleiben Dateien, Linux-UID und Namensreservierung
erhalten; Sitzungen, Gruppenmitgliedschaften und SMB-Zugriff werden entfernt.

Titan bietet Benutzerquoten für vorhandene verwaltete **ZFS-Datasets** an.
Das Limit wird mit `zfs userquota@UID` gesetzt und anschließend erneut ausgelesen.
Die belegte Größe zählt Dateien, deren Eigentümer diese Linux-UID ist. Daten
eines App-Dienstkontos zählen nicht zur persönlichen Quote. `0` bedeutet
unbegrenzt. Ein Dataset-Limit gilt für den Benutzer im gesamten ausgewählten
Dataset, auch wenn mehrere Freigaben auf dasselbe Dataset verweisen.

Ext4/XFS werden ohne aktivierte, verifizierte Kernelquoten nicht als auswählbare
Quotenbereiche angeboten. Titan behauptet dort keine Durchsetzung und aktiviert
keine Quoten durch einen ungeprüften Remount.

## Zwei-Faktor-Anmeldung

Im **Sicherheitszentrum** lässt sich eine Authenticator-App einrichten. Nach
Bestätigung des aktuellen Passworts wird ein neuer Schlüssel angezeigt.
Die App verwendet zeitbasierte sechsstellige Codes (TOTP nach RFC 6238,
SHA-1, 30 Sekunden). Ein gültiger App-Code bestätigt die Einrichtung.
Zeit und Zeitzonen müssen auf NAS und Telefon korrekt eingestellt sein;
der Prüfer toleriert einen benachbarten 30-Sekunden-Zeitschritt.

Zehn Wiederherstellungscodes werden einmal angezeigt und können lokal als
Textdatei heruntergeladen werden. Jeder ersetzt genau einen App-Code.
Titan speichert nur ihre SHA-256-Prüfwerte. App-Codes und
Wiederherstellungscodes können nicht mehrfach verwendet werden.
Neue Wiederherstellungscodes ersetzen sämtliche bisherigen Codes.
Das Deaktivieren benötigt aktuelles Passwort und Sicherheitscode.

Nach Aktivierung oder Deaktivierung werden andere Websitzungen beendet.
Die aktuell bestätigte Sitzung bleibt zum sicheren Speichern der Codes aktiv.
Bei der nächsten Anmeldung ist Passwort plus App- oder Wiederherstellungscode
erforderlich. SMB-Anmeldungen verwenden weiterhin das SMB-Passwort; TOTP ist
auf die Titan-Webanmeldung beschränkt.

Das Sicherheitszentrum zeigt aktive Sitzungen, den Anmeldeverlauf, HTTPS- und
Authenticator-Status. Normale Benutzer sehen und beenden nur eigene Sitzungen;
Administratoren können Sitzungen aller Benutzer einsehen und beenden.
Sitzungstoken werden nicht angezeigt. Fehlgeschlagene Anmeldungen werden
protokolliert, Passwörter und App-Codes nie. Im produktiven Loopback-Betrieb
wird die von Caddy normalisierte Clientadresse verwendet; beliebige
Weiterleitungsheader eines Browsers bestimmen diese Adresse nicht.

## Einstellbarer Anmeldeschutz

Unter **Systemsteuerung → Sicherheit → Anmeldeschutz** können Administratoren
zwei Regeln getrennt aktivieren: **IP-Schutz** zählt fehlgeschlagene Anmeldungen
von einer Adresse über alle Benutzernamen, **Kontoschutz** zählt sie je Konto
und IP-Adresse. Ein Angreifer kann dadurch ein Konto nicht für andere
IP-Adressen sperren. Eine gemeinsame externe Adresse, etwa hinter einem
Router, kann mehrere Benutzer betreffen, wenn der IP-Schutz greift.

Beide Regeln sind anfangs eingeschaltet: **5 Fehlversuche innerhalb von
5 Minuten sperren für 15 Minuten**. Einstellbar sind 1–100 Fehlversuche,
1–1.440 Minuten Prüfzeitraum und 1–10.080 Minuten Sperrdauer. Fehlgeschlagene
Passwörter sowie falsche oder fehlende Zwei-Faktor-Codes zählen. Erfolgreiche
Anmeldungen zählen nicht; vorherige Fehlversuche bleiben bis zum Ende ihres
Prüfzeitraums berücksichtigt. Fehler unterscheiden nicht zwischen unbekanntem
Konto, falschem Passwort und falschem Sicherheitscode.

Die Sperrliste zeigt Adresse, betroffenen Bereich, Grund und Restzeit. Eine
Sperre endet automatisch oder wird mit **Entsperren → Ja** aufgehoben. Wenn
beide Regeln greifen, sind beide Einträge zu entsperren. Das Ausschalten
einer Regel entfernt ihre Sperren und bisherigen Fehlversuche. Geänderte
Grenzwerte verkürzen bereits aktive Sperren nicht nachträglich; weitere
Versuche während einer Sperre verlängern deren Ablauf ebenfalls nicht.

Regeln, Fehlversuche und Sperren liegen in der lokalen SQLite-Datenbank und
bleiben bei einem Dienstneustart erhalten. Gleichzeitige Anmeldungen werden
transaktional gezählt. Abgelaufene Einträge werden bereinigt und der Speicher
für Anmeldeversuche ist begrenzt. Eine abgewiesene gesperrte Anmeldung meldet
HTTP 429 mit einer verbleibenden Wartezeit. Bereits angemeldete Sitzungen
bleiben erreichbar, sodass ein Administrator die Sperrliste verwalten kann.

Dieser Schutz gilt ausschließlich für die **Titan-Webanmeldung**, nicht als
Firewall oder Sperrregel für SSH, SMB oder installierte Apps. Das Löschen
eines Kontos entfernt dessen Kontoschutz-Einträge, gemeinsame IP-Sperren
bleiben erhalten.

## Systembereich und Datenterminal

Die Webadministratorrolle ist kein Linux-Root-Konto. Der Dateimanager öffnet
NAS-Daten auf dem ausgewählten benannten Speicher; System- und private
Verwaltungsdateien werden auch für Webadministratoren gesperrt. Neue App-,
Freigabe- und VM-Daten verwenden den ausgewählten NAS-Datenbereich. Änderungen
an der Systemsoftware erfolgen über geprüfte Systemupdates.

Das integrierte **Datenterminal** startet mit der unprivilegierten
Dienstidentität `titan-files` im NAS-Datenbereich. Sein Prozess darf auch über
Setuid-Programme keine zusätzlichen Rechte erlangen. Es ersetzt keine
Root-Shell zur Paketinstallation. Diese Grenzen sind API- und Prozessrechte;
ein separat eingerichteter Linux-Root-Zugriff, beispielsweise über SSH, kann
sie umgehen. Ein vollständig schreibgeschützter Linux-Rootbereich wird hier
nicht behauptet.

Ältere selbst angelegte Dienste mit dem Präfix `titan-custom-`, die noch mit
Linux-UID 0 laufen, werden beim Start des neuen Systemstands vor dem normalen
Diensteziel angehalten und ihr Autostart wird dauerhaft und für die aktuelle
Laufzeit deaktiviert. Das betrifft auch einen leeren `User`-Eintrag, numerische
UID 0 und andere Kontonamen mit UID 0. Ihre Unit-Dateien und NAS-Daten bleiben
erhalten. Die Dienstübersicht zeigt den Sperrgrund; Start und Autostart setzen
ein unprivilegiertes Datenbenutzerkonto voraus. Unbekannte Dienstidentitäten
werden vorsichtshalber ebenfalls nicht über Titan gestartet.

Diese Prüfung wirkt ausschließlich auf eindeutig zugeordnete eigene
Titan-Dienste. Fremde Distributionsdienste werden nicht gestoppt. Kann ein
Dienst nicht sicher zugeordnet, deaktiviert oder angehalten werden, startet
der Titan-Verwaltungsagent nicht. Ein lokaler Systemadministrator findet den
begrenzten Fehlergrund mit `journalctl -u titan-service-containment.service`
und in der privaten Datei `/run/titan-service-containment/result.json`.
Kommandozeilen und Umgebungsvariablen der alten Dienste werden nicht in diesen
Prüfbericht übernommen. Ein Rollback auf einen älteren Systemstand kann auch
ältere Schutzfunktionen wiederherstellen; separat eingerichteter Root-Zugriff
bleibt außerhalb der Webadministratorgrenze.

## Sicherung und Wiederherstellung

Geschützte Konfigurationsbackups enthalten Gruppenrechte, Basisrechte,
persönliche Ordner, gespeicherte ZFS-Quoten, die Anmeldeschutz-Regeln, Authenticator-Schlüssel und
Wiederherstellungscode-Prüfwerte. Diese Sicherungen enthalten daher sensible
Authentifizierungsdaten und bleiben auf geschützte Administratorbackups
beschränkt. Beim Wiederherstellen werden alle Websitzungen verworfen,
ZFS-Quoten tatsächlich wieder gesetzt und ACLs transaktional wiederhergestellt.
Vorübergehende Anmeldesperren und Fehlversuch-Zähler werden nicht in ein
Konfigurationsbackup übernommen und bei dessen Wiederherstellung verworfen.
Backups ohne Anmeldeschutz-Regeln erhalten die oben beschriebenen Standardwerte.

Ältere Konfigurationsbackups ohne die neuen Felder bleiben kompatibel. Nach
Rückkehr zu einer solchen Sicherung müssen Gruppenregeln und Zwei-Faktor-
Anmeldung neu eingerichtet werden. Nach Wiederherstellung eines älteren
Backups mit Wiederherstellungscodes sollten neue Codes erzeugt werden, da der
Backupstand auch den damaligen Verbrauch dieser Codes wiederherstellt.

Systemstände vor Titan 0.5.0 können TOTP bei der Webanmeldung nicht prüfen.
Bei einem Rollback auf einen solchen Stand wird deshalb vor der Bestätigung
auf den fehlenden zweiten Faktor hingewiesen. Für einen aktiven zweiten
Faktor bleibt ein aktueller Titan-Systemstand erforderlich.

Für die Beta müssen auf dem Test-NAS Gruppenbeitritt/-austritt über einen echten
SMB-Client, private Ordner, volle ZFS-Quote, TOTP-Anmeldung inklusive
Wiederherstellungscode, Sitzungsabmeldung und Konfigurationsrestore geprüft
werden. Die automatische Suite prüft zusätzlich RFC-Testvektoren,
Code-Wiederverwendung, Rechteentzug bei wartenden Aktionen und HTTP-Grenzen.
