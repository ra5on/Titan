#!/bin/bash
# Read-only reachability report. Never reads setup tokens or credentials.
set -u
export LC_ALL=C.UTF-8
printf '%s\n' 'Titan: Diagnose der Erreichbarkeit'
if [[ $EUID -ne 0 ]]; then
    printf '%s\n' 'Für vollständige Dienstlogs mit sudo ausführen.'
fi
printf '\nSystem und IP-Adressen\n'
if [[ -r /etc/os-release ]]; then
    awk -F= '$1 == "PRETTY_NAME" {print $2}' /etc/os-release
fi
hostname -I 2>/dev/null || true
if [[ -d /usr/lib/titan/titan ]]; then
    PYTHONPATH=/usr/lib/titan python3 -c 'import titan; print("Titan", titan.__version__, getattr(titan, "__release_stage__", "unbekannt"))' || true
fi
printf '\nDienste\n'
systemctl --no-pager --full status titan-web titan-agent titan-proxy 2>&1 || true
printf '\nListener auf Port 5000 und 5001\n'
if command -v ss >/dev/null; then
    ss -lntp '( sport = :5000 or sport = :5001 )' 2>&1 || true
fi
printf '\nLokale Web-Verbindung\n'
task_host=''
if [[ -r /etc/titan/web.env ]]; then
    task_origin=$(awk -F= '$1 == "TITAN_ORIGIN" {print substr($0, index($0,"=")+1)}' /etc/titan/web.env)
    if [[ "$task_origin" =~ ^https://([a-zA-Z0-9.-]+):5000$ ]]; then
        task_host="${BASH_REMATCH[1]}"
        printf 'Konfigurierte Adresse: %s\n' "$task_origin"
    fi
fi
if command -v curl >/dev/null; then
    curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 8 --output /dev/null \
        --write-out 'Webdienst auf localhost:5001: HTTP %{http_code}\n' \
        http://127.0.0.1:5001/api/session || true
    task_ca=/var/lib/titan-proxy/caddy/pki/authorities/local/root.crt
    if [[ -n "$task_host" && -r "$task_ca" ]]; then
        curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 8 --output /dev/null \
            --cacert "$task_ca" --resolve "$task_host:5000:127.0.0.1" \
            --write-out 'HTTPS-Proxy auf localhost:5000: HTTP %{http_code}\n' \
            "https://$task_host:5000/api/session" || true
    else
        printf '%s\n' 'HTTPS-Prüfung benötigt den konfigurierten Host und die lesbare lokale CA.'
    fi
else
    printf '%s\n' 'curl fehlt; Verbindungstest übersprungen.'
fi
printf '\nLetzte Dienstmeldungen\n'
journalctl -u titan-web -u titan-agent -u titan-proxy -n 60 --no-pager 2>&1 || true
printf '\nHTTP 200 bei beiden lokalen Tests bestätigt Webdienst und Proxy.\n'
printf '%s\n' 'Für LAN-Zugriff die konfigurierte HTTPS-Adresse auf Port 5000 verwenden und IP, Firewall sowie Client-Vertrauen zur lokalen CA prüfen.'
