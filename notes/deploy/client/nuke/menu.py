# Adds OpenCue > Submit to the Nuke menu bar.
# Nuke runs this file when its directory is on NUKE_PATH, and also puts the
# directory on sys.path, so opencue_nuke_launcher can be imported.
import nuke

nuke.menu("Nuke").addCommand(
    "OpenCue/Submit to OpenCue",
    "import opencue_nuke_launcher; opencue_nuke_launcher.submit()")
