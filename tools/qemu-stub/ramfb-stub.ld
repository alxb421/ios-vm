ENTRY(_start)
SECTIONS {
	. = 0x40200000;
	/DISCARD/ : { *(.note*) *(.comment) *(.eh_frame) }
	.text : { *(.text.start) *(.text*) *(.rodata*) }
	.data : { *(.data*) }
	.bss : { *(.bss*) *(COMMON) }
}
