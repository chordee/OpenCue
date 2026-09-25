"""OpenCue scheduler for PDG (TOP networks).

Cook one TOP node at a time: the work items that become ready together go out
as one OpenCue job, one work item per frame. The results come back to this
Houdini session, so it has to stay open until the cook ends.

With the tool directory on HOUDINI_PATH (the Houdini package sets it), this file
is found as <tool dir>/pdg/types/opencuescheduler.py and TOP networks get a
"pdg_opencuescheduler" node.

Houdini's Python cannot load the opencue package (different Python version,
needs grpc), so OpenCue is reached through opencue_pdg_helper.py in the OpenCue
venv, and every frame runs opencue_pdg_task.py there.

ASCII ONLY.
"""
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

import hou
import pdg
from pdg import scheduleResult, tickResult
from pdg.job.callbackserver import CallbackServerMixin
from pdg.scheduler import PyScheduler

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HELPER = os.path.join(TOOL_DIR, "opencue_pdg_helper.py")
TASK_SCRIPT = os.path.join(TOOL_DIR, "opencue_pdg_task.py")
VERSION_TAG = "houdini_{0}"

CREATE_NO_WINDOW = 0x08000000
# Houdini points these at its own Python and Qt; the OpenCue venv must not see them.
_INHERITED_PREFIXES = ("PYTHON", "QT_", "QTDIR", "PYSIDE")
_DONE = (pdg.workItemState.CookedSuccess, pdg.workItemState.CookedFail,
         pdg.workItemState.CookedCancel, pdg.workItemState.CookedCache)


def _clean_env():
    return dict((k, v) for k, v in os.environ.items()
                if not k.upper().startswith(_INHERITED_PREFIXES))


def _name(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


class OpenCueScheduler(CallbackServerMixin, PyScheduler):

    @classmethod
    def templateName(cls):
        return "opencuescheduler"

    @classmethod
    def templateBody(cls):
        return json.dumps({
            "name": "opencuescheduler",
            "parameters": [
                {"name": "oc_show", "label": "Show (empty: $PROJECT)", "type": "String",
                 "value": ""},
                {"name": "oc_shot", "label": "Shot", "type": "String", "value": "pdg"},
                {"name": "oc_python", "label": "OpenCue Python", "type": "String",
                 "value": "C:/opencue/venv/Scripts/python.exe"},
                {"name": "oc_batchdelay", "label": "Submit After Idle (s)", "type": "Float",
                 "value": 3.0},
                {"name": "oc_pollperiod", "label": "Poll Period (s)", "type": "Float",
                 "value": 5.0},
                {"name": "oc_portmin", "label": "Callback Port Min (0: any)",
                 "type": "Integer", "value": 0},
                {"name": "oc_portmax", "label": "Callback Port Max", "type": "Integer",
                 "value": 0},
            ]})

    def __init__(self, scheduler, name):
        PyScheduler.__init__(self, scheduler, name)
        CallbackServerMixin.__init__(self, False)
        self._reset()

    def _reset(self):
        self.pending = []       # tasks that go out together as the next job
        self.last_added = 0.0
        self.jobs = {}          # job name -> {frame number: work item id}
        self.logs = {}          # work item id -> frame log path
        self.last_poll = 0.0
        self.batch = 0
        self.cook_stamp = time.strftime("%Y%m%d_%H%M%S")

    # --- cook ---------------------------------------------------------------

    def onStartCook(self, static, cook_set):
        wd = self["pdg_workingdir"].evaluateString()
        self.setWorkingDir(wd, wd)
        low = self["oc_portmin"].evaluateInt()
        high = self["oc_portmax"].evaluateInt()
        self.custom_port_range = (low, high + 1) if low and high >= low else None
        if not self.isCallbackServerRunning():
            self.startCallbackServer()
        self._copyJobSupportFiles()
        self._reset()
        return True

    def onStopCook(self, cancel):
        if cancel and self.jobs:
            self._helper("kill", {"jobs": list(self.jobs)})
        self.pending = []
        self.jobs = {}
        return True

    def applicationBin(self, name, work_item):
        # Kept as tokens: opencue_pdg_task.py fills in the render node's Houdini.
        return "__PDG_HYTHON__" if name == "hython" else "__PDG_PYTHON__"

    def expandCommandTokens(self, item_command, work_item):
        # The base class puts this machine's $HFS in; the render node's differs.
        command = item_command.replace("__PDG_HFS__", "\0HFS\0")
        command = PyScheduler.expandCommandTokens(self, command, work_item)
        return command.replace("\0HFS\0", "__PDG_HFS__")

    def onSchedule(self, work_item):
        command = self.expandCommandTokens(work_item.platformCommand(), work_item)
        if not command:
            return scheduleResult.Failed
        self.createJobDirsAndSerializeWorkItems(work_item)
        self.pending.append({
            "id": work_item.id, "item": work_item.name, "node": work_item.node.name,
            "command": command, "env": self._environment(work_item),
            "shell": work_item.shouldRunInShell, "cwd": self.workingDir(False)})
        self.last_added = time.time()
        return scheduleResult.Succeeded

    def onTick(self):
        now = time.time()
        if self.pending and now - self.last_added >= self["oc_batchdelay"].evaluateFloat():
            self._submit()
        if self.jobs and now - self.last_poll >= self["oc_pollperiod"].evaluateFloat():
            self.last_poll = now
            self._poll()
        return tickResult.SchedulerReady

    def onCancelWorkItems(self, work_items, node):
        wanted = set(w.id for w in work_items)
        self.pending = [t for t in self.pending if t["id"] not in wanted]
        frames = {}
        for job, items in self.jobs.items():
            numbers = [frame for frame, item_id in items.items() if item_id in wanted]
            if numbers:
                frames[job] = numbers
        if frames:
            self._helper("kill", {"jobs": list(frames), "frames": frames})

    def getLogURI(self, work_item):
        path = self.logs.get(work_item.id)
        if not path:
            return ""
        # Built like the Local scheduler's: the log viewer needs file:////host/...
        # for a UNC path, and shows nothing for file://host/...
        return urllib.parse.urlunparse(("file", "", path, "", "", ""))

    # --- helpers ------------------------------------------------------------

    def _environment(self, work_item):
        """Only PDG's variables and the work item's own, never this session's."""
        env = {"PDG_JOBUSE_PDGNET": "0"}
        for key, value in work_item.environment.items():
            env[key.strip()] = self.localizePath(str(value).strip())
        self.addCommonJobEnvVars(env, work_item)
        temp_dir = self.tempDir(False)
        env.update({"PDG_DIR": self.workingDir(False), "PDG_TEMP": temp_dir,
                    "PDG_SHARED_TEMP": temp_dir, "PDG_SCRIPTDIR": self.scriptDir(False)})
        for key in ("HIP", "HIPNAME", "JOB"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _submit(self):
        tasks, self.pending = self.pending, []
        self.batch += 1
        version = hou.applicationVersionString()
        python = "{0}{1}".format(sys.version_info.major, sys.version_info.minor)
        task_dir = "{0}/opencue/{1}_{2:03d}".format(
            self.tempDir(True), self.cook_stamp, self.batch).replace("\\", "/")
        os.makedirs(task_dir)
        for frame, task in enumerate(tasks, 1):
            task.update(houdini=version, python=python)
            with open("{0}/{1}.json".format(task_dir, frame), "w") as f:
                json.dump(task, f)

        layer = _name(tasks[0]["node"])
        if len(layer) < 3:
            layer += "_pdg"
        hip = _name(os.path.splitext(hou.hipFile.basename())[0])
        reply = self._helper("submit", {
            "name": "pdg_{0}_{1}_{2}_{3}".format(hip, layer, self.cook_stamp, self.batch),
            "show": self["oc_show"].evaluateString() or os.environ.get("PROJECT", ""),
            "shot": self["oc_shot"].evaluateString(),
            "user": getpass.getuser(),
            "layer": layer,
            "service_tag": VERSION_TAG.format(version.replace(".", "_")),
            "command": ["python", TASK_SCRIPT, task_dir, "#IFRAME#"],
            "range": "1-{0}".format(len(tasks))})
        if "error" in reply:
            self.cookWarning("OpenCue submit failed: " + reply["error"])
            for task in tasks:
                self.workItemFailed(task["id"], -1)
            return

        job = reply["job"]
        self.jobs[job] = {}
        for frame, task in enumerate(tasks, 1):
            self.jobs[job][frame] = task["id"]
            self.logs[task["id"]] = "{0}/{1}.{2:04d}-{3}.rqlog".format(
                reply["log_dir"], job, frame, layer)
            self.workItemStartCook(task["id"], -1)

    def _poll(self):
        """Finish work items from their frame states.

        A frame ends SUCCEEDED or DEAD by its exit code; the work item has
        already sent its outputs through the callback server by then.
        """
        reply = self._helper("status", {"jobs": list(self.jobs)})
        if "error" in reply:
            self.cookWarning("OpenCue status failed: " + reply["error"])
            return
        graph = self.context.graph
        for job, items in list(self.jobs.items()):
            states = reply.get(job, {})
            running = False
            for frame, item_id in items.items():
                work_item = graph.workItemById(item_id)
                if work_item is None or work_item.state in _DONE:
                    continue
                state = states.get(str(frame))
                if state == "SUCCEEDED":
                    self.workItemSucceeded(item_id, -1, 0.0)
                elif state in ("DEAD", "EATEN"):
                    self.workItemFailed(item_id, -1)
                else:
                    running = True
            if not running:
                del self.jobs[job]

    def _helper(self, command, request):
        """Run opencue_pdg_helper.py in the OpenCue venv; returns its JSON reply."""
        try:
            proc = subprocess.run(
                [self["oc_python"].evaluateString(), HELPER, command],
                input=json.dumps(request), capture_output=True, text=True, timeout=120,
                env=_clean_env(), creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"error": str(e)}
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return {"error": (proc.stderr or proc.stdout).strip()[-1000:]}


def registerTypes(type_registry):
    type_registry.registerScheduler(OpenCueScheduler)
