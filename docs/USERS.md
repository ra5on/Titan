# Benutzer verwalten

Administratoren können unter **Benutzer** Konten anlegen, bearbeiten, sperren und löschen. Normale Benutzer haben Zugriff auf die ihnen zugewiesenen Freigaben. Passwortänderungen und Sperren beenden bestehende Websitzungen.

**Löschen** verlangt zur Bestätigung den vollständigen Benutzernamen. Das eigene Konto und der letzte aktive Administrator sind geschützt. Die Prüfung erfolgt erneut, wenn der Auftrag ausgeführt wird.

Die Löschung sperrt zuerst den Webzugang und widerruft alle Sitzungen. Anschließend entfernt der Verwaltungsdienst SMB-Zugang und Freigabenmitgliedschaften und bereinigt die ACLs bestehender Dateien. Datenordner und Dateien bleiben erhalten. Das gemeinsame Dienstkonto `titan-files` und dessen Freigaberechte bleiben bestehen, wenn ein damit verbundener Webadministrator gelöscht wird.

Die gesperrte Linuxidentität und ihr Name bleiben intern reserviert. Dadurch wird ihre numerische UID nicht einem späteren Benutzer zugewiesen, der sonst Zugriff auf erhaltene Dateien bekommen könnte. Der gelöschte Benutzer hat keinen Web- oder SMB-Zugang und erscheint nicht mehr in der Benutzerliste.

Wenn SMB oder eine betroffene Freigabe während der Bereinigung nicht erreichbar ist, bleibt das Webkonto gesperrt und der Auftrag meldet den Fehler. Nach Behebung des Fehlers lässt sich **Löschen** erneut ausführen. Bereits bereinigte Freigaben und erhaltene Daten werden dabei nicht zurückgesetzt.
