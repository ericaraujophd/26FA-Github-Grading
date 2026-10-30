"""
fetch, pull an assignment's setup out of GitHub into this course folder.
========================================================================

    cs108 fetch               # what is published that this folder does not have
    cs108 fetch a05           # get a05's setup
    cs108 fetch a05 --force   # overwrite what is already here

WHO THIS IS FOR
    A grader. The folder `access --share` wrote holds the assignments that
    existed the day it was written. When the instructor publishes a05 three
    weeks later, the grader's folder knows nothing about it and `collect a05`
    has no starter to compare against. Asking the instructor to re-send the
    folder for every assignment is the friction this removes.

WHERE IT GETS THE FILES
    From the assignment's TEMPLATE REPOSITORY, which is on GitHub and which
    a grader already has read access to:

        <org>/<course>-a05-starter   ->   assignments/a05/starter/

    That repository is, by construction, exactly what every student
    received, so it is the right thing to measure `complete` against. It is
    also the only part of an assignment that is on GitHub at all.

WHAT IT CANNOT GET, AND WHY
    answers/ and the grading bundle never leave the instructor's machine.
    So after fetching an AUTOGRADED assignment a grader can `collect` and
    `sheet` but not `marks`; the bundle has to come from the instructor,
    through `access --share`. This prints that in as many words rather than
    letting `marks` fail later with a missing-bundle error.

    `kind` is inferred from the workflow the template carries: autograde.yml
    means autograded, anything else means hand-graded. The restore list is
    not published either, and a grader never patches, so it is written
    empty.

SAFETY
    It refuses to touch an assignment that has an answers/ folder here,
    because that is the instructor's own course folder and the files on
    GitHub are a copy of it, not the source. --force overrides, and should
    almost never be needed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out

WORKFLOW_DIR = ".github"


def _clone(url: str, dest: Path) -> str:
    """Shallow clone; only the current files matter. Returns '' or an error."""
    proc = subprocess.run(["git", "clone", "--quiet", "--depth", "1", url, str(dest)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return proc.stderr.strip()[:300]
    return ""


def published(course: cfg.Course) -> List[str]:
    """Assignment ids that have a template repository in the organization.

    The repository name is the only evidence, so this reads the configured
    pattern backwards: cs108-{a}-starter means anything between the course
    code and the suffix is an assignment id.
    """
    try:
        repos = ghcli.Gh(course.org).repos()
    except ghcli.GhUnavailable as exc:
        out.say(f"error: {exc}")
        return []
    pattern = course.data["template"]
    prefix = pattern.split("{assignment}")[0].format(course=course.course).lower()
    suffix = pattern.split("{assignment}")[-1].format(course=course.course).lower()
    found = []
    for name in repos:
        if name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix) + len(suffix):
            aid = name[len(prefix):len(name) - len(suffix)] if suffix else name[len(prefix):]
            if asg.ASSIGNMENT_ID_RE.match(aid):
                found.append(aid)
    return sorted(found)


def listing(course: cfg.Course) -> int:
    """`fetch` with no argument: what is published, and what is missing here."""
    live = published(course)
    if not live:
        out.say(f"No template repositories found in {course.org}.")
        return 1
    here = set(asg.list_ids(course))
    out.say(f"Published in {course.org}:")
    for aid in live:
        state = "already here" if aid in here else out.yellow("not in this folder")
        out.say(f"  {aid:<10} {state}")
    missing = [a for a in live if a not in here]
    if missing:
        out.say(f"\nGet one with:  {course.course} fetch {missing[0]}")
    else:
        out.say(f"\n{out.green('Nothing missing.')}")
    return 0


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} fetch",
                                 description="Pull an assignment's setup out of GitHub.")
    ap.add_argument("assignment", nargs="?",
                    help="default: list what is published and what is missing here")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an assignment folder that is already here")
    args = ap.parse_args(argv)

    if not args.assignment:
        return listing(course)

    aid = args.assignment
    if not asg.ASSIGNMENT_ID_RE.match(aid):
        out.say(f"error: {aid!r} is not an assignment id (lowercase letters, digits, dashes)")
        return 1

    folder = course.assignment_dir(aid)
    starter = course.starter(aid)
    if course.answers(aid).is_dir() and not args.force:
        out.say(f"error: {course.answers(aid)} exists, so this is the instructor's own copy of")
        out.say(f"  {aid}, and GitHub holds a copy of THIS folder rather than the other way round.")
        out.say(f"  Refusing to overwrite it. Pass --force if you are certain.")
        return 1
    if starter.is_dir() and asg.collect(starter) and not args.force:
        out.say(f"error: {starter} already has files in it. Pass --force to replace them.")
        return 1

    try:
        ghcli.require_auth()
    except ghcli.GhUnavailable as exc:
        out.say(f"error: {exc}")
        return 1

    full = course.full(course.template_repo(aid))
    if not ghcli.repo_exists(full):
        out.say(f"error: no template repository at {full}")
        out.say(f"  Either {aid} has not been published yet, or you do not have read access.")
        out.say(f"  Ask the instructor to run:  {course.course} template {aid} --go")
        out.say(f"                              {course.course} access {aid} --go")
        out.say(f"  See what is published:      {course.course} fetch")
        return 1

    out.say(f"Fetching {aid} from {full}")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "template"
        err = _clone(f"https://github.com/{full}.git", work)
        if err:
            out.say(f"error: could not clone {full}: {err}")
            out.say(f"  If it asks for a password, run:  gh auth setup-git")
            return 1

        # The workflow is GitHub's business, not the starter's: students
        # receive it but it is not part of the work, and `template`
        # regenerates it on every publish.
        has_autograde = (work / WORKFLOW_DIR / "workflows" / "autograde.yml").is_file()
        kind = "auto" if has_autograde else "manual"

        if starter.is_dir() and args.force:
            shutil.rmtree(starter)
        starter.mkdir(parents=True, exist_ok=True)
        copied = 0
        for rel in asg.collect(work):
            if rel.parts[0] in (WORKFLOW_DIR, ".git"):
                continue
            dest = starter / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / rel, dest)
            copied += 1

    path = folder / asg.ASSIGNMENT_JSON
    if path.is_file() and not args.force:
        out.say(f"  kept {path.name} (already here)")
    else:
        asg.write_json(path, {
            "title": aid,
            "kind": kind,
            "restore": [],
            "fetched": f"from {full} on {dt.date.today().isoformat()}; "
                       f"starter only, no answers and no grading bundle",
        })
        out.say(f"  wrote {path.relative_to(course.root)}  (kind {kind}, inferred from the workflow)")

    out.say(f"  wrote {copied} file(s) into {starter.relative_to(course.root)}")
    out.say()
    out.say(f"Now:  {course.course} collect {aid}")
    out.say(f"      {course.course} sheet {aid}")
    if kind == "auto" and not (course.bundle(aid) / "").is_dir():
        out.say()
        out.say(out.yellow(f"{aid} is autograded, and the grading bundle is not on GitHub."))
        out.say(f"  collect and sheet work. `marks` needs autograders/{aid}/, which only the")
        out.say(f"  instructor has: ask them for  {course.course} access {aid} --share")
    return 0
