// Reset stub for QEMU virt: program ramfb (fw_cfg "etc/ramfb") to scan out the
// framebuffer XNU draws at FB_BASE, then jump to the kernel with x0 = boot_args.
// Loaded at 0x40200000 by tools/qemu-sweet.py --window. The host patches the
// two quads below (boot_args, entry) before loading.
	.section .text.start
	.global _start
_start:
	b	1f
	.balign 8
params:
	.quad	0			// boot_args pa
	.quad	0			// kernel entry pa
1:	adr	x1, params
	ldp	x19, x20, [x1]
	ldr	x0, =0x40240000		// stack, above the stub
	mov	sp, x0
	bl	ramfb_setup
	mov	x0, x19
	br	x20
