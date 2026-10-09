# Prüfnachweis 0.6.1

## Weboberfläche

Das [signierte Webrelease web-v0.6.1](https://github.com/ra5on/Titan/releases/tag/web-v0.6.1) wurde im [Containerworkflow](https://github.com/ra5on/Titan/actions/runs/37933287698) aus `e9c35f37afe7eb0068cbefd764393e76172ed2dc` gebaut und veröffentlicht.

- Sieben Tests prüfen Containerauswahl, Kompatibilität und Wiederherstellung.
- Ein tatsächlicher Docker-Start prüft HTTP, Gesundheitsstatus, Neustart und persistente Daten.
- Ein tatsächlicher Container mit fehlerhafter Gesundheitsprüfung wird zurückgewiesen; das vorherige Image startet anschließend wieder mit nutzbarer Datenbank. Der Test ersetzt den systemd-Aufruf durch einen Runner-Adapter und verwendet einen simulierten Host-Agenten.
- Die tatsächliche Update-Suche hat das veröffentlichte Release mit dem vertrauenswürdigen Repository-Schlüssel akzeptiert. Bei installierter Version 0.6.1 meldet sie korrekt kein neueres Webupdate. Nur der lokale Installationsstand wurde für diese lesende Prüfung vorgegeben.
- Die heruntergeladene Manifest-Signatur wurde mit dem im Repository hinterlegten Ed25519-Schlüssel erfolgreich geprüft.
- Die von GitHub gemeldeten Asset-Größen und SHA-256-Digests des Webarchivs und Debian-Quellarchivs stimmen mit dem signierten Manifest überein. Diese Prüfung ist kein erneuter vollständiger Download beider Archive.

| Identität | Wert |
| --- | --- |
| GHCR | `ghcr.io/ra5on/titan-web:0.6.1` |
| Registry-Digest | `sha256:18d23f07b074ac71d2c0f8ce1d75aafdfd63e68351aac736aef076f82959355b` |
| Docker-Image-ID | `sha256:febd8f375400f846da9e02eb918b710cbf7e18dc02a594fef3d31c15dd8d01dc` |
| Webarchiv SHA-256 | `78c1bd7ac650058416782613a6efb8fd74ec4cb1067f4cf707d8dd2de6fc0c69` |
| Debian-Quellarchiv SHA-256 | `4a7c4614a138aab9032525b485f9012086fcbfc10dd34da6fca4c7c20f848842` |

Die Updatefunktion bindet das signierte Archiv und die Image-ID. Registry-Tags sind technisch veränderlich; der Digest bezeichnet den überprüften Registry-Stand.

## Quell- und Browserprüfungen

[Quellprüfung](https://github.com/ra5on/Titan/actions/runs/37931904469) des Anwendungsstands `0b67a4a383a4aa9e231eb8854f7efefbfa3cca3e`: 1.928 ausgeführte Python-/API-Testfälle (26 umgebungsbedingt übersprungen) sowie die JavaScript-/UI-Prüfungen erfolgreich. Die nachfolgenden Änderungen bis zum Webrelease betreffen die separate Veröffentlichung, Quellarchive und Dokumentation.

Die Updateansicht wurde in der lokalen Browser-Demo geöffnet und die Webupdateprüfung ausgelöst. Die Ansicht kennzeichnet die Simulation ausdrücklich; das Browserfehlerprotokoll war leer. Der [Screenshot](images/titan-web-updates.jpg) zeigt diese Demo. Das ist kein Nachweis einer tatsächlichen Browserinstallation auf einem NAS.

## Installationsimage

Der [Systemworkflow](https://github.com/ra5on/Titan/actions/runs/37931935677) baut den eingefrorenen Anwendungsstand `0b67a4a383a4aa9e231eb8854f7efefbfa3cca3e`. Die abschließenden Systemnachweise werden nach erfolgreicher Veröffentlichung ergänzt.

Reale NAS-Hardware und längerer Dauerbetrieb sind separat zu prüfen. Diese Version setzt eine Neuinstallation voraus.
