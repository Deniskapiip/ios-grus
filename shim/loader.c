/*
 * Milestone 4: act as iBoot for xnu.
 *
 * mkpayload.py already resolved the kernel's chained fixups and built the
 * ADT, so this only has to: find the payload in the ABL ramdisk, copy the
 * segments to phys_base + (vmaddr - virt_base), place the ADT and
 * boot_args behind the kernel, and jump to the entry point with the MMU
 * and caches off, x0 = boot_args (physical).
 */
#include <stdint.h>
#include "board.h"
#include "console.h"
#include "fdt.h"
#include "loader.h"
#include "apple_logo.h"

static void draw_apple_logo(void)
{
	volatile uint32_t *fb = (volatile uint32_t *)FB_BASE;
	unsigned int scale = 2;
	unsigned int logo_w = APPLE_LOGO_W * scale;
	unsigned int logo_h = APPLE_LOGO_H * scale;
	unsigned int start_x = (FB_W - logo_w) / 2;
	unsigned int start_y = (FB_H - logo_h) / 2;
	for (unsigned int ly = 0; ly < APPLE_LOGO_H; ly++) {
		const unsigned char *row = &apple_logo_bitmap[ly * APPLE_LOGO_STRIDE];
		for (unsigned int sy = 0; sy < scale; sy++) {
			volatile uint32_t *dst_row = fb + (start_y + ly * scale + sy) * (FB_STRIDE / 4);
			for (unsigned int lx = 0; lx < APPLE_LOGO_W; lx++) {
				if (row[lx / 8] & (0x80u >> (lx % 8))) {
					for (unsigned int sx = 0; sx < scale; sx++) {
						dst_row[start_x + lx * scale + sx] = 0xffffffffu;
					}
				}
			}
		}
	}
}

#define BOOT_LINE_LENGTH	608
#define PAGE_16K		0x4000UL

struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};

struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};

/* pexpert/pexpert/arm64/boot.h, Revision/Version 2 */
struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload header layout");
_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args layout");

/* MMU off: everything is Device memory, so copy in aligned 8-byte words. */
static void copy64(uintptr_t dst, uintptr_t src, uint64_t n)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	volatile const uint64_t *s = (volatile const uint64_t *)src;
	for (uint64_t i = 0; i < (n + 7) / 8; i++)
		d[i] = s[i];
}

static void zero64(uintptr_t dst, uint64_t n)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	for (uint64_t i = 0; i < n / 8; i++)
		d[i] = 0;
}

static int magic_ok(const char *m)
{
	static const char want[] = "SWEETXNU";
	for (int i = 0; i < 8; i++)
		if (m[i] != want[i])
			return 0;
	return 1;
}

typedef void (*xnu_entry_t)(uint64_t boot_args_pa);

/*
 * The kernel keeps a 4 MiB ring of every console byte it printed
 * (sweet_log_ring in bsd/dev/sweet_ufs.c). After a hang the phone is power
 * cycled, DRAM still holds that ring, and the kernel's BSS (where the ring
 * lives) is zeroed by _this_ boot only after we read it. So print what the
 * previous boot managed to say, then wipe the counter and stop: the next
 * power cycle boots normally.
 *
 * The two addresses are kernel links (kernel.development.sweet); they must be
 * refreshed for every kernel build (tools/98_find_log_syms.py prints them).
 */
#define SWEET_LOG_TOTAL_VA	0xfffffe0007c52650ULL
#define SWEET_LOG_RING_VA	0xfffffe0007c52658ULL
#define SWEET_LOG_SIZE		(4u << 20)
#define SWEET_LOG_LINES		44
#define SWEET_LOG_COLS		78

static void sweet_dram_log(uintptr_t pa_of_va_base)
{
	volatile uint64_t *total = (volatile uint64_t *)(SWEET_LOG_TOTAL_VA + pa_of_va_base);
	volatile const char *ring = (volatile const char *)(SWEET_LOG_RING_VA + pa_of_va_base);
	uint64_t n = *total;

	if (n == 0 || n > 512ull * 1024 * 1024) {
		con_hex("LOGPA", (uint64_t)SWEET_LOG_TOTAL_VA + pa_of_va_base);
		con_hex("LOGTOT", n);
		return;
	}

	static char lines[SWEET_LOG_LINES][SWEET_LOG_COLS];
	int head = 0, count = 0, k = 0;
	char cur[SWEET_LOG_COLS];

	uint64_t start = (n > (uint64_t)SWEET_LOG_SIZE) ? n - SWEET_LOG_SIZE : 0;
	for (uint64_t i = start; i < n; i++) {
		char c = ring[i % SWEET_LOG_SIZE];
		if (c == '\n') {
			cur[k] = 0;
			for (int j = 0; j <= k; j++)
				lines[head][j] = cur[j];
			head = (head + 1) % SWEET_LOG_LINES;
			if (count < SWEET_LOG_LINES)
				count++;
			k = 0;
		} else if (c != '\r' && k < SWEET_LOG_COLS - 1) {
			cur[k++] = c;
		}
	}
	if (k) {
		cur[k] = 0;
		for (int j = 0; j <= k; j++)
			lines[head][j] = cur[j];
		head = (head + 1) % SWEET_LOG_LINES;
		if (count < SWEET_LOG_LINES)
			count++;
	}

	con_clear(0x00000000);
	con_puts("==== kernel log from DRAM ====");
	for (int i = 0; i < count; i++) {
		int idx = (head - count + i + SWEET_LOG_LINES) % SWEET_LOG_LINES;
		con_puts(lines[idx]);
	}
	con_puts("==== end (power-cycle to boot) ====");

	*total = 0;
	for (;;)
		__asm__ volatile("wfi");
}

const char *loader_boot(uintptr_t dtb)
{
	uint64_t rd_start, rd_end;

	if (!fdt_chosen_u64(dtb, "linux,initrd-start", &rd_start) ||
	    !fdt_chosen_u64(dtb, "linux,initrd-end", &rd_end))
		return "no initrd in /chosen";
	con_hex2("INITRD", "lo=", rd_start, "hi=", rd_end);

	const struct payload *p = (const struct payload *)rd_start;
	if (!magic_ok(p->magic))
		return "no SWEETXNU payload";
	if (p->version != 1 || (p->adt_off & 7) || (rd_start & 7))
		return "bad payload header";

	/* What ABL actually gave us: /memory and the reserved carve-outs. */
	fdt_dump_memory(dtb);

	uint64_t pa_of_va_base = p->phys_base - p->virt_base;	/* pa = va + this */
	con_hex2("PHYS", "base=", p->phys_base, "size=", p->mem_size);
	con_hex("VIRT", p->virt_base);
	con_hex("ENTRY", p->entry_va);

	/* Previous boot's console log disabled to prevent hangs */
	/* sweet_dram_log(pa_of_va_base); */

	/* The payload must not overlap where the kernel goes. */
	if (rd_end > p->phys_base && rd_start < p->phys_base + p->mem_size)
		return "ramdisk overlaps kernel memory";

	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		uintptr_t dst = s->vmaddr + pa_of_va_base;
		copy64(dst, rd_start + s->file_off, s->file_size);
		if (s->vmsize > s->file_size)
			zero64(dst + ((s->file_size + 7) & ~7UL), s->vmsize - ((s->file_size + 7) & ~7UL));
	}
	con_hex2("SEGS", "n=", p->nsegs, "end=", p->kernel_end + pa_of_va_base);

	/* ADT, then boot_args, behind the kernel; everything below topOfKernelData is ours. */
	uintptr_t adt_pa = p->kernel_end + pa_of_va_base;
	copy64(adt_pa, rd_start + p->adt_off, p->adt_size);
	uintptr_t ba_pa = (adt_pa + p->adt_size + PAGE_16K - 1) & ~(PAGE_16K - 1);
	uintptr_t top = ba_pa + PAGE_16K;

	zero64(ba_pa, PAGE_16K);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = top;
	ba->Video.v_baseAddr = FB_BASE;
	ba->Video.v_display = 1;
	ba->Video.v_rowBytes = FB_STRIDE;
	ba->Video.v_width = FB_W;
	ba->Video.v_height = FB_H;
	ba->Video.v_depth = 32;
	ba->deviceTreeP = adt_pa - pa_of_va_base;	/* xnu reads it with the MMU on: a VA */
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < BOOT_LINE_LENGTH; i++)
		ba->CommandLine[i] = p->cmdline[i];
	ba->memSizeActual = p->mem_size;
	con_hex2("BOOTARG", "pa=", ba_pa, "top=", top);

	uintptr_t entry_pa = p->entry_va + pa_of_va_base;
	con_hex("JUMP", entry_pa);
	con_str("XNU", "jumping (fbcon clears screen)");

	/*
	 * Wipe the console and draw Apple logo: clean iPhone 1:1 boot screen.
	 */
	con_clear(0x00000000);
	draw_apple_logo();

	/* Everything was written with the MMU and caches off; drop any stale I-cache lines too. */
	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	((xnu_entry_t)entry_pa)(ba_pa);
	return "xnu returned";
}
