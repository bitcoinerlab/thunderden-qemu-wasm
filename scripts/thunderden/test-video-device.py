"""Smoke-test camera registration, QOM properties and unplug/replug without a guest."""

import argparse
import json
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("qemu")
args = parser.parse_args()
process = subprocess.Popen([
    args.qemu, "-machine", "q35", "-nodefaults", "-display", "none", "-S",
    "-device", "qemu-xhci,id=xhci",
    "-videodev", "frame-file,id=cam0,path=/unused.yuyv", "-qmp", "stdio",
], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

try:
    assert "QMP" in json.loads(process.stdout.readline())

    def qmp(command, arguments=None):
        process.stdin.write(json.dumps({"execute": command, "arguments": arguments or {}}) + "\n")
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            assert line, "QEMU closed QMP unexpectedly"
            response = json.loads(line)
            assert "error" not in response, response
            if "return" in response:
                return response["return"]

    qmp("qmp_capabilities")
    for _ in range(2):
        qmp("device_add", {"driver": "usb-video", "id": "camera", "bus": "xhci.0", "videodev": "cam0"})
        tree = qmp("human-monitor-command", {"command-line": "info qtree"})
        assert 'videodev = "cam0"' in tree, tree
        qmp("device_del", {"id": "camera"})
        usb = qmp("human-monitor-command", {"command-line": "info usb"})
        assert "QEMU USB Video Interface" not in usb, usb
    qmp("quit")
    _, errors = process.communicate(timeout=10)
    assert process.returncode == 0, errors
    print("PASS: UVC camera registration, property reads and repeated unplug/replug")
finally:
    if process.poll() is None:
        process.kill()
        process.communicate()
