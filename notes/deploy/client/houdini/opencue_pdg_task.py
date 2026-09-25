"""Run one PDG work item as one OpenCue frame.

Runs in the OpenCue venv on the render node:

    python opencue_pdg_task.py <task dir> <frame number>

The scheduler writes <task dir>/<frame number>.json with the work item's
command and environment. The command still holds __PDG_HYTHON__,
__PDG_PYTHON__ and __PDG_HFS__: where Houdini is installed differs from machine
to machine, so they are resolved here from this node's dcc.toml, the same way
ocrun does for every other job.

ASCII ONLY.
"""
import json
import os
import subprocess
import sys

import ocrun


def houdini_paths(config, version, python):
    """(hfs, hython, python) of this node's Houdini, or None if not installed."""
    bindir = config.get("houdini", {}).get(version)
    if not bindir:
        return None
    hython = ocrun.find_program(bindir, "hython")
    if not hython:
        return None
    hfs = os.path.dirname(os.path.normpath(bindir))
    if os.name == "nt":
        python = os.path.join(hfs, "python" + python, "python.exe")
    else:
        python = os.path.join(hfs, "python", "bin", "python")
    return hfs, hython, python


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    task_dir, frame = argv
    with open(os.path.join(task_dir, frame + ".json")) as f:
        task = json.load(f)

    path, config = ocrun.load_config()
    paths = houdini_paths(config, task["houdini"], task["python"])
    if not paths:
        print("[pdg] houdini {0} is not configured in {1}".format(task["houdini"], path),
              file=sys.stderr)
        return 127
    hfs, hython, python = paths
    command = (task["command"].replace("__PDG_HYTHON__", hython)
               .replace("__PDG_PYTHON__", python).replace("__PDG_HFS__", hfs))

    # The work item's variables first, so dcc.toml only fills in what is left.
    os.environ.update(task["env"])
    env = ocrun.build_env(config, "houdini")
    print("[pdg] {0}: {1}".format(task["item"], command), flush=True)
    return subprocess.call(command, env=env, shell=task["shell"], cwd=task["cwd"])


if __name__ == "__main__":
    sys.exit(main())
