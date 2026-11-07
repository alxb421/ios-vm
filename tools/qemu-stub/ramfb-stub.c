// QEMU virt fw_cfg MMIO: data +0, selector +8 (BE16), DMA +16 (BE64).
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;

#define FW		0x09020000UL
#define FW_SEL		(*(volatile u16 *)(FW + 8))
#define FW_DMA		(*(volatile u64 *)(FW + 16))
#define FW_DIR		0x19
#define DMA_READ	2
#define DMA_SELECT	8
#define DMA_WRITE	16

#define FB_BASE		0x9c000000UL
#define FB_W		1080
#define FB_H		2400
#define FB_FOURCC	0x34325241	// 'AR24' = DRM_FORMAT_ARGB8888 (B,G,R,A in memory)

static inline u32 be32(u32 x) { return __builtin_bswap32(x); }
static inline u64 be64(u64 x) { return __builtin_bswap64(x); }

struct dma { u32 control; u32 length; u64 address; } __attribute__((aligned(16)));
static volatile struct dma cmd;

static int fw_dma(u32 control, u32 sel, void *buf, u32 len)
{
	cmd.control = be32(control | (sel ? DMA_SELECT | (sel << 16) : 0));
	cmd.length = be32(len);
	cmd.address = be64((u64)buf);
	__asm__ volatile("dsb sy" ::: "memory");
	FW_DMA = be64((u64)&cmd);
	while (be32(cmd.control) & ~1u)
		;
	return be32(cmd.control) & 1;	// 1 = error
}

struct entry { u32 size; u16 select; u16 reserved; char name[56]; };
struct ramfb_cfg { u64 addr; u32 fourcc; u32 flags; u32 width; u32 height; u32 stride; } __attribute__((packed));

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b) a++, b++;
	return *a == *b;
}

void ramfb_setup(void)
{
	static u32 count;
	static struct entry e;
	static struct ramfb_cfg cfg;

	if (fw_dma(DMA_READ, FW_DIR, &count, 4))
		return;
	count = be32(count);
	// the directory stream continues after the count: read entries one by one
	for (u32 i = 0; i < count; i++) {
		if (fw_dma(DMA_READ, 0, &e, sizeof e))
			return;
		if (streq(e.name, "etc/ramfb")) {
			cfg.addr = be64(FB_BASE);
			cfg.fourcc = be32(FB_FOURCC);
			cfg.flags = 0;
			cfg.width = be32(FB_W);
			cfg.height = be32(FB_H);
			cfg.stride = be32(FB_W * 4);
			fw_dma(DMA_WRITE, __builtin_bswap16(e.select), &cfg, sizeof cfg);
			return;
		}
	}
}
