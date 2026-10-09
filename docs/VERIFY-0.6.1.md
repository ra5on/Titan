# Prüfnachweis 0.6.1

## Weboberfläche

Das [signierte Webrelease web-v0.6.1](https://github.com/ra5on/Titan/releases/tag/web-v0.6.1) wurde im [Containerworkflow](https://github.com/ra5on/Titan/actions/runs/37933287698) aus `e9c35f37afe7eb0068cbefd764393e76172ed2dc` gebaut und veröffentlicht.

- Sieben Tests prüfen Containerauswahl, Kompatibilität und Wiederherstellung.
- Ein tatsächlicher Docker-Start prüft HTTP, Gesundheitsstatus, Neustart und persistente Daten.
- Ein tatsächlicher Container mit fehlerhafter Gesundheitsprüfung wird zurückgewiesen; das vorherige Image startet anschließend wieder mit nutzbarer Datenbank. Der Test ersetzt den systemd-Aufruf durch einen Runner-Adapter und verwendet einen simulierten Host-Agenten.
- Der anonyme Abruf des GHCR-Manifests für `0.6.1` lieferte HTTP 200 und den unten dokumentierten Registry-Digest. Die Veröffentlichung erfordert zum Abruf keine GitHub-Anmeldung.
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

[Quellprüfung](https://github.com/ra5on/Titan/actions/runs/37931904469) des Anwendungsstands `0b67a4a383a4aa9e231eb8854f7efefbfa3cca3e`: 1.928 Python-/API-Testfälle, davon 26 umgebungsbedingt übersprungen, sowie die JavaScript-/UI-Prüfungen erfolgreich. Die nachfolgenden Änderungen bis zum Webrelease betreffen die separate Veröffentlichung, Quellarchive und Dokumentation.

Die Updateansicht wurde in der lokalen Browser-Demo geöffnet und die Webupdateprüfung ausgelöst. Die Ansicht kennzeichnet die Simulation ausdrücklich; das Browserfehlerprotokoll war leer. Der [Screenshot](images/titan-web-updates.jpg) zeigt diese Demo. Das ist kein Nachweis einer tatsächlichen Browserinstallation auf einem NAS.

## Installationsimage

Der erfolgreiche [Systemworkflow](https://github.com/ra5on/Titan/actions/runs/37943811929) hat das [Installationsrelease v0.6.1](https://github.com/ra5on/Titan/releases/tag/v0.6.1) aus dem eingefrorenen Anwendungsstand `0b67a4a383a4aa9e231eb8854f7efefbfa3cca3e` gebaut und veröffentlicht. Im veröffentlichten Lauf sind die Start-/Laufzeitprüfung (15 bestandene Prüfgruppen, eine in den A/B-Test verlagerte Wachstumsprüfung) und die A/B-Prüfung (sieben bestandene Prüfgruppen) erfolgreich abgeschlossen. Geprüft wurden unter anderem HTTPS und Ersteinrichtung, SMB mit mehreren Benutzern, Docker-Apps und Netzwerke, VM-Lebenszyklus, Vergrößerung des Datenbereichs, signiertes Systemupdate, Datenerhalt, manueller Rollback und Rückfall nach einem fehlerhaften Start.

Die A/B-Prüfung verwendet eine private Kopie des aktuellen Builds mit einer älteren Systemidentität. Sie weist die Wechselmechanik nach, keine Migration von einer älteren veröffentlichten Installation. Beim absichtlich unbootbaren Testslot löst der Test einen Reset aus; ein automatischer Hardware-Watchdog ist damit nicht nachgewiesen.

Die VM-Prüfung startet virtuelle Maschinen und prüft den authentifizierten RFB-Handshake; sie installiert kein Gastbetriebssystem und bewertet nicht die Browser-Canvas-Darstellung. Reale NAS-Hardware und längerer Dauerbetrieb sind separat zu prüfen. Diese Version setzt eine Neuinstallation voraus.

Die heruntergeladenen Signaturen von `manifest.json` und `SHA256SUMS` wurden mit dem vertrauenswürdigen Repository-Schlüssel erfolgreich verifiziert. Alle 15 in der signierten Prüfsummenliste enthaltenen Assets stimmen mit den von GitHub gemeldeten SHA-256-Digests überein; die heruntergeladenen Manifeste und Testberichte wurden zusätzlich lokal gehasht. Die großen Archive wurden dafür nicht vollständig erneut heruntergeladen.

| Veröffentlichung | Größe in Bytes | SHA-256 |
| --- | ---: | --- |
| `titan-0.6.1-amd64.img.xz` | 671096404 | `8b0f88a9f8545325261c3ac1075732f30885f48c0703a70dde838be8c34d85d8` |
| `titan-0.6.1-amd64.raucb` | 830694709 | `6aa61b0c697201a3c4eb6b158d87cd9f7a8c0a78713732246bab5279d4259db7` |

Das offline vorinstallierte Webimage hat die Image-ID `sha256:1f90f26cf61bdd413398107c76fa6146982a24b73e0ac08f010c9bd7548281dc`. Es wurde innerhalb des Systembuilds erzeugt und hat daher eine eigene Identität gegenüber dem separat veröffentlichten GHCR-Image gleicher Anwendungsversion.

## Veröffentlichungskorrektur

Der erste Systemlauf bestand Build und alle Laufzeittests. GitHub lehnte anschließend die Release-Anlage mit dem expliziten älteren `target_commitish` durch HTTP 403 ab. Der Publisher prüft jetzt den unveränderlichen Tag und verwendet `--verify-tag`, ohne diesen redundanten Zielparameter. Der [Test mit dem tatsächlichen Veröffentlichungsbefehl](https://github.com/ra5on/Titan/actions/runs/37943642911) konnte mit `contents: write` einen unveröffentlichten Entwurf anlegen und wieder entfernen.

Künftige Feature- und Webbuilds reservieren ihren exakten Tag vor dem aufwendigen Build. Ein bereits vorhandener Tag auf einem anderen Commit wird niemals überschrieben. Sechs lokale Tests prüfen Neuanlage, Wiederholung, abweichenden Commit, verweigerte Rechte und ungültige Eingaben. Unveränderte Debian-Wartungsläufe reservieren keinen Tag, da sie ausdrücklich ohne Release enden dürfen.

Der erfolgreich veröffentlichte [erneute Systemlauf](https://github.com/ra5on/Titan/actions/runs/37943811929) verwendet weiterhin Anwendung und Builder aus `0b67a4a383a4aa9e231eb8854f7efefbfa3cca3e`. Nur der Publisher wird vor dem Wechsel auf diesen eingefrorenen Checkout separat gesichert und aus dem neuen Workflow verwendet. Falls die Veröffentlichung scheitert, werden ausschließlich die öffentlichen Release-Dateien für einen Tag als Wiederaufnahme-Artefakt aufbewahrt; private Signierschlüssel gehören nicht dazu.

Die [CI-Prüfung des Publishers](https://github.com/ra5on/Titan/actions/runs/37943793225) und die [Debian-Paketprüfung](https://github.com/ra5on/Titan/actions/runs/37943793165) für `b00174cb8aab7ce24634f83f9721afc6c05f89d3` sind erfolgreich.
