#!/bin/bash
# Build the final grus boot image: payload (kernel + ADT + boot-args) wrapped
# in the board shim, as an Android boot.img v2 for `fastboot boot`.
#
#   mkimg-grus.sh KERNEL ADT OUTDIR [DTB]
#
# Defaults: ADT=out/grus.adt DTB=work/grus.dtb OUTDIR=out
# The kernel is the CI artifact xnu/out/kernel.development.sweet: the grus
# port reuses the SWEET machine class (see PORT_GRUS.md) and selects the grus
# drivers at runtime with the grus=1 boot-arg.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
port=$(cd "$here/.." && pwd)
KERNEL=${1:?usage: mkimg-grus.sh KERNEL ADT OUTDIR [DTB]}
ADT=${2:-$port/../out/grus.adt}
OUTDIR=${3:-$port/../out}
DTB=${4:-$port/../work/grus.dtb}
CMDLINE=${CMDLINE:-"debug=0xc serial=3 cpus=6 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetcon=1 grus=1 sweettouch=1 sweetkeys=1 cs_enforcement_disable=1 amfi_get_out_of_my_way=1 amfi=0xff"}

[ -s "$KERNEL" ] || { echo "no kernel: $KERNEL" >&2; exit 1; }
[ -s "$ADT" ] || { echo "no ADT: $ADT (run tools/mkadt.py --board grus --highmem)" >&2; exit 1; }
[ -s "$DTB" ] || { echo "no DTB: $DTB" >&2; exit 1; }
mkdir -p "$OUTDIR"
python3 "$here/mkpayload.py" "$KERNEL" "$ADT" "$OUTDIR/payload.bin" --cmdline "$CMDLINE"
BOARD=grus DTB="$DTB" "$port/shim/build.sh" "$OUTDIR/payload.bin"
cp -f "$port/shim/out/shim-boot.img" "$OUTDIR/shim-boot.img"
echo "=== artifacts ==="
ls -l "$OUTDIR/payload.bin" "$OUTDIR/shim-boot.img"
sha256sum "$OUTDIR/payload.bin" "$OUTDIR/shim-boot.img" | tee "$OUTDIR/shim-boot.sha256"
