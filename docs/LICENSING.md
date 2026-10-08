# Titan-Lizenz

Maßgeblich ist die englische [Titan Noncommercial License 1.0](../LICENSE).

Erlaubt sind nichtkommerzielle Nutzung, Einsicht, Kopien, Änderungen und kostenlose Weitergabe einschließlich veränderter Versionen. Copyright und Lizenz müssen erhalten bleiben; Änderungen müssen kenntlich gemacht werden.

Ohne gesonderte Erlaubnis sind Verkauf, Vermietung, kostenpflichtige Bundles oder Hardware-Angebote, bezahltes Hosting, Installation/Support gegen Entgelt, Werbe- und Abonnementerlöse sowie Einsatz für gewerbliche Geschäftstätigkeit ausgeschlossen. Die Regeln betreffen auch Ableitungen des eigenen Titan-Codes.

Debian, Linux und andere unabhängige Fremdkomponenten sowie gespeicherte Benutzerdaten sind hiervon ausgenommen. Die jeweiligen Fremdlizenzen gelten unverändert. Hinweise stehen in [NOTICE](../NOTICE) und den mitgelieferten Lizenzen.

Die kommerzielle Einschränkung bedeutet Source available, nicht Open Source gemäß [OSI-Definition](https://opensource.org/osd). Diese projektspezifische Lizenz ist keine anwaltlich geprüfte Rechtsberatung.

## Kommerzielle Zukunft von Titan

Die öffentliche Lizenz beschränkt die Rechte der Empfänger. Sie überträgt ihnen kein Eigentum am eigenen Titan-Code. Der jeweilige Rechteinhaber kann für sein eigenes Material gesonderte kommerzielle Rechte einräumen; Abschnitt 3 der Lizenz sieht solche schriftlichen Vereinbarungen ausdrücklich vor. Für fremde Beiträge sind die entsprechenden Rechte separat erforderlich. Aus einer kostenlosen GitHub-Veröffentlichung allein folgt keine Berechtigung, fremde Beiträge kommerziell neu zu lizenzieren.

**Titan und TitanOS sind getrennte Projekte.** Das Schwesterprojekt TitanOS basiert laut dessen `UPSTREAM.md` auf Umbrel. Dessen Code und Assets dürfen nicht in Titan übernommen werden, um die kommerzielle Zukunft von Titan zu erhalten. Umbrel veröffentlicht seinen Code unter [PolyForm Noncommercial 1.0.0](https://github.com/getumbrel/umbrel/blob/master/LICENSE.md). Laut [offizieller Lizenz-FAQ](https://github.com/getumbrel/umbrel/wiki/License-FAQ) umfasst die Einschränkung auch den Verkauf von Ableitungen, vorinstallierter Hardware und Support. Für solche Umbrel-basierten Angebote ist eine gesonderte Vereinbarung erforderlich; der aktuelle [Umbrel-Projekthinweis](https://github.com/getumbrel/umbrel#license) nennt `partner@umbrel.com`.

Für Titan werden Bedienideen anhand von Bildern beschrieben und mit eigenem Code und eigenen Grafiken umgesetzt. Neue Hintergrundbilder in `titan/web/wallpapers/` sind eigens erstellte SVG-Zeichnungen; die AppStore-Szenen bestehen aus eigenen CSS-Illustrationen. Die Referenzfotos aus dem Chat werden weder ausgeliefert noch als README-Screenshots verwendet. Die Darstellung verwendet lokal verfügbare Systemschriften, keine aus Umbrel übernommenen Fontdateien. Ähnliche Bedienideen ersetzen keine Prüfung geschützter Gestaltung, Marken oder Patente; eine pixelgenaue Nachbildung ist kein Ziel.

## Fremdkomponenten vor einem Verkauf

Ein eigener Titan-Code hebt die Pflichten der ausgelieferten Komponenten nicht auf. Für das konkrete Verkaufsimage sind Paket- und Container-Versionen, Lizenztexte, Urheberhinweise und erforderliche Quellcodeangebote zu erfassen. Insbesondere bleiben die Rechte an Linux, Debian-Paketen, QEMU, Samba, ZFS, Docker, noVNC und xterm sowie an optional installierten Apps eigenständig. App-Namen und erkennbare Marken begründen keine Partnerschaft oder Markenlizenz.

Die vorhandenen Hinweise in `NOTICE`, den Terminal-Lizenzen und `/usr/share/doc` bleiben erhalten. Diese Dokumentation hält die Entwicklungsgrenze fest; sie ist keine abschließende Freigabe eines späteren kommerziellen Gesamtprodukts. Vor dessen Verkauf muss die tatsächlich ausgelieferte Kombination einschließlich Fremdbeiträgen und Marken geprüft werden.

### Native Apps und Abhängigkeiten

**Prüfstand: 08.10.2026.** Der native Katalog bietet Cloudflare Tunnel, Immich, AdGuard Home und Tailscale an. Die folgenden Versionen entsprechen den Rezepten in [`titan/app_packages.py`](../titan/app_packages.py); dort sind die Container zusätzlich mit vollständigen SHA-256-Digests fixiert. Die Tabelle erfasst die genannten Hauptkomponenten, nicht sämtliche Pakete und Bibliotheken aller Container-Layer.

| Komponente / Rezeptversion | Primärquelle zur Lizenz | Bedeutung für ein kommerzielles Angebot |
| --- | --- | --- |
| cloudflared `2026.10.0` | [Apache 2.0](https://github.com/cloudflare/cloudflared/blob/2026.10.0/LICENSE) | Kommerzielle Weitergabe ist unter den Lizenzbedingungen möglich; Lizenz-, Urheber- und gegebenenfalls NOTICE-Hinweise erhalten. Der Cloudflare-Dienstvertrag gilt separat. |
| Immich Server und Machine Learning `v3.3.0` | [AGPLv3](https://github.com/immich-app/immich/blob/v3.3.0/LICENSE) | Verkauf ist erlaubt. Bei Binärweitergabe korrespondierenden Quellcode und erforderliche Build-/Installationsinformationen nach der Lizenz bereitstellen; bei veränderten Netzwerkversionen zusätzlich Abschnitt 13 beachten. Modellgewichte sind separat zu prüfen, siehe unten. |
| AdGuard Home `v0.107.79` | [GPLv3](https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/LICENSE.txt) | Verkauf ist erlaubt; Lizenzhinweise und Pflichten zur Bereitstellung des korrespondierenden Quellcodes erfüllen. |
| Tailscale `v1.102.5` | [BSD 3-Clause](https://github.com/tailscale/tailscale/blob/v1.102.5/LICENSE) | Der Client ist mit den vorgeschriebenen Hinweisen kommerziell weitergebbar. Daraus folgt kein Recht, den gehosteten Tailscale-Dienst weiterzuverkaufen; die [Dienstbedingungen](https://tailscale.com/terms) sind separat maßgeblich. |
| Immich-Cache: Valkey `9` | [BSD 3-Clause](https://github.com/valkey-io/valkey/blob/9.0/COPYING) | Hinweise erhalten. Der Compose-Dienst heißt `redis`, verwendet aber ein per Digest fixiertes Valkey-Image; er ist deshalb nicht als Redis unter SSPL einzustufen. |
| Immich-Datenbank: PostgreSQL `14` | [PostgreSQL-Lizenz](https://www.postgresql.org/about/licence/) | Kommerzielle Nutzung und Weitergabe sind mit den vorgeschriebenen Hinweisen möglich. Das Rezept fixiert das kombinierte Image `14-vectorchord0.4.3-pgvectors0.2.0` per Digest. |
| Darin: VectorChord `0.4.3` | [AGPLv3 oder ELv2, wählbar](https://github.com/tensorchord/VectorChord/blob/0.4.3/LICENSE) | Die gewählte Lizenz und deren Pflichten dokumentieren. [ELv2](https://github.com/tensorchord/VectorChord/blob/0.4.3/licenses/LICENSE.ELv2) beschränkt bestimmte gehostete oder verwaltete Dienste; AGPLv3 ist eine separate Wahl mit eigenen Quellcodepflichten. |
| Darin: pgvecto.rs `0.2.0` | [Apache 2.0](https://github.com/tensorchord/pgvecto.rs/blob/v0.2.0/LICENSE) | Kommerzielle Weitergabe unter Erhaltung der erforderlichen Lizenz- und Urheberhinweise möglich. |

Die GPL-/AGPL-Regeln verbieten den Verkauf nicht. Ob Bestandteile unabhängige Programme in einem Aggregat oder Teile eines abgeleiteten Gesamtwerks sind, muss anhand ihrer tatsächlichen Verbindung beurteilt werden; Containergrenzen allein entscheiden das nicht. Bei Auslieferung als Verbraucherprodukt können auch die Installationsinformationen nach Abschnitt 6 relevant sein. Ein allgemeiner Link auf ein Upstream-Projekt ersetzt nicht automatisch die erforderliche Bereitstellung des zur ausgelieferten Binärversion gehörenden Quellcodes.

### Immich: Grenze bei vortrainierten Modellen

Immich `v3.3.0` aktiviert in seiner [Standardkonfiguration](https://github.com/immich-app/immich/blob/v3.3.0/server/src/dtos/config.dto.ts#L635-L640) die Gesichtserkennung mit `buffalo_l`. Die [offizielle Immich-Modellkarte](https://huggingface.co/immich-app/buffalo_l/blob/main/README.md) verweist auf die InsightFace-Lizenz. InsightFace unterscheidet ausdrücklich zwischen dem kommerziell nutzbaren MIT-Code und den vortrainierten Modellen, die laut [Lizenzhinweis](https://github.com/deepinsight/insightface/blob/master/python-package/README.md#license) nur für nichtkommerzielle Forschung vorgesehen sind, auch bei automatischem Download.

Die AGPL-Lizenz von Immich erteilt daher keine pauschalen kommerziellen Rechte an diesen Modellgewichten. Für ein Verkaufsangebot mit dieser Gesichtserkennung müssen gesonderte Rechte geklärt, das Modell durch eine entsprechend lizenzierte Alternative ersetzt oder die Funktion deaktiviert werden. Ein nachträglicher Kundendownload allein klärt die kommerziellen Rechte nicht. Weitere Modelle, etwa für CLIP und OCR, benötigen ebenfalls eine eigene Prüfung; sie sind durch diese Stichprobe nicht abschließend freigegeben.

Die ML-Modelle werden bei Bedarf nachgeladen. Die [ML-Konfiguration von v3.3.0](https://github.com/immich-app/immich/blob/v3.3.0/machine-learning/immich_ml/config.py) verwendet standardmäßig die Modellrevision `main`. Der gepinnte Container-Digest fixiert somit nicht sämtliche später bezogenen Modellgewichte. Modellname, Revision, Herkunft und Lizenz müssen für die tatsächlich angebotene Konfiguration zusätzlich erfasst werden.

### Fabrikimage und später installierte Apps

Der untersuchte Buildpfad in [`build-debian-package.py`](../scripts/build-debian-package.py), [`build-debian-image.sh`](../scripts/build-debian-image.sh) und [`configure-guest.sh`](../image/debian/configure-guest.sh) liefert Titan einschließlich der Compose-Rezepte und installiert Debian-Runtimepakete. Er zieht oder speichert die oben aufgeführten Appcontainer nicht im Fabrikimage. Optional installierte Apps und ihre Modelle werden erst später bezogen. Diese Aussage beschreibt die untersuchten Buildskripte; sie ist kein vollständiger Nachweis des Inhalts eines fertigen Release-Images.

Wer Geräte mit bereits installierten Apps, zusätzlichen Container-Layern oder gefüllten Modell-Caches ausliefert, muss auch deren Weitergabe prüfen. Die bereits im Fabrikimage enthaltenen Debian- und Runtimekomponenten benötigen unabhängig davon ein vollständiges versionsbezogenes Lizenz- und Quellcodeinventar. Der Build erfasst versionsgenaue Debian-Quellarchive einschließlich zusätzlicher eingebetteter Quellen. Vor der Veröffentlichung werden Index, Tarinhalt und Paketversionen geprüft; Quellarchivteile erhalten signierte Prüfsummen und werden neben dem Image angeboten. Die tatsächlichen Release-Dateien und der abgeschlossene Build belegen die erfolgreiche Sammlung für einen bestimmten Stand. [Quellarchive](DEBIAN-SOURCES.md).

### ZFS und Linux

Der aktuelle Builder kompiliert ZFS-DKMS für den ausgelieferten Linux-Kernel und nimmt das Modul in das Image auf. Die CDDL-/GPL-Kombination ist deshalb ein konkreter gesonderter Prüffall für ein Verkaufsimage. [Debians Hinweise zu ZFS](https://wiki.debian.org/ZFS) beschreiben die Lizenzfrage und den DKMS-Ansatz. Eine technisch funktionierende Kombination oder ein vorhandenes Quellarchiv stellt keine rechtliche Freigabe ihrer gemeinsamen Weitergabe dar. Diese Dokumentation behauptet weder eine gesicherte Zulässigkeit noch einen festgestellten Lizenzverstoß.
