# Thunderden browser emulator

This fork combines:

- [ktock/qemu-wasm](https://github.com/ktock/qemu-wasm), based on QEMU 8.2,
  at `0ef7b4e2814b231705d8371dd7997f5b72e70baf`;
- 9elements' UVC video subsystem, backported from commit
  [`72ecd6a1af0f2c7602eb3ecbadceb8f39ee1fe70`](https://github.com/9elements/qemu/commit/72ecd6a1af0f2c7602eb3ecbadceb8f39ee1fe70);
- a host-side `frame-file` camera backend for native fixtures and browser capture.

The website lives in
[thunderden-web](https://github.com/bitcoinerlab/thunderden-web).
**Thunderden's release image must remain byte-for-byte unchanged.** Do not add a
guest agent, replacement scanner, kernel module or extra initramfs.

## Camera interface

Attach the standard UVC device to a virtual USB 2 EHCI controller, as used by
the companion website:

```sh
-device usb-ehci,id=ehci \
-videodev frame-file,id=cam0,path=/camera.yuyv,mode=browser \
-device usb-video,bus=ehci.0,videodev=cam0
```

`path` is in the **emulator host** filesystem (Emscripten's FS in a browser), not
the guest filesystem. It contains one complete, row-major YUYV frame, no padding:

| Mode | Dimensions | Bytes | Virtual frame rate |
| --- | --- | --- | --- |
| `standard` (default) | 640×480 | 614,400 | 10 fps |
| `browser` | 320×240 | 153,600 | 2 fps |

Publish new frames by writing another file and atomically renaming it over this
path. Frames already being read retain their original inode. This camera interface
uses ordinary host files rather than guest-memory injection. The browser mode
reduces capture/decoding work and old-frame buffering in the emulated guest.

The same camera device and frame backend are exercised natively and through
browser capture. It is not physical USB passthrough and does not require WebUSB
or a USB-connected host camera.

## Wasm build

Docker builds use the upstream Emscripten 3.1.50 toolchain; the host's Emscripten
version is not used. The original build instructions remain in `README.md`.

```sh
docker build -t thunderden-qemu-wasm-builder .
mkdir -p build/thunderden-wasm
docker run --rm \
  -v "$PWD:/qemu:ro" \
  -v "$PWD/build/thunderden-wasm:/out" \
  thunderden-qemu-wasm-builder sh /qemu/scripts/thunderden/compile-wasm.sh
```

The loader, worker, Wasm binary and BIOS assets are written to
`build/thunderden-wasm/emulator/`. These are generated artifacts, not source files.
The emulator itself is headless. The companion website now presents its framebuffer
and forwards keyboard input using QMP, without changing the guest. See
[the website's local-start instructions](https://github.com/bitcoinerlab/thunderden-web#open-the-interactive-prototype-locally).
The website's **Enable camera** button requests browser permission and feeds
local frames to the existing host-side camera backend.

## Native development

QEMU Wasm defaults to its Emscripten coroutine backend even in native builds;
select `--with-coroutine=ucontext` explicitly on Linux. For a minimal native build:

```sh
mkdir -p build/native
cd build/native
../../configure --without-default-features --target-list=x86_64-softmmu \
  --enable-system --enable-tcg --enable-pixman --enable-vnc \
  --disable-v4l2 --disable-docs --disable-werror --with-coroutine=ucontext
make -j4 qemu-system-x86_64
```

Use `-nic none`, a virtual RNG, and `snapshot=on` for guest-image testing. Test
only public recovery-word fixtures; never put real wallet material in logs or
screenshots. The native image/QR test records image hashes before and after.

## Checks

```sh
python3 scripts/thunderden/test-video-device.py build/native/qemu-system-x86_64
# Requires Pillow, qrencode and tesseract:
python3 scripts/thunderden/test-image-camera.py \
  build/native/qemu-system-x86_64 /path/to/thunderden.img /path/to/new-test-output
# Match the browser's read-only virtio boot disk:
python3 scripts/thunderden/test-image-camera.py \
  build/native/qemu-system-x86_64 /path/to/thunderden.img /path/to/other-test-output \
  --virtio-readonly
# Exercise the smaller, lower-rate camera mode:
python3 scripts/thunderden/test-image-camera.py \
  build/native/qemu-system-x86_64 /path/to/thunderden.img /path/to/browser-mode-test-output \
  --virtio-readonly --camera-mode browser
# Requires Python Playwright and an installed Chromium:
python3 scripts/thunderden/test-wasm.py build/thunderden-wasm/emulator \
  --chromium /path/to/chromium
```

On 2026-10-15, the native integration test passed using the downloaded, checksum-
verified `v0.0.1-preview.8` release. The real image booted, its isolated scanner
decoded a QR through the emulated USB webcam, and its address verifier confirmed
the public BIP39 fixture's first BIP84 receiving address. Image SHA-256 before
and after:

```text
43f3a7b9bcb5febea564f2f02a4137cb176c73a31392abe98581865094b94d4d
```

Native registration, QOM property reads and repeated unplug/replug also passed.
The full native camera/address proof also passed with `--virtio-readonly`, matching
the website's boot-disk configuration, with the same before/after image hash.
The Wasm build produced a roughly 12 MiB binary. Both browser smoke tests passed
in headless Chromium on Linux: backend discovery, then QMP startup with an emulated
UVC camera and virtio RNG device. These do not boot the guest image, deliver camera
frames or validate recovery-word generation in the browser.

The generated Emscripten loader uses Web Crypto's `crypto.getRandomValues()` for
its random device. The guest RNG path still needs an end-to-end generation check;
never replace it with deterministic seeds, snapshots or `Math.random()`.

## Interactive browser boot

On 2026-10-15 the companion website booted the same checksum-pinned preview.8 image
inside Chromium on Linux. An automated check read the actual framebuffer and used
browser keyboard events to select Regtest, enter the public-key menu and return
with Escape. The network chooser appeared in about 23 seconds.

The working browser configuration uses a read-only virtio boot disk:

```sh
-drive file=/thunderden.img,format=raw,if=virtio,readonly=on
```

IDE snapshot initialization stalled in the browser; its exact cause has not been
isolated. Keep the proven read-only virtio configuration for the website.

## Browser camera integration

### Browser camera proof

On 2026-10-15, the companion website's camera test passed in Chromium on Linux.
Chromium's synthetic webcam delivered a public fixture QR through the real
`getUserMedia()` API, RGBA-to-YUYV conversion, host frame file and emulated UVC
device. The unchanged preview.8 image decoded it and verified the fixture address.
Permission denial/retry, camera stop/restart and disconnection handling also passed.
No physical webcam was accessed, and no real wallet material was used.

The website uses EHCI for this path. xHCI device registration and native scanning
passed earlier, but its Wasm guest scanner timed out despite receiving USB video
data. EHCI passed the end-to-end browser scan without changing the guest image
or guest clock configuration. The cause of the xHCI timeout is not isolated.

### Responsiveness

The website now uses a 640×480 guest display and the `browser` camera mode. A
Linux/Chromium numbered-video comparison measured about 0.5 seconds of camera
frame age, versus 7–8 seconds with the original 1280×800 display and 640×480/10 fps
camera. The original guest's software preview rendering is expensive under x86-64
Wasm emulation; feeding frames faster than it can consume them produces stale
frames. Merely increasing website repaint frequency does not remove that backlog.

The website separately reduced its screenshot wait from 500 ms to 33 ms, keeping
one request in flight. Camera frame age, display refresh cadence and guest camera
frame rate are different measurements. The browser mode intentionally caps the
virtual camera at 2 fps, and does not establish macOS or physical-webcam performance.

Both camera modes passed the native public-fixture QR/address test, with the
unchanged release hash above. The website's 120-second numbered-video check
measured about 0.51 seconds median frame age, 0.79 seconds maximum observed age
and 1.99 complete frame changes per second, then cancelled the original scanner.

### Remaining checks

1. Test physical webcams and animated QR streams; repeat cancellation across browsers.
2. Verify guest RNG initialization and recovery-word generation without camera
   entropy. Camera entropy/NIST assessment and its timing need separate testing.
3. Measure on Chrome/macOS, including Apple Silicon, before claiming support;
   Safari and Firefox are separate validation targets.
