#!/bin/sh
set -eu

runtime=/app/qemu
monitor=/tmp/qemu-monitor.sock
nginx_prefix=/tmp/securebench-nginx

export TMPDIR=/tmp
mkdir -p \
    "$nginx_prefix/logs" \
    "$nginx_prefix/client_body" \
    "$nginx_prefix/proxy" \
    "$nginx_prefix/fastcgi" \
    "$nginx_prefix/uwsgi" \
    "$nginx_prefix/scgi"
rm -f "$monitor"

"$runtime/bin/qemu-system-i386" \
    -L "$runtime/share/qemu" \
    -drive file=/app/isos/win311.img,format=raw,snapshot=on \
    -m 32 \
    -vga cirrus \
    -netdev user,id=net0 \
    -device ne2k_pci,netdev=net0 \
    -vnc :1 \
    -device sb16 \
    -monitor unix:"$monitor",server,nowait \
    -snapshot \
    -daemonize

websockify --web /usr/share/novnc --daemon 8080 127.0.0.1:5901
nginx -c /app/windows-web.conf -p "$nginx_prefix"
