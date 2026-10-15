#!/bin/sh
set -eu

# Run inside the upstream Dockerfile's builder, with this repo at /qemu and a
# writable output directory at /out. No guest image is rebuilt or unpacked.
mkdir -p /out/source /out/build /out/emulator
# Meson downloads pinned subprojects into the source directory. Use a writable
# snapshot rather than giving the container write access to the developer clone.
tar -C /qemu --exclude=.git --exclude=./build -cf - . | tar -C /out/source -xf -
cd /out/build

flags="-O2 -g1 -Wno-error=unused-command-line-argument -matomics -mbulk-memory"
flags="$flags -DNDEBUG -DG_DISABLE_ASSERT -D_GNU_SOURCE -sASYNCIFY=1 -pthread"
flags="$flags -sPROXY_TO_PTHREAD=1 -sFORCE_FILESYSTEM -sALLOW_TABLE_GROWTH"
flags="$flags -sTOTAL_MEMORY=2300MB -sWASM_BIGINT -sMALLOC=mimalloc"
flags="$flags --js-library=/build/node_modules/xterm-pty/emscripten-pty.js"
flags="$flags -sEXPORT_ES6=1 -sASYNCIFY_IMPORTS=ffi_call_js"

emconfigure /out/source/configure --static --target-list=x86_64-softmmu \
    --cpu=wasm32 --cross-prefix= --without-default-features \
    --enable-system --enable-pixman --disable-v4l2 --disable-docs \
    --with-coroutine=fiber --disable-werror \
    --extra-cflags="$flags" --extra-cxxflags="$flags" \
    --extra-ldflags="-sEXPORTED_RUNTIME_METHODS=getTempRet0,setTempRet0,addFunction,removeFunction,TTY,FS,callMain"

emmake make -j"${JOBS:-4}" qemu-system-x86_64
cp qemu-system-x86_64 /out/emulator/qemu-system-x86_64.js
cp qemu-system-x86_64.wasm qemu-system-x86_64.worker.js /out/emulator/
cp /out/source/pc-bios/bios-256k.bin /out/source/pc-bios/vgabios-stdvga.bin \
    /out/source/pc-bios/kvmvapic.bin /out/source/pc-bios/linuxboot_dma.bin /out/emulator/
