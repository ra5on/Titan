# Benutzer verwalten

Administratoren verwalten Konten unter **Systemsteuerung → Benutzer**. Die Liste lässt sich durchsuchen und nach Rolle oder Status filtern. Ein Klick zeigt Kontodaten, SMB-Zugang und die zugewiesenen Freigaben. Normale Benutzer haben Zugriff auf die ihnen zugewiesenen Freigaben. Passwortänderungen und Sperren beenden bestehende Websitzungen.

Unter **Bearbeiten → Konto** können Anzeigename, Beschreibung, Rolle und Kontostatus geändert werden. Anzeigename und Beschreibung sind optional und ändern den Anmeldenamen nicht. Reine Profiländerungen beenden keine Sitzungen. Neue Sicherungen erhalten die Profilfelder; ältere Sicherungen ohne diese Felder lassen sich weiterhin wiederherstellen.

Unter **Bearbeiten → Freigaben** stehen für jeden freigegebenen Ordner **Kein Zugriff**, **Nur Lesen** oder **Lesen und Schreiben** zur Auswahl. Beim Speichern bleiben die Rechte anderer Benutzer erhalten. Jede Änderung wird als Auftrag ausgeführt; erst ein abgeschlossener Auftrag bestätigt das Speichern. Bei einem Fehler bleiben erfolgreich gespeicherte Änderungen erhalten und die noch offenen Änderungen können erneut gespeichert werden. Die Administratorrolle allein ersetzt keine SMB-Freigabenrechte.

Ältere Webkonten, die noch die gemeinsame Dienstidentität `titan-files` verwenden, benötigen zuerst einen persönlichen SMB-Zugang über **Konto → Passwort ändern**. Ihre gemeinsamen App-Rechte lassen sich im Benutzerdialog nicht verändern.

**Löschen** wird mit **Ja/Nein** bestätigt. Das eigene Konto und der letzte aktive Administrator sind geschützt. Die Prüfung erfolgt erneut, wenn der Auftrag ausgeführt wird.

Die Löschung sperrt zuerst den Webzugang und widerruft alle Sitzungen. Anschließend entfernt der Verwaltungsdienst SMB-Zugang und Freigabenmitgliedschaften und bereinigt die ACLs bestehender Dateien. Datenordner und Dateien bleiben erhalten. Das gemeinsame Dienstkonto `titan-files` und dessen Freigaberechte bleiben bestehen, wenn ein damit verbundener Webadministrator gelöscht wird.

Die gesperrte Linuxidentität und ihr Name bleiben intern reserviert. Dadurch wird ihre numerische UID nicht einem späteren Benutzer zugewiesen, der sonst Zugriff auf erhaltene Dateien bekommen könnte. Der gelöschte Benutzer hat keinen Web- oder SMB-Zugang und erscheint nicht mehr in der Benutzerliste.

Wenn SMB oder eine betroffene Freigabe während der Bereinigung nicht erreichbar ist, bleibt das Webkonto gesperrt und der Auftrag meldet den Fehler. Nach Behebung des Fehlers lässt sich **Löschen** erneut ausführen. Bereits bereinigte Freigaben und erhaltene Daten werden dabei nicht zurückgesetzt.
