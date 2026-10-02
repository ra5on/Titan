#!/bin/sh
# init-bottom: the real root is mounted, PID 1 has not read its configuration yet.
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0 ;; esac
. /scripts/functions
case " $(cat /proc/cmdline) " in *' rauc.slot=A '*|*' rauc.slot=B '*) ;; *) exit 0 ;; esac
task_root="${rootmnt:-/root}"
task_data="$task_root/var/lib/titan-system"
mkdir -p "$task_data"
mount -t ext4 -o rw /dev/disk/by-partlabel/TITAN-DATA "$task_data" || panic 'Titan: Datenpartition konnte nicht eingehängt werden.'
# A durable completed directory is the publication point; an interrupted seed
# is rebuilt from the pristine root, never accepted as complete.
if [ ! -d "$task_data/persistent" ]; then
    rm -rf "$task_data/.seed"
    mkdir -p "$task_data/.seed"
    for task_path in etc var/lib/titan var/lib/titan-agent var/lib/titan-proxy var/lib/docker var/lib/containerd var/lib/libvirt var/lib/samba var/cache/samba var/srv/titan home; do
        mkdir -p "$task_data/.seed/$task_path"
        if [ -d "$task_root/$task_path" ]; then
            cp -a "$task_root/$task_path/." "$task_data/.seed/$task_path/" || panic 'Titan: Initialisierung der persistenten Daten fehlgeschlagen.'
            chmod --reference="$task_root/$task_path" "$task_data/.seed/$task_path" 2>/dev/null || true
        fi
    done
    sync
    mv "$task_data/.seed" "$task_data/persistent" || panic 'Titan: Persistenz konnte nicht abgeschlossen werden.'
    sync
fi
for task_path in etc var/lib/titan var/lib/titan-agent var/lib/titan-proxy var/lib/docker var/lib/containerd var/lib/libvirt var/lib/samba var/cache/samba var/srv/titan home; do
    [ -d "$task_data/persistent/$task_path" ] || panic 'Titan: Persistente Verzeichnisse sind unvollständig.'
    mkdir -p "$task_root/$task_path"
    mount --bind "$task_data/persistent/$task_path" "$task_root/$task_path" || panic 'Titan: Persistente Daten konnten nicht eingebunden werden.'
done
