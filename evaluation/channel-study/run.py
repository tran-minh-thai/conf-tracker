# SPDX-License-Identifier: MIT
"""Run wrapper: python3 run.py <probe|evaluation|fetch> <label> -- <command...>
Writes ~/data-local/conf-tracker-eval/runs/<stamp>-<label>/{run_meta.json,log.txt}: command verbatim, kind,
sha256 of every *.py in this folder, sha256 of every existing file argument, python version, host, start/end,
exit code. The log holds what the command prints; scripts print counts only, never abstract text."""
import hashlib, json, os, platform, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
kind, label = sys.argv[1], sys.argv[2]; cmd = sys.argv[sys.argv.index("--") + 1:]
assert kind in ("probe", "evaluation", "fetch"), kind
here = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
start = datetime.now(timezone.utc).replace(microsecond=0)
out = Path.home() / "data-local/conf-tracker-eval/runs" / f"{start.strftime('%Y%m%dT%H%M%SZ')}-{label}"
out.mkdir(parents=True)
meta = {"kind": kind, "label": label, "command": cmd, "cwd": str(here), "started": start.isoformat(),
        "python": platform.python_version(), "host": platform.node(), "machine": platform.machine(),
        "code_sha256": {p.name: sha(p) for p in sorted(here.glob("*.py"))},
        "input_sha256": {a: sha(a) for a in cmd if os.path.isfile(a) and not a.endswith(".py")}}
(out / "run_meta.json").write_text(json.dumps(meta, indent=1))
with open(out / "log.txt", "w") as log:
    rc = subprocess.call(cmd, cwd=here, stdout=log, stderr=subprocess.STDOUT)
meta.update({"ended": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "exit_code": rc,
             "outputs_sha256": {p.name: sha(p) for p in sorted(out.glob("*")) if p.name not in ("run_meta.json", "log.txt")}})
(out / "run_meta.json").write_text(json.dumps(meta, indent=1))
print(out, "exit", rc)
sys.exit(rc)
