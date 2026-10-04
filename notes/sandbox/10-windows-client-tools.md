# 10 — Windows Artist Client Tools

Earlier sandbox notes installed client utilities exclusively inside WSL Ubuntu for initial infrastructure validation.
**In production pipelines, artists work natively on Windows desktops.** Artists require Windows-native execution of `cuesubmit` (job submission) and `cuegui` (job monitoring) to prevent operational friction.

## Installation

Using the Windows Python 3.11.9 virtual environment:

```bash
C:\Users\<user>\opencue-win-venv\Scripts\python.exe -m pip install \
    ./proto ./pycue ./pyoutline ./cuegui ./cuesubmit
```

Result: **Installation succeeded without errors.**

Installed dependencies:

```
opencue_cuegui, opencue_cuesubmit, opencue_pyoutline
PySide6 6.5.3 (+Addons +Essentials)
Qt.py 2.0.7, nodegraphqt 0.6.43, types-PySide6
```

Note: PySide6 6.5.3 was pulled in previously during CueNIMBY installation.

## CueGUI Verification

```powershell
$env:CUEBOT_HOSTS = "localhost"
Start-Process "C:\Users\<user>\opencue-win-venv\Scripts\cuegui.exe"
```

The process launched cleanly with `Responding: True`. Stderr reported standard first-run initialization notices:

```
WARNING Layout  Local config file not found at C:/Users/<user>/AppData/Roaming/.cuecommander/config.ini
WARNING Layout  Copying ...\cuegui\config\cuecommander.ini to C:/Users/<user>/AppData/Roaming/.cuecommander/config.ini
```

CueGUI persists layout configuration to `%APPDATA%\.cuecommander\config.ini`.

**Pending**: UI layout, job table rendering, and interactive operations require visual confirmation by artists.

## Configuring Remote Cuebot on Windows Clients

Resolution order in `pycue/opencue/config.py` (highest to lowest priority):

1. File designated by `OPENCUE_CONFIG_FILE` environment variable
2. Environment variable `OPENCUE_CONF` (deprecated, retained for compatibility)
3. `opencue.yaml` located under the configuration base directory
4. Package default `default.yaml`

**The configuration base directory is platform-dependent** (`config.py:54-58`):

```python
if platform.system() == 'Windows':
    return os.path.join(os.path.expandvars('%APPDATA%'), 'opencue')
return os.path.join(os.path.expanduser('~'), '.config', 'opencue')
```

The standard Windows path is **`%APPDATA%\opencue\opencue.yaml`**.

Configuration format (referencing `pycue/opencue/default.yaml`):

```yaml
cuebot.facility_default: local
cuebot.facility:
    local:
        - linux-server.studio.local:8443
```

Template available at [`notes/deploy/client/opencue-client.yaml`](../deploy/client/opencue-client.yaml).

While `CUEBOT_HOSTS` can override this setting directly, distributing a clean configuration file to `%APPDATA%\opencue\` avoids per-machine environment variable maintenance.

### Note: Path Inconsistency Between CueNIMBY and pycue

| Component | Configuration Path on Windows |
|---|---|
| pycue / cuegui / cuesubmit | `%APPDATA%\opencue\opencue.yaml` |
| CueNIMBY | `%USERPROFILE%\.config\opencue\cuenimby.json` |

CueNIMBY uses Linux convention `~/.config` without platform branching (`cuenimby/config.py:59`), scattering configuration files across two directories and causing Pitfall #10 (`mkdir` missing `parents=True`).

## DCC Application Submitters

In studio production, artists submit jobs directly from DCC menus inside Maya or Nuke rather than launching standalone CueSubmit.
The repository includes built-in plugins under `cuesubmit/plugins/` (not top-level `plugins/`):

```
cuesubmit/plugins/maya/
    CueMayaSubmit.py
    userSetup.py            <- Auto-loaded on Maya startup
    opencue_logo_small.png
cuesubmit/plugins/nuke/
    CueNukeSubmit.py
    CueNukeSubmitLauncher.py
    menu.py                 <- Nuke menu registration
```

**Only Maya and Nuke submitters are provided; Blender is not supported out-of-the-box.** Blender workflows require custom pyoutline wrappers or standalone CueSubmit / CLI submissions.

## Items for Verification

> **Note**: This section reflects findings at the time of initial testing. Several items have since been validated.
> **Refer to [`19-verification-summary.md`](19-verification-summary.md) for the definitive status matrix.**

| Item | Notes |
|---|---|
| CueGUI UI | Requires manual verification of layout, job lists, and interactions |
| CueSubmit | Standalone submission interface startup validation |
| Real job submission | Submit real render jobs from Windows CueSubmit (Maya/Blender/Nuke) |
| Remote Cuebot | Evaluated on localhost; requires validating cross-machine LAN `opencue.yaml` |
