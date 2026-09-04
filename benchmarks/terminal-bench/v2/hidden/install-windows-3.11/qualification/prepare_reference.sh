#!/bin/sh
set -eu

archive=/tmp/qemu-5.2.0.tar.xz
source_dir=/tmp/qemu-5.2.0
build_dir=/tmp/qemu-5.2.0-build

wget -q https://download.qemu.org/qemu-5.2.0.tar.xz -O "$archive"
printf '%s  %s\n' \
    'cb18d889b628fbe637672b0326789d9b0e3b8027e0445b936537c78549df17bc' \
    "$archive" | sha256sum -c -
tar -xf "$archive" -C /tmp
mkdir "$build_dir"
cd "$build_dir"
"$source_dir/configure" \
    --target-list=i386-softmmu \
    --disable-docs \
    --disable-werror
make -j2 qemu-system-i386

mkdir -p /app/qemu/bin /app/qemu/share/qemu/keymaps
cp "$build_dir/qemu-system-i386" /app/qemu/bin/
cp "$source_dir/pc-bios/bios-256k.bin" /app/qemu/share/qemu/
cp "$source_dir/pc-bios/vgabios-cirrus.bin" /app/qemu/share/qemu/
cp "$source_dir/pc-bios/pxe-ne2k_pci.rom" /app/qemu/share/qemu/
cp "$source_dir/pc-bios/efi-ne2k_pci.rom" /app/qemu/share/qemu/
cp "$source_dir/pc-bios/kvmvapic.bin" /app/qemu/share/qemu/
cp "$source_dir/pc-bios/keymaps/en-us" /app/qemu/share/qemu/keymaps/
strip /app/qemu/bin/qemu-system-i386
cp /qualification/reference-launch.sh /app/start-windows.sh
cp /qualification/reference-nginx.conf /app/windows-web.conf
chmod 0755 /app/start-windows.sh
