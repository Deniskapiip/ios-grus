#!/usr/bin/env python3
import subprocess

with open(r'G:\ios_grus_port\ios-grus\out\apple_logo.h', 'r') as f:
    apple_code = f.read()

path = r'G:\ios_grus_port\repos\xnu\osfmk\console\serial_console.c'
with open(path, 'r') as f:
    src = f.read()

# Replace SWEET_CON_ROWS
old_rows = '#define SWEET_CON_ROWS      (SWEET_CON_H / SWEET_CON_CH)'
new_rows = '#define SWEET_CON_ROWS      44u\n\n' + apple_code

assert old_rows in src, 'SWEET_CON_ROWS not found'
src = src.replace(old_rows, new_rows)

draw_apple_func = """
static void
sweet_con_draw_apple_logo(void)
{
	volatile uint32_t *fb = sweet_con_fb;
	if (fb == 0) {
		return;
	}
	unsigned int start_x = (SWEET_CON_W - APPLE_LOGO_W) / 2;
	unsigned int start_y = 1500;
	for (unsigned int ly = 0; ly < APPLE_LOGO_H; ly++) {
		const unsigned char *row = &apple_logo_bitmap[ly * APPLE_LOGO_STRIDE];
		for (unsigned int lx = 0; lx < APPLE_LOGO_W; lx++) {
			unsigned char byte_val = row[lx / 8];
			if (byte_val & (0x80u >> (lx % 8))) {
				unsigned int px_x = start_x + lx;
				unsigned int px_y = start_y + ly;
				fb[px_y * SWEET_CON_W + (SWEET_CON_W - 1 - px_x)] = 0xffffffffu;
			}
		}
	}
	__asm__ volatile("dsb sy" ::: "memory");
}
"""

old_clear = """static void
sweet_con_clear(void)
{
	volatile uint32_t *fb = sweet_con_fb;
	for (unsigned int y = 0; y < SWEET_CON_H; y++) {
		for (unsigned int x = 0; x < SWEET_CON_W; x++) {
			fb[y * SWEET_CON_W + x] = 0;
		}
	}
	sweet_con_col = 0;
	sweet_con_row = 0;
}"""

new_clear = draw_apple_func + """static void
sweet_con_clear(void)
{
	volatile uint32_t *fb = sweet_con_fb;
	for (unsigned int y = 0; y < SWEET_CON_H; y++) {
		for (unsigned int x = 0; x < SWEET_CON_W; x++) {
			fb[y * SWEET_CON_W + x] = 0;
		}
	}
	sweet_con_col = 0;
	sweet_con_row = 0;
	sweet_con_draw_apple_logo();
}"""

assert old_clear in src, 'old_clear not found'
src = src.replace(old_clear, new_clear)

with open(path, 'w', newline='\n') as f:
    f.write(src)

print('serial_console.c updated in repos/xnu!')

# Generate git diff
diff = subprocess.check_output(['git', '-C', r'G:\ios_grus_port\repos\xnu', 'diff', 'osfmk/console/serial_console.c'])
patch_path = r'G:\ios_grus_port\ios-grus\xnu\patches\0094-sweet-own-console.patch'
with open(patch_path, 'wb') as f:
    f.write(diff)

print('0094-sweet-own-console.patch regenerated successfully via git diff!')
