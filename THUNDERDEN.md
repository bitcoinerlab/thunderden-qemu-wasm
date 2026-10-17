# Thunder Den browser emulator

This fork provides the virtual computer behind
[Thunder Den Web](https://github.com/bitcoinerlab/thunderden-web).
[Thunder Den](https://github.com/bitcoinerlab/thunderden) is a small Linux system
that turns a spare laptop into an air-gapped Bitcoin signer. Here, QEMU emulates
that laptop inside a browser using WebAssembly, including a virtual USB webcam
for QR scanning. The website supplies the screen, keyboard controls and optional
browser-camera capture; this repository supplies the emulator and its build tools.

**This is an experimental demo, not a signer for real funds.** A browser is not
an air-gapped device. Use only public test fixtures, never real recovery words.
The integration runs the original Thunder Den software: the release image stays
byte-for-byte unchanged, with no guest agent, replacement application, kernel
module or extra initramfs.

## Upstream projects

This fork combines:

- [ktock/qemu-wasm](https://github.com/ktock/qemu-wasm), based on QEMU 8.2,
  at `0ef7b4e2814b231705d8371dd7997f5b72e70baf`;
- 9elements' USB Video Class (UVC) subsystem, backported from
  [`72ecd6a1af0f2c7602eb3ecbadceb8f39ee1fe70`](https://github.com/9elements/qemu/commit/72ecd6a1af0f2c7602eb3ecbadceb8f39ee1fe70);
- a `frame-file` camera backend for native tests and browser capture.

The original [README](README.md) retains the upstream instructions and examples.
The commands below describe the Thunder Den integration.

## Wasm build

You need Docker. Run these commands from the root of this repository:

```sh
docker build -t thunderden-qemu-wasm-builder .
mkdir -p build/thunderden-wasm
docker run --rm \
  -v "$PWD:/qemu:ro" \
  -v "$PWD/build/thunderden-wasm:/out" \
  thunderden-qemu-wasm-builder sh /qemu/scripts/thunderden/compile-wasm.sh
```

The loader, worker, Wasm binary and BIOS files are written to
`build/thunderden-wasm/emulator/`. These are generated artifacts, not source files.
Keep this checkout beside `thunderden-web`, then follow the
[website's local setup instructions](https://github.com/bitcoinerlab/thunderden-web#run-locally)
to copy the assets and start the demo.

The builder uses Emscripten 3.1.50 rather than a host-installed SDK. Its Dockerfile
backports the upstream synchronous-proxy lifetime correction
[#26582](https://github.com/emscripten-core/emscripten/pull/26582), commit
`f3fef05bf5d63df33ed21eb067b86d827c546bfa`, and rebuilds both threaded libc
variants. The correction signals completion before releasing the context mutex,
so a caller cannot retire its stack context before the signalling thread's final
access. It changes the emulator runtime, not Thunder Den. Rebuild the builder and
emulator together, then rerun website setup when changing this runtime.

### Runtime smoke test

This standalone check exercises 200,000 synchronous runtime calls. It needs
Node.js and the Docker builder, but no guest image or wallet material:

```sh
mkdir -p build/runtime-proxy
docker run --rm -v "$PWD:/qemu:ro" -v "$PWD/build/runtime-proxy:/out" \
  thunderden-qemu-wasm-builder emcc /qemu/scripts/thunderden/test-runtime-proxy.c \
  -O2 -pthread -sPROXY_TO_PTHREAD=1 -sPTHREAD_POOL_SIZE=5 \
  -sENVIRONMENT=node -sEXIT_RUNTIME=1 -o /out/proxy.cjs
node build/runtime-proxy/proxy.cjs
```

This is a stress smoke test, not a deterministic reproduction of the upstream
race or proof that every intermittent emulator-control stall is resolved.

## Camera interface

The website turns local browser video into complete frames and supplies them to
the emulator's host filesystem. The `frame-file` backend reads those frames and
presents a standard USB webcam to Thunder Den's existing driver and QR reader.
There is no guest-memory injection, physical USB passthrough or WebUSB dependency.

Attach the camera to a virtual USB 2 EHCI controller:

```sh
-device usb-ehci,id=ehci \
-videodev frame-file,id=cam0,path=/camera.yuyv,mode=browser \
-device usb-video,bus=ehci.0,videodev=cam0
```

`path` is in the **emulator host** filesystem (Emscripten's filesystem in a
browser), not the guest filesystem. It contains one complete, row-major YUYV
frame with no padding:

| Mode | Dimensions | Bytes per frame | Target frame rate |
| --- | --- | --- | --- |
| `standard` (default) | 640×480 | 614,400 | 10 fps |
| `browser` | 320×240 | 153,600 | 10 fps |

Publish a frame by writing another file and atomically renaming it over this
path. Readers already using the previous file keep its original inode. The
smaller browser profile reduces capture and decoding work, but its target cadence
does not guarantee that the emulated guest can display ten new frames per second.

Normal gaps between scheduled frames return zero-length isochronous transfers,
not error-marked UVC headers that would make the guest reject a capture buffer.
Actual backend read failures still fail the transfer; guest validation is not
bypassed.

The website uses EHCI because its end-to-end Wasm scan passed. An xHCI
configuration registered and passed native scanning but timed out during Wasm
guest scanning; its cause has not been isolated.

## Browser boot

The companion website verifies its pinned release image, reads the existing
`/bzImage` from the FAT32 boot partition and supplies it to QEMU's `-kernel`
option. The root filesystem and applications are built into this kernel. No
separate kernel download, replacement application or extra initramfs is needed.
The original image remains attached as a read-only virtio disk:

```sh
-drive file=/thunderden.img,format=raw,if=virtio,readonly=on
```

The single-CPU browser profile uses:

```sh
-kernel /thunderden-kernel -no-acpi \
-append 'console=tty1 quiet loglevel=3 acpi=off random.trust_cpu=off random.trust_bootloader=off'
```

Disabling ACPI reduces firmware discovery work in the emulated machine. The
website covers quiet startup until it recognizes the original network menu;
raw console viewing and manual control remain available. The kernel and image
are unchanged, but **direct boot skips GRUB**. This demo does not validate the
USB bootloader, UEFI or Secure Boot. Native image-camera tests use disk boot.

## Native development

QEMU Wasm defaults to its Emscripten coroutine backend even in native builds.
Select `--with-coroutine=ucontext` explicitly on Linux. With the native QEMU
build dependencies installed, a minimal build is:

```sh
mkdir -p build/native
cd build/native
../../configure --without-default-features --target-list=x86_64-softmmu \
  --enable-system --enable-tcg --enable-pixman --enable-vnc \
  --disable-v4l2 --disable-docs --disable-werror --with-coroutine=ucontext
make -j4 qemu-system-x86_64
```

For guest-image tests, disable networking with `-nic none`, supply a virtual RNG
and use either `snapshot=on` or a read-only disk. Never put real wallet material
in test inputs, logs or screenshots. The image-camera test compares image hashes
before and after the run.

## Integration checks

Run these from the repository root. The native camera test additionally needs
Pillow, `qrencode` and `tesseract`. The Wasm smoke test needs Python Playwright
and Chromium.

```sh
python3 scripts/thunderden/test-video-device.py build/native/qemu-system-x86_64
python3 scripts/thunderden/test-image-camera.py \
  build/native/qemu-system-x86_64 /path/to/thunderden.img /path/to/new-test-output
# Use the browser's read-only disk and smaller camera mode:
python3 scripts/thunderden/test-image-camera.py \
  build/native/qemu-system-x86_64 /path/to/thunderden.img /path/to/other-test-output \
  --virtio-readonly --camera-mode browser
python3 scripts/thunderden/test-wasm.py build/thunderden-wasm/emulator \
  --chromium /path/to/chromium
```

Image-camera checks use the public BIP39 `abandon`/`about` vector and the unchanged
`v0.0.1-preview.8` release. Its SHA-256 is:

```text
43f3a7b9bcb5febea564f2f02a4137cb176c73a31392abe98581865094b94d4d
```

Native checks cover device registration, property reads, unplug/replug and an
actual guest QR/address flow. The Wasm smoke test checks backend discovery and
QEMU monitor startup with the virtual webcam and RNG; it does not boot Thunder
Den or deliver camera frames. End-to-end browser tests live in the
[website's development guide](https://github.com/bitcoinerlab/thunderden-web/blob/main/docs/DEVELOPMENT.md).

## Current limits

Recorded native and Linux/Chromium checks cover the public QR/address flow.
Browser checks also cover keyboard navigation, camera permission/lifecycle,
startup failures and one animated transaction QR fixture that cancels at review
without signing. Synthetic webcams do not establish physical-camera compatibility
or support for every animated QR format.

Camera-based randomness is not working end to end. Synthetic collection can
finish, but statistical assessment has exceeded the unchanged guest's time limit.
The website's collection test checks delivery and cancellation, not entropy
quality or successful word generation. The generated Emscripten loader uses
Web Crypto's `crypto.getRandomValues()` for its random device, but the guest RNG
path and recovery-word generation still need end-to-end browser validation.
Never substitute deterministic seeds or `Math.random()` for that path.

Physical webcams, broader QR coverage, macOS, Safari, Firefox and actual
background-tab/resume behavior need further validation. Screen refresh rate,
camera-frame age and guest camera throughput are separate measurements; no
cross-platform performance or signing-security guarantee is made.
