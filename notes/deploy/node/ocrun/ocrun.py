"""Run a DCC program on an OpenCue render node, on Windows or Linux.

    ocrun <product> <version> <program> [args...]

    ocrun maya 2027 Render -r file -s #IFRAME# -e #IFRAME# P:/proj/scene.ma
    ocrun houdini 22.0.429 hython P:/proj/render.py
    ocrun nuke 17.0v1 Nuke17.0 -t P:/proj/render.py

Where each version is installed differs from machine to machine, so it is
looked up in a per-machine config file (dcc.toml). Job commands therefore stay
the same on every node, whatever the OS.

ASCII ONLY.
"""
import os
import shutil
import subprocess
import sys
import tomllib

if sys.platform == "win32":
    DEFAULT_CONFIG = r"C:\opencue\dcc.toml"
else:
    DEFAULT_CONFIG = "/opt/opencue/dcc.toml"

# Environment a product needs on every node, whatever the machine.
PRODUCT_ENV = {
    # A crashing mayabatch opens Autodesk's error reporting dialog
    # (cer_dialog.exe) on the desktop, where nobody answers it.
    "maya": {"MAYA_DISABLE_CER": "1"},
}

# Output that means the frame failed even though the program exits with 0.
# Matched case-insensitively against each line; any match fails the frame.
PRODUCT_FAIL_PATTERNS = {
    # Maya's Render exits with 0 when Arnold cannot get a license and aborts,
    # so the frame would count as done with no image written.
    "maya": [b"aborting render because", b"license checkout error"],
}


def load_config():
    path = os.environ.get("OPENCUE_DCC_CONFIG", DEFAULT_CONFIG)
    with open(path, "rb") as f:
        return path, tomllib.load(f)


def build_env(config, product):
    env = dict(os.environ)
    # RQD passes TMP to frames but not TEMP, and several DCCs read TEMP only.
    tmp = env.get("TMP") or env.get("TMPDIR")
    if tmp:
        env.setdefault("TEMP", tmp)
    env.update(PRODUCT_ENV.get(product, {}))
    env.update(config.get("env", {}))
    if product == "nuke" and "NUKE_DISK_CACHE" not in env:
        # Without it Nuke falls back to C:\temp\nuke, which does not exist on a
        # render node, and every frame fails.
        env["NUKE_DISK_CACHE"] = os.path.join(env.get("TEMP", "/tmp"), "nuke")
        os.makedirs(env["NUKE_DISK_CACHE"], exist_ok=True)
    return env


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path, config = load_config()
    if len(argv) < 3:
        print("usage: ocrun <product> <version> <program> [args...]")
        print("configured in %s:" % path)
        for product, versions in config.items():
            if product != "env":
                for version, bindir in versions.items():
                    print("  %s %s  %s" % (product, version, bindir))
        return 2

    product, version, program, args = argv[0], argv[1], argv[2], argv[3:]
    bindir = config.get(product, {}).get(version)
    if not bindir:
        print("[ocrun] %s %s is not configured in %s" % (product, version, path),
              file=sys.stderr)
        return 127
    exe = shutil.which(program, path=bindir)
    if not exe:
        print("[ocrun] %s not found in %s" % (program, bindir), file=sys.stderr)
        return 127

    print("[ocrun] %s %s: %s %s" % (product, version, exe, " ".join(args)), flush=True)
    patterns = PRODUCT_FAIL_PATTERNS.get(product)
    if not patterns:
        return subprocess.call([exe] + args, env=build_env(config, product))
    return run_checked(exe, args, build_env(config, product), patterns)


def run_checked(exe, args, env, patterns):
    """Run the program, pass its output through, and fail on a known error line."""
    matched = None
    proc = subprocess.Popen([exe] + args, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = sys.stdout.buffer
    for line in proc.stdout:
        out.write(line)
        out.flush()
        lower = line.lower()
        if matched is None and any(p in lower for p in patterns):
            matched = line.strip()
    rc = proc.wait()
    if rc == 0 and matched is not None:
        print("[ocrun] failing the frame, the output reported: %s"
              % matched.decode("utf-8", "replace"), flush=True)
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
