#!/usr/bin/env python3
"""Match public cross-platform CI evidence to the exact component package."""
import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from check_component_package import package_fingerprint, validate_archive


def api(repository, path, payload=None):
    headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json",
               "User-Agent": "esp-iris-release-check",
               "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request("https://api.github.com/repos/" + repository + path,
                                     headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def successful_status(statuses, fingerprint):
    context = "esp-iris/package/" + fingerprint
    for status in statuses:
        if status.get("context") == context:
            return (status.get("state") == "success" and
                    status.get("creator", {}).get("login") == "github-actions[bot]")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--repository", default="esp-mosaico/esp-mosaico-utils")
    parser.add_argument("--record", action="store_true", help="Record a successful GitHub package matrix")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
        parser.error("Invalid GitHub repository")
    files, version = validate_archive(args.archive)
    fingerprint = package_fingerprint(files)
    evidence = {"version": version, "package_fingerprint": fingerprint, "repository": args.repository}
    if args.record:
        commit = os.environ["GITHUB_SHA"]
        url = "https://github.com/" + args.repository + "/actions/runs/" + os.environ["GITHUB_RUN_ID"]
        api(args.repository, "/statuses/" + commit, {
            "state": "success", "context": "esp-iris/package/" + fingerprint,
            "description": "Package passed Linux/macOS/Windows, Python 3.8/3.12 and browser checks",
            "target_url": url,
        })
        evidence.update(public_commit=commit, workflow_url=url, result="passed")
    else:
        runs = api(args.repository, "/actions/workflows/iris-package.yml/runs?status=success&branch=main&per_page=20")
        for run in runs.get("workflow_runs", []):
            if run.get("event") not in ("push", "workflow_dispatch"):
                continue
            statuses = api(args.repository, "/commits/" + run["head_sha"] + "/statuses?per_page=100")
            if successful_status(statuses, fingerprint):
                evidence.update(public_commit=run["head_sha"], workflow_url=run["html_url"], result="passed")
                break
        else:
            raise SystemExit("No successful public package matrix matches this archive. "
                             "Synchronize the release sources to public main and run Iris package CI.")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
