/*
 * Just enough flattened-device-tree parsing for the shim:
 *   - /chosen linux,initrd-start/end (where ABL put our payload)
 *   - a read-only diagnostic dump of /memory and /reserved-memory so the
 *     board's real RAM layout is visible before XNU is started.
 * Big-endian, 4-byte aligned tokens.
 */
#include "fdt.h"
#include "console.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9

static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static int strprefix(const char *a, const char *p)
{
	while (*p && *a == *p)
		a++, p++;
	return *p == 0;
}

static uintptr_t align4(uintptr_t a)
{
	return (a + 3) & ~3UL;
}

static uintptr_t skip_str(uintptr_t p)
{
	/* byte loads are fine on Device memory as long as they are aligned to 1 */
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

/* Big-endian 64-bit value from a 1 or 2 cell reg entry. */
static uint64_t cell_be(uintptr_t p, uint32_t len, int hi)
{
	if (len == 8)
		return (uint64_t)be32(p) << 32 | be32(p + 4);
	if (len == 4)
		return hi ? 0 : be32(p);
	return 0;
}

int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

void fdt_dump_memory(uintptr_t fdt)
{
	if (!fdt || be32(fdt) != FDT_MAGIC) {
		con_str("FDT", "no live tree");
		return;
	}
	uintptr_t p = fdt + be32(fdt + 8);
	uintptr_t strings = fdt + be32(fdt + 12);
	int depth = 0;
	int region = 0;		/* 1 = /memory, 2 = /reserved-memory parent, 3 = rsv child */
	unsigned mem_count = 0, rsv_count = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			if (depth == 2) {
				if (strprefix(name, "memory"))
					region = 1;
				else if (streq(name, "reserved-memory"))
					region = 2;
				else
					region = 0;
			} else if (depth == 3 && region == 2) {
				region = 3;
			} else if (depth == 2) {
				region = 0;
			}
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (region == 3)
				region = 2;
			else if (depth == 2)
				region = 0;
			depth--;
			if (depth <= 0)
				return;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			const char *pname = (const char *)(strings + nameoff);
			if (region == 1 && streq(pname, "reg") &&
			    (len == 8 || len == 16) && mem_count < 2) {
				uint64_t base = cell_be(val, len, 1);
				uint64_t size = cell_be(val + (len == 16 ? 8 : 4), len, len == 16);
				con_hex("MEM base", base);
				con_hex("MEM size", size);
				mem_count++;
			} else if (region == 3 && streq(pname, "reg") && len <= 16 &&
			    rsv_count < 8) {
				uint64_t base = cell_be(val, len, 1);
				uint64_t size = cell_be(val + (len == 16 ? 8 : 4), len, len == 16);
				if (size && base >= 0x80000000UL) {
					con_hex("RSV base", base);
					con_hex("RSV size", size);
					rsv_count++;
				}
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:
			return;
		}
	}
}
