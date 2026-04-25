#!/usr/bin/env python3
"""
Blotto Research PWA Deployer
Fetches current live data, archives it, embeds new research, redeploys to Vercel.

Usage: python3 deploy.py '<json_data>'
Config: expects deploy_config.py in same directory with VERCEL_TOKEN and TEAM_ID
"""

import json, hashlib, os, sys, re
import urllib.request, urllib.error

# Load credentials from config file (gitignored)
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
try:
    from deploy_config import VERCEL_TOKEN, TEAM_ID
except ImportError:
    print("ERROR: deploy_config.py not found. Create it with VERCEL_TOKEN and TEAM_ID.")
    sys.exit(1)

LIVE_URL = "https://blotto-research.vercel.app"


def vercel_api(method, path, body=None):
    url = f"https://api.vercel.com{path}?teamId={TEAM_ID}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {VERCEL_TOKEN}", "Content-Type": "application/json"},
        method=method
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Vercel {method} {path} -> {e.code}: {e.read().decode()}")


def upload_file(content_bytes):
    sha = hashlib.sha1(content_bytes).hexdigest()
    req = urllib.request.Request(
        f"https://api.vercel.com/v2/files?teamId={TEAM_ID}",
        data=content_bytes,
        headers={
            "Authorization": f"Bearer {VERCEL_TOKEN}",
            "Content-Type": "application/octet-stream",
            "x-vercel-digest": sha
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()
    return sha, len(content_bytes)


def fetch_live_data():
    try:
        req = urllib.request.Request(LIVE_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8")
        m = re.search(r'const RESEARCH_DATA = (.+?); /\* __RESEARCH_DATA__ \*/', html)
        current = json.loads(m.group(1)) if m and m.group(1) != 'null' else None
        m2 = re.search(r'const HISTORY_DATA = (\[.*?\]); /\* __HISTORY_DATA__ \*/', html, re.DOTALL)
        history = json.loads(m2.group(1)) if m2 else []
        return current, history
    except Exception as e:
        print(f"  (could not fetch live data: {e})")
        return None, []


def deploy(new_data: dict):
    print("Fetching current live data...")
    current, history = fetch_live_data()

    if current and current.get("date"):
        already_archived = any(h.get("date") == current["date"] for h in history)
        if not already_archived:
            history.insert(0, current)
            print(f"  archived week of {current['date']}")

    history = history[:12]

    with open(os.path.join(_dir, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace(
        'const RESEARCH_DATA = null; /* __RESEARCH_DATA__ */',
        f'const RESEARCH_DATA = {json.dumps(new_data, ensure_ascii=True)}; /* __RESEARCH_DATA__ */'
    )
    html = html.replace(
        'const HISTORY_DATA = []; /* __HISTORY_DATA__ */',
        f'const HISTORY_DATA = {json.dumps(history, ensure_ascii=True)}; /* __HISTORY_DATA__ */'
    )

    files = {
        "index.html":    html.encode("utf-8"),
        "manifest.json": open(os.path.join(_dir, "manifest.json"), "rb").read(),
        "vercel.json":   open(os.path.join(_dir, "vercel.json"),   "rb").read(),
        "icon-192.png":  open(os.path.join(_dir, "icon-192.png"),  "rb").read(),
        "icon-512.png":  open(os.path.join(_dir, "icon-512.png"),  "rb").read(),
    }

    file_specs = []
    for fname, content in files.items():
        sha, size = upload_file(content)
        file_specs.append({"file": fname, "sha": sha, "size": size})
        print(f"  uploaded {fname}")

    result = vercel_api("POST", "/v13/deployments", {
        "name": "blotto-research",
        "files": file_specs,
        "projectSettings": {"framework": None},
        "target": "production"
    })

    url = result.get("alias", [result.get("url")])[0]
    print(f"  deployed -> https://{url}")
    print(f"  history: {len(history)} previous week(s) stored")
    return f"https://{url}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 deploy.py '<json_data>'")
        sys.exit(1)
    data = json.loads(sys.argv[1])
    deploy(data)
