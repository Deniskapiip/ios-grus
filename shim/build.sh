#!/bin/bash
# Build the board shim and wrap it in a boot.img v2 that mirrors the stock
# header of the target (sweet / grus).
#
#   ./build.sh [PAYLOAD]
#   BOARD=grus DTB=../../work/grus.dtb ./build.sh ../../out/payload.bin
#
# The board profile selects the GIC, the bootloader framebuffer and the UFS
# host (shim/board.h). Everything else is in the XNU Apple Device Tree that
# tools/mkadt.py --board <name> generates.
set -euo pipefail
cd "$(dirname "$0")"
BOARD=${BOARD:-grus}
case "$BOARD" in
grus|sweet) ;;
*) echo "error: BOARD must be grus or sweet (got '$BOARD')" >&2; exit 1 ;;
esac
BOARD_DEF="-DBOARD_$(echo "$BOARD" | tr '[:lower:]' '[:upper:]')"
# Stock DTB for the boot.img header. A grus build unpacks it from the phone's
# own boot.img; the source-built work/grus.dtb is the documented fallback.
DTB=${DTB:-}
if [ -z "$DTB" ]; then
	for cand in "../work/$BOARD.dtb" "../dtb/boot_unpacked/dtb"; do
		[ -f "$cand" ] && DTB=$cand && break
	done
fi
[ -n "$DTB" ] && [ -f "$DTB" ] || {
	echo "error: no DTB: set DTB=/path/to/$BOARD.dtb (mount: unpack the stock boot.img with" >&2
	echo "       tools/unpack_bootv2.py or build one from the LineageOS DTS sources)" >&2
	exit 1
}
MKBKIMG=${MKBKIMG:-mkbootimg}
CC=${CC:-aarch64-linux-gnu-gcc}
OBJCOPY=${OBJCOPY:-aarch64-linux-gnu-objcopy}
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra $BOARD_DEF"
mkdir -p out
for f in start.S shim.c console.c mmu.c fdt.c loader.c ufs.c; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$($OBJCOPY --version >/dev/null 2>&1; aarch64-linux-gnu-readelf -r out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/ufs.o | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	out/start.o out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/ufs.o -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print strtonum("0x"$1)}')
truncate -s "$size" out/Image
# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi
"$MKBKIMG" --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \
	--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
	--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
	--os_version 17.0.0 --os_patch_level 2035-06 \
	--cmdline "console=null" -o out/shim-boot.img
# Host render of the console layout.
gcc -O1 -Wall -DBOARD_GRUS=$([ "$BOARD" = grus ] && echo 1 || echo 0) -o out/host_test console.c host_test.c && ./out/host_test
ls -l out/Image out/shim-boot.img
echo "board=$BOARD dtb=$DTB"
