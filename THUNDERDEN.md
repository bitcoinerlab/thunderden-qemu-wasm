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

Attach the standard UVC device to an emulated xHCI controller:

```sh
-device qemu-xhci,id=xhci \
-videodev frame-file,id=cam0,path=/camera.yuyv \
-device usb-video,bus=xhci.0,videodev=cam0
```

`path` is in the **emulator host** filesystem (Emscripten's FS in a browser), not
the guest filesystem. It contains exactly 614,400 bytes: one 640×480 YUYV frame,
row-major, no padding. The virtual camera advertises 10 fps. Publish new frames
by writing another file and atomically renaming it over this path. Frames already
being read retain their original inode. This camera interface uses ordinary host
files rather than guest-memory injection.

This permits the same camera device and frame backend to be exercised natively
before browser capture is connected. It is not physical USB passthrough and does
not require WebUSB or a USB-connected host camera.

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
The initial build is a **headless development milestone**: framebuffer presentation,
browser input and live camera capture need integration in the website. Compiling
successfully alone does not establish that Thunderden runs in a browser.

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
The Wasm build produced a roughly 12 MiB binary. Both browser smoke tests passed
in headless Chromium on Linux: backend discovery, then QMP startup with an emulated
UVC camera and virtio RNG device. These do not boot the guest image, deliver camera
frames or validate recovery-word generation in the browser.

The generated Emscripten loader uses Web Crypto's `crypto.getRandomValues()` for
its random device. The guest RNG path still needs an end-to-end generation check;
never replace it with deterministic seeds, snapshots or `Math.random()`.

## Next integration milestone

1. Present the emulated framebuffer and forward keyboard input in the website.
2. Boot the same checksum-pinned preview.8 image inside the browser.
3. Connect `getUserMedia()` to the existing frame-file backend; repeat the native
   static QR proof, then test animated QR streams and cancellation.
4. Verify guest RNG initialization and recovery-word generation without camera
   entropy. Camera entropy/NIST assessment and its timing need separate testing.
5. Measure on Chrome/macOS, including Apple Silicon, before claiming support;
   Safari and Firefox are separate validation targets.
