# ios-grus — порт ios-sweet на Xiaomi Mi 9 SE (`grus`, Snapdragon 712 / SDM710)

Этот каталог — дерево порта `dipa-studio/ios-sweet` (iOS 16.7.16 / `20H392` от
iPhone X, ядро Apple XNU `xnu-8796`) на **Xiaomi Mi 9 SE `grus`**
(Qualcomm SDM712, 6 ГиБ RAM, панель Samsung EA8076 1080×2340, PM660/PM660L,
Goodix GT9886).

Полный отчёт о состоянии, собранных артефактах и блокерах —
`../PORT_STATUS.md`. Фактическая карта железа с адресами —
`../HARDWARE_MAP_GRUS.md`.

## Что отличается от upstream sweet

Платформы родственны (SDM670/SDM710 → SM7150), поэтому **все ключевые
адреса совпадают**, а отличаются PMIC, тач и панель:

| Блок | sweet | grus |
|---|---|---|
| GICD / GICR | 0x17a00000 / 0x17a60000 | **то же** |
| Таймер | 19.2 МГц, vtimer INTID 19 | **то же** |
| UFS | `ufshc@1d84000`, `qcom,ufshc` | **то же** |
| SPMI arbiter (core/obs/cnfg) | 0xc440000 / 0xe600000 / 0xc40a000 | **то же** |
| GENI тача | SE7 @ `0xa84000`, пины TLMM 6/7 | SE9 @ **0xa84000**, пины TLMM 6/7 |
| TLMM (NORTH +0x500000) | 0x03400000 | **то же** |
| GCC | 0x100000 | **то же** |
| Фреймбуфер cont_splash | 0x9c000000, 1080×2400, 0x1700000 | 0x9c000000, **1080×2340**, **0x2300000** |
| PMIC | PM6150 SID0 + PM6150L SID4 | **PM660 SID0 + PM660L SID2** |
| Кнопки | PON + PM6150L GPIO2 | PON + **PM660L GPIO7** |
| Тач | Goodix GT9896 (0x4180) | **Goodix GT9886/GT9889 GTx8 (0x824e)** |
| Питание тача | RPMh `ldoc11` (3.2 В) | **RPMh `ldoa13` (1.8 В) + `ldob8` (3.3 В)** |
| CPU | 6×A55 + 2×A76 | 6×A55 + 2×A75 |

## Ключевое проектное решение: класс машины SWEET, доска — рантайм

Так как GIC, таймер, UFS, SPMI и адрес фреймбуфера совпадают, порт **не вводит
новую XNU machine config**. Ядро собирается с `MACHINE_CONFIG=SWEET`
(проверенный на железе класс: GICv3 + Group 1 IRQ, 16K pages, ARMv8.2 без PAC,
SMP через PSCI), а отличия платы выбираются в рантайме:

* **`tools/mkadt.py --board grus`** — Apple Device Tree под grus
  (фреймбуфер 0x9c000000 1080×2340, `dram-base 0x1_00000000`,
  `/product` от реального D22AP, identity iPhone X).
* **boot-arg `grus=1`** (его кладёт `tools/mkimg-grus.sh` в payload) —
  драйверы кнопок, тача и регуляторов берут адреса PM660/PM660L и протокол
  GTx8 вместо PM6150/GT9896. Без этого аргумента ядро ведёт себя как sweet.

Это меньшее по риску решение: 100% кода машины уже проверено на sweet, а наши
изменения — только в четырёх драйверных файлах (патч
`0082-grus-board-runtime.patch`, 4 файла, +214/−56 строк).

## Что изменено в этом дереве

1. **`shim/board.h`** — профили плат (`-DBOARD_GRUS` / `-DBOARD_SWEET`):
   GIC, адрес и геометрия фреймбуфера, UFS, частота таймера. `build.sh`
   собирает нужный профиль (`BOARD=grus`), DTB передаётся через `DTB=...`.
2. **`shim/fdt.c` / `shim/loader.c`** — перед прыжком в XNU шим печатает
   живой FDT: `/memory` и первые `/reserved-memory` (ABL подставляет реальный
   размер DRAM; на grus он не выводится из исходников платы).
3. **`tools/mkadt.py`** — `--board sweet|grus` (+ `--dram-size`). Для grus:
   `sweet-fbcon` = 0x9c000000/0x2300000/1080×2340, `dram-base` = 0x1_00000000,
   `dram-size` = 0x70000000 (1.75 ГиБ, безопасно для 6 ГиБ модели), canvas
   остаётся iPhone X 1125×2436 (иначе SpringBoard не примет FBSDisplayMode).
   Root-compatible содержит `xiaomi,grus` и `xiaomi,sweet` (последний — матч
   `SweetPlatformExpert`, чтобы не трогать проверенный platform expert).
4. **`xnu/patches/0082-grus-board-runtime.patch`** — единственный новый патч
   к серии из 81 upstream-патча. Применяется чисто (проверено `git apply` на
   точном CI-базлайне xnu-8796.141.3 + blacktop sed-правки).
   * `bsd/dev/sweet_keys.c`: при `grus=1` volume-up читается с PM660L SID 2
     GPIO7 (PPID 0x2c6, статус 0xc610, mode 0xc640, enable 0xc646,
     subtype 0xc605); power/vol-down остаются на PM660 PON SID0 0x810.
   * `bsd/dev/sweet_touch.c`: при `grus=1` — Goodix GT9886/GT9889 (GTx8):
     блок 0x824e (2 байта заголовка, n×8 байт координат, 2 байта checksum,
     сумма всех байт = 0; handshake — запись 0x00 в 0x824e); reset TLMM 5,
     IRQ TLMM 125; питание — RPMh `ldoa13` 1.8 В + `ldob8` 3.3 В; лимиты
     координат 1079×2339.
   * `bsd/dev/sweet_rpmh.c`: таблица разрешённых ресурсов
     `ldoc11` (sweet) / `ldoa13` + `ldob8` (grus) вместо жёсткого `ldoc11`;
     кодировка режима PMIC4 LDO HPM = 7 совпадает с уже проверенной sweet.
   * `iokit/Kernel/arm/hid/SweetHID.cpp`: размер панели берётся из boot
     framebuffer (PE_current_console), а не из констант 1080×2400 — на grus
     это 1080×2340, канвас iOS по-прежнему 1125×2436 (letterbox 22/48 px).
5. **`.github/workflows/xnu.yml`** — `machine_config` по умолчанию `SWEET`
   (для grus это правильно), sanity-шаг проверяет наличие grus-патча.
6. **`tools/mkimg-grus.sh`** — одна команда: kernel + ADT → payload →
   `shim-boot.img` (с `grus=1` в boot-args).
7. **`tools/mkiosroot.sh`, `tools/grus-root-tweaks.py`, `tools/grus-log-pull.sh`**
   — копии device-независимых инструментов с grus-именами (пользовательская
   часть iOS одинакова).
8. **`.gitattributes`** — LF для текстовых файлов: серия патчей должна иметь
   LF, иначе `git apply` на macOS-раннере их не примет (это уже случалось при
   Windows-клонировании).

## Сборка

```sh
# 0. окружение (Linux/WSL2): apt install device-tree-compiler gcc-aarch64-linux-gnu \
#    hfsprogs android-sdk-libsparse-utils apfs-fuse rsync python3
# 1. DTB платы (из LineageOS android_kernel_xiaomi_sdm710):
#    arch/arm64/boot/dts/qcom/grus-sdm710.dts -> work/grus.dtb
BOARD=grus DTB=../work/grus.dtb shim/build.sh     # диагностический boot.img
# -> shim/out/shim-boot.img  (ANDROID! v2: kernel=шим, dtb=grus.dtb)

# 2. Apple Device Tree
python3 tools/mkadt.py ../out/grus.adt --board grus --highmem --dram-size 0x70000000

# 3. ядро XNU — облачная сборка GitHub Actions (нужен gh auth):
gh workflow run xnu.yml -R <you>/ios-grus
gh run watch
gh run download <RUN_ID> -n xnu-kernel -D xnu/out

# 4. финальный boot image (kernel + ADT + boot-args с grus=1)
tools/mkimg-grus.sh xnu/out/kernel.development.sweet ../out/grus.adt ../out
# -> ../out/shim-boot.img

# 5. корневая ФС (iPhone X IPSW 16.7.16 20H392)
tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ../work/ios16-root.img 16G
sudo fsck.hfsplus -fy ../work/ios16-root.img
sudo mount -t hfsplus -o loop,force ../work/ios16-root.img /mnt/iosroot
sudo python3 tools/grus-root-tweaks.py /mnt/iosroot
sudo umount /mnt/iosroot
img2simg ../work/ios16-root.img ../out/ios16-root.simg
```

## Порядок первого запуска (на живой плате)

1. `fastboot boot shim-boot.img` **без payload** — диагностика шима: GIC/GICR,
   PSCI, таймер, UFS probe, дамп живого `/memory`. Сверить с
   `HARDWARE_MAP_GRUS.md`.
2. Собрать ядро (п.3) и boot-args `grus=0 sweetkeys=0 sweettouch=0` — проверка,
   что XNU стартует и графика живёт. Это безопасно: драйверы ввода выключены.
3. Включить `grus=1 sweetkeys=1 sweettouch=1` — смотреть persist-лог
   (`tools/grus-log-pull.sh` из recovery). Ожидаемые строки:
   `SWEET KEYS: board=grus ...`, `SWEET TOUCH: board=grus ...`,
   `SWEET TOUCH: probe 0x5d GTx8 reg=0x824e err=0 b0=.. b1=..`.
4. `sweetusb=2` + `tools/grus-usbnet.sh` — живой лог по USB.

> Пункты 2–4 требуют сборки ядра на GitHub Actions (macOS-раннер), поэтому
> нужен `gh auth login`. В окружении, где делался порт, авторизации `gh` не
> было — см. `../PORT_STATUS.md`.
