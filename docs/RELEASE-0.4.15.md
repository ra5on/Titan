# Titan 0.4.15 Alpha · Desktop und Hauptmenü

Der Desktop und das vollständige Hauptmenü sind getrennt. Verknüpfungen und App-Ordner bleiben pro Benutzer anpassbar; die Suche im Hauptmenü findet alle verfügbaren Werkzeuge und installierten Apps, auch wenn ihre Desktop-Verknüpfung ausgeblendet ist.

## Bedienung

- Obere Taskleiste mit Hauptmenü, Desktop, geöffneten Anwendungen, Meldungen, Aktivität, Konto und Systemmenü. Neustart, Ausschalten und Update/Rollback sind von jeder Anwendung erreichbar.
- Interne Anwendungen bleiben gleichzeitig geöffnet. Beim Wechsel zwischen Dateimanager, Docker und anderen Fenstern bleiben laufende Ansichten und Eingaben erhalten. Minimieren beendet keine Sitzung; Schließen beendet das betreffende Fenster.
- Fenster am Titel verschieben, am unteren rechten Griff vergrößern, maximieren oder minimieren. Titel und Größengriff unterstützen Pfeiltasten. Der Stern heftet eine Anwendung an die Taskleiste.
- Geöffnete Fenster, Fenstergröße und Position, angeheftete Anwendungen sowie drei Hintergrundvarianten werden pro Benutzer in diesem Browser gespeichert. Ein erneutes Laden öffnet Anwendungen wieder; ungespeicherte Formulare und Terminal-/VNC-Sitzungen werden nach einem Browser-Neuladen nicht wiederhergestellt.
- Auf dem Handy zeigt Titan eine Anwendung über die volle verfügbare Breite. Die Taskleiste wechselt zwischen Anwendungen; Desktop blendet sie aus. Es gibt keine frei verschiebbaren mobilen Fenster und keine feste rechte Seitenleiste.
- Neue Desktop-Anordnungen beginnen mit Speicher und Systemressourcen. Weitere Widgets lassen sich über „Übersicht anpassen“ hinzufügen; ausdrücklich gespeicherte bisherige Widget-Auswahlen bleiben erhalten.
- Desktop-App-Verknüpfungen und Hauptmenü-Einträge öffnen die Verwaltung der ausgewählten App im Docker-Fenster.
- Beim Schließen eines Fensters mit offenen Eingaben, Upload oder Konsole erscheint eine Ja/Nein-Rückfrage. Alle Fenster greifen weiterhin mit dem bestehenden Benutzerkonto und den bisherigen API-Berechtigungen zu.

## Prüfung

959 Python-Tests (eine hardwareabhängige Prüfung übersprungen), JavaScript-Syntax und 31 UI-Suiten einschließlich neuer Fenster-Lebenszyklus-, Rollen-, Nachrichten- und Persistenzprüfungen. Browserprüfungen untersuchen verschiedene Bildschirmgrößen, Anwendungssuche, Fensterwechsel mit erhaltenen Eingaben sowie mobile Vollbreite. Die Demo simuliert die Hostfunktionen. Physische Mobilgeräte sind nicht verfügbar; vollständige Systemveröffentlichungen behalten die bestehenden Debian-QEMU- und A/B-Update-Prüfungen als Freigabebedingung. Weiterhin Alpha.
