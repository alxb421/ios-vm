#!/usr/bin/env python3
"""Boot a SWEETXNU payload in QEMU and show it inside a phone frame.

  qemu-phone.py PAYLOAD OUTDIR [--scale S] [--grab OUT.png --grab-after SECS]

QEMU runs without a window of its own. Guest RAM is a shared file in /dev/shm,
and this window maps the framebuffer XNU draws at 0x9c000000 straight out of it,
so there is no screenshot polling. tools/phone-frame.png is drawn on top.

The side buttons in the frame (mute, volume up/down, power) are clickable;
keyboard: PageUp / PageDown = volume, End = power. Each press is sent to QEMU
over QMP (input-send-event) as a qcode key, routed to a virtio-keyboard-pci
device. The guest kernel needs a virtio-input driver to act on them (not
written yet): until then the events arrive in QEMU and iOS ignores them.
"""
import argparse, importlib.util, json, mmap, os, socket, struct, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('qemu_sweet', os.path.join(HERE, 'qemu-sweet.py'))
qs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qs)

RAM_BASE = 0x40000000		# QEMU virt RAM start
FB_W, FB_H, FB_STRIDE, FB_BASE = qs.FB_W, qs.FB_H, qs.FB_STRIDE, qs.FB_BASE
FB_BYTES = FB_STRIDE * FB_H
# Measured on frame.png (343x657): screen = the transparent area around the centre
SCREEN = (28, 24, 279, 609)	# x, y, w, h in frame pixels
# name -> (x, y, w, h, qcode). Hit boxes are wider than the drawn buttons.
BUTTONS = {
    'mute':        (0, 128, 22, 30, 'audiomute'),
    'volume up':   (0, 174, 22, 56, 'volumeup'),
    'volume down': (0, 236, 22, 56, 'volumedown'),
    'power':       (321, 209, 22, 82, 'power'),
}
KEYS = {'PgUp': 'volumeup', 'PgDown': 'volumedown', 'End': 'power'}


class Qmp:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(path)
        self.f = self.s.makefile('rw')
        self.f.readline()
        self.call('qmp_capabilities')

    def call(self, execute, **args):
        self.f.write(json.dumps({'execute': execute, 'arguments': args}) + '\n')
        self.f.flush()
        while True:
            r = json.loads(self.f.readline())
            if 'return' in r or 'error' in r:
                return r

    def key(self, qcode, down):
        ev = {'type': 'key', 'data': {'down': down, 'key': {'type': 'qcode', 'data': qcode}}}
        r = self.call('input-send-event', events=[ev])
        if 'error' in r:
            print(f'qmp key {qcode}: {r["error"]["desc"]}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('payload')
    ap.add_argument('outdir')
    ap.add_argument('--scale', type=float, default=0, help='window scale of the 343x657 frame (default: fit the screen)')
    ap.add_argument('--cpu', default='cortex-a76')
    ap.add_argument('--grab', help='render one frame of the window to this PNG and exit (testing)')
    ap.add_argument('--grab-after', type=float, default=30)
    ap.add_argument('--press', help='with --grab: press this button (e.g. "volume up") before grabbing')
    a = ap.parse_args()

    from PyQt5.QtCore import Qt, QRectF, QTimer
    from PyQt5.QtGui import QImage, QPainter, QPixmap, QColor
    from PyQt5.QtWidgets import QApplication, QWidget

    if not qs.check_qemu_dependency(a.cpu):
        return 1
    payload = open(a.payload, 'rb').read()
    out = os.path.abspath(a.outdir)
    os.makedirs(out, exist_ok=True)
    phys_base, img, ba_pa, entry_pa = qs.build_image(payload)
    open(f'{out}/ram.bin', 'wb').write(img)
    open(f'{out}/stub.bin', 'wb').write(qs.stub(ba_pa, entry_pa))
    mem_size = struct.unpack_from('<Q', payload, 0x40)[0]
    ram_gib = max(4, -(-(phys_base + mem_size - RAM_BASE) // (1 << 30)))
    mon = f'/dev/shm/ios-vm-mon-{os.getpid()}.sock'	# AF_UNIX paths are limited to 108 bytes
    if os.path.exists(mon):
        os.unlink(mon)
    shm = f'/dev/shm/ios-vm-ram-{os.getpid()}'
    cmd = ['qemu-system-aarch64', '-M', 'virt,gic-version=3,memory-backend=ram0', '-cpu', a.cpu, '-smp', '1',
           '-m', f'{ram_gib}G',
           '-object', f'memory-backend-file,id=ram0,size={ram_gib}G,mem-path={shm},share=on',
           '-display', 'none', '-serial', f'file:{out}/serial.txt', '-qmp', f'unix:{mon},server,nowait',
           '-d', 'int,guest_errors,unimp', '-D', f'{out}/qemu.log', '-no-reboot',
           '-device', 'virtio-keyboard-pci',
           '-device', f'loader,file={out}/ram.bin,addr={phys_base:#x},force-raw=on',
           '-device', f'loader,file={out}/stub.bin,addr={qs.STUB_PA:#x},force-raw=on',
           '-device', f'loader,addr={qs.STUB_PA:#x},cpu-num=0']
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    fbmap = None
    try:
        t0 = time.time()
        while not (os.path.exists(mon) and os.path.exists(shm)):
            if p.poll() is not None or time.time() - t0 > 30:
                print('qemu did not start', file=sys.stderr)
                return 1
            time.sleep(0.1)
        qmp = Qmp(mon)
        fb_off = FB_BASE - RAM_BASE
        fd = os.open(shm, os.O_RDONLY)
        fbmap = mmap.mmap(fd, FB_BYTES, mmap.MAP_SHARED, mmap.PROT_READ, offset=fb_off)

        app = QApplication(sys.argv[:1])
        frame = QPixmap(os.path.join(HERE, 'phone-frame.png'))
        fw, fh = frame.width(), frame.height()
        scale = a.scale or min(1080 * 0.9 / fh, 3.0)
        scale = min(scale, QApplication.primaryScreen().availableGeometry().height() * 0.9 / fh) if not a.grab else (a.scale or 2.0)

        class Phone(QWidget):
            def __init__(self):
                super().__init__()
                self.setWindowTitle('iOS (XNU on QEMU)')
                self.setFixedSize(int(fw * scale), int(fh * scale))
                self.setFocusPolicy(Qt.StrongFocus)
                self.down = None
                t = QTimer(self)
                t.timeout.connect(self.update)
                t.start(33)

            def r(self, x, y, w, h):
                return QRectF(x * scale, y * scale, w * scale, h * scale)

            def paintEvent(self, _):
                p = QPainter(self)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.fillRect(self.rect(), QColor(0, 0, 0, 0))
                img = QImage(fbmap, FB_W, FB_H, FB_STRIDE, QImage.Format_RGB32)
                p.drawImage(self.r(*SCREEN), img)
                p.drawPixmap(self.rect(), frame)
                if self.down:
                    x, y, w, h, _q = BUTTONS[self.down]
                    p.fillRect(self.r(x, y, w, h), QColor(255, 255, 255, 90))

            def press(self, name, down):
                self.down = name if down else None
                qmp.key(BUTTONS[name][4], down)

            def mousePressEvent(self, e):
                for name, (x, y, w, h, _q) in BUTTONS.items():
                    if self.r(x, y, w, h).contains(e.pos()):
                        self.press(name, True)
                        return

            def mouseReleaseEvent(self, e):
                if self.down:
                    self.press(self.down, False)

            def keyPressEvent(self, e):
                for name, (_x, _y, _w, _h, q) in BUTTONS.items():
                    if e.key() == {'volumeup': Qt.Key_PageUp, 'volumedown': Qt.Key_PageDown,
                                   'power': Qt.Key_End}.get(q) and not e.isAutoRepeat():
                        self.press(name, True)

            def keyReleaseEvent(self, e):
                if self.down and not e.isAutoRepeat():
                    self.press(self.down, False)

        w = Phone()
        w.show()
        if a.grab:
            def grab():
                if a.press:
                    w.press(a.press, True)
                    app.processEvents()
                w.grab().save(a.grab)
                if a.press:
                    w.press(a.press, False)
                app.quit()
            QTimer.singleShot(int(a.grab_after * 1000), grab)
        app.exec_()
        return 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        for f in (shm, mon, f'{out}/ram.bin'):
            try:
                os.unlink(f)
            except OSError:
                pass


if __name__ == '__main__':
    sys.exit(main())
