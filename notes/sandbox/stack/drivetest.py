"""驗證 RQD frame 能否存取網路磁碟機代號與 UNC 路徑。

路徑用 chr(92) 組出反斜線，避免經過 shell / heredoc 時被跳脫吃掉。
"""
import os, sys, platform, time

B = chr(92)  # backslash
frame = os.environ.get("CUE_IFRAME", "0")
SERVER = "192.168.0.107"
SHARE = "chordee"
DIR = "opencue-drivetest"

targets = [
    ("磁碟機代號",   "H:" + B + DIR),
    ("UNC 反斜線",   B + B + SERVER + B + SHARE + B + DIR),
    ("UNC 正斜線",   "//" + SERVER + "/" + SHARE + "/" + DIR),
]

print("=== RQD frame 網路路徑測試 ===")
print("host   :", platform.node())
print("frame  :", frame)
print("使用者 :", os.environ.get("USERNAME") or os.environ.get("USER"))
print()

fail = 0
for label, base in targets:
    print("%-12s %s" % (label, base))
    try:
        if not os.path.isdir(base):
            print("             -> 目錄不存在 (isdir=False)")
            fail += 1
            continue
        p = os.path.join(base, "f%s_%s.txt" % (frame, label.replace(" ", "")))
        with open(p, "w", encoding="utf-8") as f:
            f.write("frame %s %s\n" % (frame, time.ctime()))
        print("             -> 寫入成功 (%d bytes)" % os.path.getsize(p))
    except Exception as e:
        print("             -> 失敗 %s: %s" % (type(e).__name__, e))
        fail += 1

print()
print("結果:", "全部成功" if fail == 0 else "%d 項失敗" % fail)
sys.exit(1 if fail else 0)
