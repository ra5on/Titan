#!/bin/bash
# Bounded read-only startup status: no settings, session bodies or credentials.
set -u
export LC_ALL=C.UTF-8
printf '%s\n' 'Titan boot status (read-only)'
systemctl show titan-firstboot titan-runtime titan-agent titan-web titan-proxy docker \
    --property=Id,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus --no-pager || true
# This image owns the proxy configuration; its bounded startup journal contains
# service/exec errors, never API request bodies or application credentials.
journalctl --boot --unit=titan-proxy.service --lines=40 --no-pager --output=short-monotonic || true
ss -lntp '( sport = :5000 or sport = :5001 )' || true
firewall-cmd --get-active-zones || true
getenforce || true
ls -Z /usr/bin/python3 /usr/bin/caddy /usr/bin/dockerd /etc/titan/Caddyfile || true
task_host=''
if [[ -r /etc/titan/web.env ]]; then
    task_origin=$(awk -F= '$1 == "TITAN_ORIGIN" {print substr($0, index($0,"=")+1)}' /etc/titan/web.env)
    if [[ "$task_origin" =~ ^https://([a-zA-Z0-9.-]+):5000$ ]]; then task_host="${BASH_REMATCH[1]}"; fi
fi
if [[ -n "$task_host" ]]; then
    curl --silent --show-error --noproxy '*' --connect-timeout 2 --max-time 5 \
        --header "Host: $task_host:5000" --output /dev/null \
        --write-out 'Titan local backend HTTP %{http_code}\n' http://127.0.0.1:5001/api/session || true
    task_ca=/var/lib/titan-proxy/caddy/pki/authorities/local/root.crt
    if [[ -r "$task_ca" ]]; then
        curl --silent --show-error --noproxy '*' --connect-timeout 2 --max-time 5 \
            --cacert "$task_ca" --connect-to "$task_host:5000:127.0.0.1:5000" \
            --output /dev/null --write-out 'Titan local proxy HTTP %{http_code}\n' \
            "https://$task_host:5000/api/session" || true
    fi
fi
