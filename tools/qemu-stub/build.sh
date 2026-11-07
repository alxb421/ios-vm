#!/bin/sh
# build.sh OUT.bin  -> flat stub linked at 0x40200000
set -e
d=$(dirname "$0"); out=${1:-ramfb-stub.bin}
CC=${CC:-aarch64-linux-gnu-gcc}; OBJCOPY=${OBJCOPY:-aarch64-linux-gnu-objcopy}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
$CC -O2 -ffreestanding -fno-pic -mgeneral-regs-only -mstrict-align -nostdlib -c "$d/ramfb-stub.S" -o "$tmp/s.o"
$CC -O2 -ffreestanding -fno-pic -mgeneral-regs-only -mstrict-align -nostdlib -c "$d/ramfb-stub.c" -o "$tmp/c.o"
$CC -nostdlib -static -Wl,--build-id=none -Wl,-z,noexecstack -Wl,--no-warn-rwx-segments -Wl,-T,"$d/ramfb-stub.ld" "$tmp/s.o" "$tmp/c.o" -o "$tmp/stub.elf"
$OBJCOPY -O binary "$tmp/stub.elf" "$out"
