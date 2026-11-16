#pragma once
#include <stdint.h>

/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);

/*
 * Diagnostics: print the live FDT's /memory ranges and the first
 * /reserved-memory children to the framebuffer console. The shim boots with
 * no knowledge of the board's real RAM layout (ABL injects /memory from the
 * DDR configuration), so the values are logged before the jump into XNU.
 */
void fdt_dump_memory(uintptr_t fdt);
