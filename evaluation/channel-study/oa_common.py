# SPDX-License-Identifier: MIT
"""OpenAlex access. Key from ~/.config/openalex/api_key (never printed or stored); anonymous if missing or rejected."""
import json, os, time, urllib.request, urllib.parse, urllib.error
KEY_PATH = os.path.expanduser("~/.config/openalex/api_key")
_KEY = open(KEY_PATH).read().strip() if os.path.exists(KEY_PATH) else ""
STATE = {"keyed": bool(_KEY), "remaining": None}
def get(path, params):
    for a in range(8):
        hdr = {"User-Agent": "conf-tracker-evaluation/1.0"}
        if STATE["keyed"]: hdr["Authorization"] = "Bearer " + _KEY
        url = "https://api.openalex.org/" + path + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=90) as r:
                STATE["remaining"] = r.headers.get("X-RateLimit-Remaining")
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and STATE["keyed"]:
                STATE["keyed"] = False; print("OpenAlex rejected the key (401); continuing anonymously", flush=True); continue
            if e.code in (400, 404): return None
            if e.code == 429: STATE["remaining"] = "0"; return None
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    return None
def text(inv):
    pos = [(i, w) for w, ii in (inv or {}).items() for i in ii]
    return " ".join(w for _, w in sorted(pos))
