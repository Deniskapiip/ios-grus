/*
 * Board profiles for the ios-sweet boot shim.
 *
 * The shim is board-thin: it only needs the GIC, the bootloader framebuffer,
 * the UFS host and the arch timer. Everything else is decided by the XNU
 * Apple Device Tree (tools/mkadt.py --board <name>).
 *
 *   -DBOARD_GRUS   Xiaomi Mi 9 SE (grus, Qualcomm SDM712/SDM710)
 *   default        Xiaomi Redmi Note 10 Pro (sweet, Qualcomm SM7150)
 *
 * All numbers here come from the platform device tree in
 * LineageOS/android_kernel_xiaomi_sdm710 (sdm670.dtsi, grus-sdm710.dtsi)
 * and from the live FDT facts recorded in ios-sweet NOTES.md.
 */
#pragma once

#if defined(BOARD_GRUS)
/* ---- Xiaomi Mi 9 SE: SDM710, PM660 + PM660L, EA8076 1080x2340 ---- */
#define BOARD_NAME	"grus"
#define BOARD_SOC	"qcom,sdm710"
#define GICD_BASE	0x17a00000UL
#define GICR_BASE	0x17a60000UL
#define GICR_SIZE	0x100000UL
#define GICR_PE_SIZE	0x20000UL
/* reserved-memory cont_splash_region@9c000000, size 0x2300000 */
#define FB_BASE		0x9c000000UL
#define FB_W		1080
#define FB_H		2340
#define FB_STRIDE	(FB_W * 4)	/* a8r8g8b8, as ABL leaves it */
#define FB_SIZE		0x2300000UL
/* ufshc@1d84000, one lane, same host as sweet */
#define UFS_BASE	0x01d84000UL
#define UFS_SIZE	0x3000UL
/* arm,armv8-timer: 19.2 MHz XO, Qualcomm PPI numbering -> vtimer INTID 19 */
#define BOARD_TIMEBASE	19200000UL
#else
/* ---- Xiaomi Redmi Note 10 Pro: SM7150, PM6150 + PM6150L, 1080x2400 ---- */
#define BOARD_NAME	"sweet"
#define BOARD_SOC	"qcom,sm7150"
#define GICD_BASE	0x17a00000UL
#define GICR_BASE	0x17a60000UL
#define GICR_SIZE	0x100000UL
#define GICR_PE_SIZE	0x20000UL
/* reserved-memory cont_splash_region@9c000000, size 0x1700000 */
#define FB_BASE		0x9c000000UL
#define FB_W		1080
#define FB_H		2400
#define FB_STRIDE	(FB_W * 4)
#define FB_SIZE		0x1700000UL
#define UFS_BASE	0x01d84000UL
#define UFS_SIZE	0x3000UL
#define BOARD_TIMEBASE	19200000UL
#endif
