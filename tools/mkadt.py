#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the board's xnu needs to boot.

Only what the early boot path actually reads (see NOTES.md); every MMIO
address comes from the board's own device tree sources.

Usage:  mkadt.py OUT.adt [--board sweet|grus] [--dump] [--qemu] [--highmem]
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# Panic log buffer, carved from the TOP of the dram range and exposed to XNU as
# /pram + /chosen/embedded-panic-log-size. Without it, pe_init.c's
# check_for_panic_log() leaves gPanicBase == 0, debug_log_init() bails out twice
# and the kernel hangs right after "kdp_core zlib memory" - reproduced on QEMU
# and independently on ios-fajita.
PANIC_LOG_SIZE = 0x100000
# /arm-io children are relative to this; it must not be 0 (serial_init bails)
SOC_BASE = 0x01000000

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree. That tree is
# an Apple artifact (kept out of git): extract it from the IPSW with
#   tools/remotezip.py URL DeviceTree.d22ap.im4p DIR
#   ipsw img4 im4p extract DIR/Firmware/all_flash/DeviceTree.d22ap.im4p -o d22ap.adt
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw-x/d22ap.adt')

# Per-board MMIO facts. Every value is taken from the board's own dts:
#   sweet: LineageOS android_kernel_xiaomi_sm7150 (sm7150.dtsi + sweet dtsi),
#          live FDT facts in ios-sweet NOTES.md.
#   grus:  LineageOS android_kernel_xiaomi_sdm710, sdm670.dtsi +
#          grus-sdm710.dtsi (see HARDWARE_MAP_GRUS.md in the grus port).
BOARDS = {
    'sweet': dict(
        name='sweet', soc_compat='qcom,sm7150',
        # kernel-managed RAM below 4G: above every fixed carve-out
        phys_base=0xb0000000, mem_size=0x4d000000,
        # --highmem: whole upper DDR bank (8 GiB part: 4 GiB..~8.2 GiB)
        high_phys_base=0x100000000, high_mem_size=0xfcc00000,
        gicd=0x17a00000, gicr=0x17a60000, gicd_size=0x10000, gicr_size=0x100000,
        fb=0x9c000000, fb_size=0x1700000,
        fb_w=1080, fb_h=2400,
        ufs=0x01d84000, ufs_size=0x3000,
        timebase=19200000, vtimer_intid=19,
        cpu_compat='qcom,kryo470',
        cpu_count=8, npu=8,
    ),
    'grus': dict(
        name='grus', soc_compat='qcom,sdm710',
        phys_base=0xb0000000, mem_size=0x4d000000,
        # Mi 9 SE: 6 GiB part, so the upper bank is 4 GiB..6 GiB. 0x70000000
        # (1.75 GiB) leaves room for rmtfs/hyp style carve-outs above 4 GiB and
        # is still enough for the iOS userland. Override with --dram-size.
        high_phys_base=0x100000000, high_mem_size=0x6cfd0000,
        gicd=0x17a00000, gicr=0x17a60000, gicd_size=0x10000, gicr_size=0x100000,
        # reserved-memory cont_splash_region@9c000000, 0x2300000; EA8076
        # 1080x2340 command-mode panel, ABL leaves an RGBA8888 buffer.
        fb=0x9c000000, fb_size=0x2300000,
        fb_w=1080, fb_h=2340,
        ufs=0x01d84000, ufs_size=0x3000,
        timebase=19200000, vtimer_intid=19,
        cpu_compat='qcom,kryo360',
        cpu_count=8, npu=8,
    ),
}
# /chosen display geometry presented to iOS: iPhone X panel class, unchanged.
CANVAS_W, CANVAS_H = 1125, 2436

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a76): GICD/GICR and CNTFRQ
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

BOOT_MANIFEST_HASH = hashlib.sha384(b'sweet boot manifest').digest()


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def profile(board):
    if board not in BOARDS:
        raise SystemExit(f'unknown board {board!r}; known: {", ".join(BOARDS)}')
    return BOARDS[board]


def build(seed=None, qemu=False, highmem=False, board='sweet', dram_size=None):
    """qemu=True: same tree, but with QEMU virt's GIC addresses and CNTFRQ
    (tools/qemu-sweet.py). dram_size overrides the --highmem bank size."""
    b = profile(board)
    phys_base, mem_size = (b['high_phys_base'], b['high_mem_size']) if highmem \
        else (b['phys_base'], b['mem_size'])
    if highmem and dram_size:
        mem_size = dram_size
    # Carve the panic log off the top so the kernel never allocates over it.
    panic_base = phys_base + mem_size - PANIC_LOG_SIZE
    mem_size -= PANIC_LOG_SIZE
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu \
        else (b['gicd'], b['gicr'], b['timebase'])
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('embedded-panic-log-size', u32(PANIC_LOG_SIZE)),
        ('firmware-version', cstr(b['name'] + '-shim')),
        ('system-firmware-version', cstr(b['name'] + '-shim')),
        # iBoot's SHA-384 of the boot manifest; /sbin/mount -P 1 exits unless
        # it exists (bind mounts /private/preboot/<hex>/usr/standalone/firmware,
        # tolerating a missing directory). Fixed stand-in value.
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) aborts "failed to get crypto algorithm" without
        # it; real A11+ device trees say sha2-384.
        ('crypto-hash-method', cstr('sha2-384')),
        # MobileGestalt's screen class: display-scale (u32, default 0) comes
        # from /chosen, the pixel size from IOMobileFramebuffer. Scale 0 makes
        # SpringBoard's FBSDisplayMode "infxinf@0x" invalid. 1080x2400 @3x =
        # 360x800 points (like iPhone X class devices).
        ('display-scale', u32(3)),
        # XNU derives IOPlatformUUID (gethostuuid) from these on arm; without
        # them CFPreferences cannot use kCFPreferencesCurrentHost (no ByHost
        # files), so e.g. DataMigration never records LastSystemVersion and
        # migrates on every boot. Synthetic ECID (not the phone's); chip-id
        # of the A11 that the iPhone X userland expects.
        ('unique-chip-id', struct.pack('<Q', 0x5357454554000001)),
        ('chip-id', u32(0x8015)),
        # Security status as on a dev-fused, undemoted board (tuple 0,0,1,1):
        # MobileGestalt reads these from /chosen, and mobileactivationd's
        # DeviceType then takes its native "Hactivation" branch (state
        # Activated without an activation record; no SEP, no baseband here).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # Local boot policy (kern_csr.c): SIP relaxed like `csrutil disable`
        # (lp-sip0: untrusted kexts, unrestricted FS, task_for_pid, kernel
        # debugger, dtrace, nvram), lp-sip1: unauthenticated (unsealed) root.
        # The iOS shared cache is in no trust cache, so dyld can only map it
        # with CSR_ALLOW_UNRESTRICTED_FS (vm_unix.c shared region checks).
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # SMP: all eight cores in physical-core order (0-5 little A55, 6-7 big),
    # one homogeneous cluster. The kernel defaults to one and uses cpus=N to
    # select an initial prefix (N <= 8). QEMU retains a single-CPU tree.
    cpu_nodes = []
    cpu_compat_val = (
        cstr(b['cpu_compat'])
        + (cstr('qcom,kryo470') if b['cpu_compat'] != 'qcom,kryo470' else b'')
        + cstr('ARM,v8')
    )
    for core in range(1 if qemu else b['cpu_count']):
        cpu_nodes.append(node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cpu_compat_val),
            ('reg', u32(core << 8)),  # actual MPIDR Aff1:Aff0, NOT logical ID
            ('cpu-id', u32(core)),   # descriptive: XNU assigns IDs by DT order
            ('cluster-id', u32(0)),  # descriptive; see ml_parse_cpu_topology
            ('cluster-type', u32(0)),  # homogeneous CLUSTER_TYPE_SMP, not AMP
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(core)),  # distinct per-core L2 nodes in live FDT
            ('l3-cache-id', u32(0)),     # shared L3
            ('state', cstr('running' if core == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            ('clock-frequency', u32(2304000000 if core >= 6 else 1804800000)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else b['vtimer_intid'])),
        ('reg', u64(gicd - SOC_BASE, b['gicd_size'], gicr - SOC_BASE, b['gicr_size'])),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        # No hardware: watchdogd checks IODeviceTree:/arm-io/wdt for no-pmu and
        # otherwise crashes trying to set the PMU boot stage (customer builds
        # ignore the -wdt_no_pmu boot-arg).
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        # Main display: IOMobileFramebuffer.framework counts /arm-io children
        # with this device_type and reads the canvas size from the node
        # (the presented iPhone X size, see SweetFramebuffer.cpp);
        # the kernel's AppleCLCD matches the compatible string.
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('sweet,display')),
            ('canvas-width', u32(CANVAS_W)),
            ('canvas-height', u32(CANVAS_H)),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(b['fb'], b['fb_size'])),
        ('width', u32(b['fb_w'])),
        ('height', u32(b['fb_h'])),
        ('stride', u32(b['fb_w'] * 4)),
    ])

    # bsd/dev/sweet_ufs.c: the UFS host ABL leaves running (absolute physical reg).
    ufs = node('sweet-ufs', [
        ph(),
        ('compatible', cstr('qcom,ufshc')),
        ('reg', u64(b['ufs'], b['ufs_size'])),
    ])

    # pmap_compute_max_asids requires the node even when no overrides are set.
    # An absent pmap-max-asids property selects XNU's own MAX_ASIDS default.
    # No effaceable storage: keybagd then reads /private/var/keybags/systembag.kb
    # as a plain plist instead of decrypting it with the effaceable key.
    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # MobileGestalt HomeButtonType = IODeviceTree:/buttons home-button-type
    # (D22AP: 2, no Home button; absent = 0 = Home-button device).
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    # Panic log region. /pram reg = <phys size>; it sits just above the
    # dram-size we expose, so XNU maps it but never allocates into it.
    pram = node('pram', [ph(), ('reg', u64(panic_base) + u64(PANIC_LOG_SIZE))])

    # Identity of the iPhone X whose userland runs here: compatible[0] is
    # hw.model/hw.target (D22AP), model is hw.machine/hw.product
    # (iPhone10,3). 'xiaomi,<board>' selects IODTPlatformExpert matching
    # (KernelConfigTables IONameMatch) and 'xiaomi,sweet' stays for the
    # SweetPlatformExpert personality shared by both board ports.
    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') +
         cstr('xiaomi,' + b['name']) + cstr('xiaomi,sweet') +
         cstr(b['soc_compat']) + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons, pram] + product + ([] if qemu else [ufs]))


def _args(argv):
    board, highmem, dram = 'sweet', False, None
    dump = qemu = False
    out = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--board':
            board = argv[i + 1]
            i += 2
            continue
        if a.startswith('--board='):
            board = a.split('=', 1)[1]
        elif a == '--dram-size':
            dram = int(argv[i + 1], 0)
            i += 2
            continue
        elif a.startswith('--dram-size='):
            dram = int(a.split('=', 1)[1], 0)
        elif a == '--highmem':
            highmem = True
        elif a == '--qemu':
            qemu = True
        elif a == '--dump':
            dump = True
        elif not a.startswith('--'):
            out = a
        i += 1
    return out, board, highmem, dram, dump, qemu


if __name__ == '__main__':
    out, board, highmem, dram, dump, qemu = _args(sys.argv[1:])
    if not out:
        raise SystemExit('usage: mkadt.py OUT.adt [--board sweet|grus] '
                         '[--dump] [--qemu] [--highmem] [--dram-size BYTES]')
    root = build(qemu=qemu, highmem=highmem, board=board, dram_size=dram)
    blob = adt.serialize(root)
    open(out, 'wb').write(blob)
    if dump:
        adt.dump(adt.parse(blob)[0])
    print(f'{out}: {len(blob)} bytes (board {board})', file=sys.stderr)
