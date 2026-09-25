"""OpenCue side of the PDG scheduler (opencuescheduler.py).

Runs in the OpenCue venv, not in Houdini: Houdini's Python cannot load the
opencue package (different Python version, needs grpc). The scheduler starts
this as a subprocess with a JSON request on stdin and reads a JSON reply on
stdout.

    python opencue_pdg_helper.py submit|status|kill < request.json

ASCII ONLY.
"""
import json
import sys

import opencue
import outline
from outline.modules.shell import Shell

KILL_REASON = "PDG cook cancelled"


def find_service(tag):
    for service in opencue.api.getDefaultServices():
        if tag in service.tags():
            return service.name()
    return None


def submit(request):
    service = find_service(request["service_tag"])
    if not service:
        return {"error": "No service has the {0} tag.".format(request["service_tag"])}
    ol = outline.Outline(request["name"], shot=request["shot"], show=request["show"],
                         user=request["user"])
    ol.add_layer(Shell(request["layer"], command=request["command"], range=request["range"],
                       service=service))
    # No OpenCue retries: a rerun adds the work item's outputs a second time,
    # and whether a work item failed is PDG's call.
    job = outline.cuerun.launch(ol, use_pycuerun=False, maxretries=0)[0]
    return {"job": job.name(), "log_dir": job.logDir()}


def _jobs(names):
    return opencue.api.getJobs(job=names, include_finished=True)


def status(request):
    """Frame states of each job, {job: {frame number: state name}}."""
    reply = {}
    for job in _jobs(request["jobs"]):
        # A frame search returns 500 frames unless told otherwise.
        frames = job.getFrames(limit=job.data.job_stats.total_frames or 1)
        reply[job.name()] = dict(
            (str(f.number()), opencue.api.job_pb2.FrameState.Name(f.state())) for f in frames)
    return reply


def kill(request):
    """Kill whole jobs, or only some frames when "frames" maps a job to frame numbers."""
    frames = request.get("frames", {})
    for job in _jobs(request["jobs"]):
        if job.name() in frames:
            numbers = ",".join(str(n) for n in frames[job.name()])
            job.killFrames(reason=KILL_REASON, range=numbers)
        else:
            job.kill(reason=KILL_REASON)
    return {}


COMMANDS = {"submit": submit, "status": status, "kill": kill}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    request = json.load(sys.stdin)
    try:
        reply = COMMANDS[argv[0]](request)
    except Exception as e:  # pylint: disable=broad-except
        reply = {"error": "{0}: {1}".format(type(e).__name__, e)}
    json.dump(reply, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
