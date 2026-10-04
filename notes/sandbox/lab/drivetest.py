"""Verify whether RQD frames can access network drive letters and UNC paths.

Paths construct backslashes via chr(92) to avoid stripping during shell / heredoc pass-through.
"""
import os, sys, platform, time

B = chr(92)  # backslash
frame = os.environ.get("CUE_IFRAME", "0")
SERVER = "192.168.0.107"
SHARE = "chordee"
DIR = "opencue-drivetest"

targets = [
    ("Drive Letter",        "H:" + B + DIR),
    ("UNC Backslash",       B + B + SERVER + B + SHARE + B + DIR),
    ("UNC Forward Slash",   "//" + SERVER + "/" + SHARE + "/" + DIR),
]

print("=== RQD frame network path verification ===")
print("host   :", platform.node())
print("frame  :", frame)
print("user   :", os.environ.get("USERNAME") or os.environ.get("USER"))
print()

fail = 0
for label, base in targets:
    print("%-20s %s" % (label, base))
    try:
        if not os.path.isdir(base):
            print("                     -> Directory not found (isdir=False)")
            fail += 1
            continue
        p = os.path.join(base, "f%s_%s.txt" % (frame, label.replace(" ", "")))
        with open(p, "w", encoding="utf-8") as f:
            f.write("frame %s %s\n" % (frame, time.ctime()))
        print("                     -> Write successful (%d bytes)" % os.path.getsize(p))
    except Exception as e:
        print("                     -> Failed %s: %s" % (type(e).__name__, e))
        fail += 1

print()
print("Result :", "All passed" if fail == 0 else "%d check(s) failed" % fail)
sys.exit(1 if fail else 0)
