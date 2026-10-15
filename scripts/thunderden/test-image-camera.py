"""Exercise the original image's UVC driver, scanner and address verifier.

Requires Linux, Pillow, qrencode and tesseract. Only a public BIP39 fixture is
entered. No extra initramfs, guest agent or modified image is used.
"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time

from PIL import Image


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("qemu", type=Path)
parser.add_argument("image", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--virtio-readonly", action="store_true", help="Use the browser's read-only virtio boot disk instead of an IDE snapshot")
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
image = args.image.resolve()
before = digest(image)
source = Path(__file__).resolve().parents[2]
address = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
subprocess.run(["qrencode", "-s", "6", "-m", "4", "-o", str(out / "qr.png"), address], check=True)
with Image.open(out / "qr.png") as qr:
    qr = qr.convert("RGBA").convert("L").point(lambda value: 16 + value * 219 // 255)
    frame = Image.new("L", (640, 480), 235)
    frame.paste(qr, ((640 - qr.width) // 2, (480 - qr.height) // 2))
raw = bytearray([128]) * (640 * 480 * 2)
raw[::2] = frame.tobytes()
frame_path = out / "camera.yuyv"
frame_path.write_bytes(raw)
qmp_path = out / "qmp.sock"
if qmp_path.exists():
    raise RuntimeError(f"Remove the old test socket first: {qmp_path}")

drive = "if=virtio,readonly=on" if args.virtio_readonly else "if=ide,snapshot=on"
command = [str(args.qemu.resolve()), "-m", "1024", "-smp", "1", "-cpu", "qemu64",
           "-L", str(source / "pc-bios"), "-display", "none", "-nic", "none", "-no-reboot",
           "-drive", f"file={image},format=raw,{drive}",
           "-vga", "none", "-device", "VGA,xres=1280,yres=800",
           "-device", "virtio-rng-pci", "-device", "qemu-xhci,id=xhci",
           "-videodev", f"frame-file,id=cam0,path={frame_path}",
           "-device", "usb-video,bus=xhci.0,videodev=cam0",
           "-qmp", f"unix:{qmp_path},server=on,wait=off"]

with (out / "qemu.log").open("wb") as log:
    process = subprocess.Popen(command, stdout=log, stderr=log)
    connection = socket.socket(socket.AF_UNIX)
    try:
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"QEMU exited; inspect {out / 'qemu.log'}")
            try:
                connection.connect(str(qmp_path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("QMP startup timed out")
                time.sleep(0.1)
        connection.settimeout(15)
        stream = connection.makefile("rwb")
        json.loads(stream.readline())

        def qmp(name, arguments=None):
            stream.write(json.dumps({"execute": name, "arguments": arguments or {}}).encode() + b"\n")
            stream.flush()
            while True:
                response = json.loads(stream.readline())
                if "error" in response:
                    raise RuntimeError(response)
                if "return" in response:
                    return response["return"]

        def key(value):
            qmp("human-monitor-command", {"command-line": f"sendkey {value} 30"})
            time.sleep(0.07)

        def wait_for(text, name, timeout=90):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("QEMU exited during guest test")
                capture = out / "screen.ppm"
                qmp("screendump", {"filename": str(capture)})
                ocr = subprocess.run(["tesseract", str(capture), "stdout", "--psm", "11"],
                                     capture_output=True, text=True, check=True).stdout
                (out / "screen.txt").write_text(ocr)
                if text.casefold() in ocr.casefold():
                    capture.replace(out / f"{name}.ppm")
                    print(f"Reached {name}", flush=True)
                    return
                time.sleep(0.5)
            raise TimeoutError(f"Did not see {text!r}; inspect {out / 'screen.txt'}")

        qmp("qmp_capabilities")
        usb = qmp("human-monitor-command", {"command-line": "info usb"})
        assert "QEMU USB Video Interface" in usb, usb
        wait_for("Choose a Bitcoin network", "network")
        key("ret")  # Mainnet: only the publicly known fixture is used.
        wait_for("What would you like to do", "menu")
        key("ret")  # Scan a QR code.
        wait_for("Generate new recovery words", "recovery-choice")
        key("ret")  # Use existing words.
        wait_for("How many words", "word-count")
        key("ret")  # Twelve words.
        wait_for("Word 1 of 12", "word-entry")
        for word in ["abandon"] * 11 + ["about"]:
            for char in word:
                key(char)
            key("ret")
        wait_for("Wallet passphrase", "passphrase")
        key("ret")
        wait_for("Account number", "qr-decoded")
        key("ret")
        wait_for("Address verified", "address-verified")
        qmp("quit")
        process.wait(timeout=15)
        assert process.returncode == 0, f"QEMU exited with status {process.returncode}"
        stream.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        connection.close()
        qmp_path.unlink(missing_ok=True)
        after = digest(image)
        (out / "image-hashes.json").write_text(json.dumps({"before": before, "after": after}, indent=2) + "\n")
        assert before == after, "Guest image changed"

print("PASS: unchanged image scanned a virtual UVC camera and verified the public fixture address")
