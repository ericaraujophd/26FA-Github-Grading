"""
marks, the mark of record. collect, the same without grading.
=============================================================

    cs108 marks a04
    cs108 marks a04 --as-of "2026-10-14T23:59:59-04:00"
    cs108 marks a04 --students jsmith,test-account
    cs108 marks a04 --verify-reproducible
    cs108 collect a04                     # clone everything and stop

For each participant: clone or update the repository, park it on the commit
being graded, compute `complete` against the untouched starter, then (marks
only, autograded only) run the bundle against the checkout and read back
result.json. On a hand-graded assignment `marks` refuses and names `collect`
and `sheet` instead; `collect` works for both kinds.

`collect` IS `marks` with the grading step skipped. It is implemented as the
same function with one flag, so the two can never clone differently.

--as-of grades the last commit at or before that instant. This is how a late
policy stays consistent: grade what existed when it was due, no matter when
you get round to running it.

OUTPUT, under <grading>/a04/
    gradebook.csv          one row per participant, the file actually used
    gradebook.previous.csv the previous run, kept so `complete` can be diffed
    run.json               when this ran, with what --as-of
    results/<user>.json    the full result.json
    feedback/<user>.md     student-facing feedback, when the grader wrote it
    logs/<user>.log        grader output, for when something looks wrong
    checkouts/<user>/      the graded working copy, kept for inspection

WHAT CHANGED SINCE LAST TIME
    Both verbs record the commit they pulled for each student in
    collect.csv, and compare against the one recorded by the previous run.
    Every run ends by naming the students whose work MOVED since you last
    looked, which is the question a grader has in front of a pile of
    resubmissions. `sheet --updated` turns that list into a marking sheet
    of only those students.

THE TWO KINDS OF COLUMN (settled 2026-09-15; see docs/score-vs-complete.md)
    score / max_score / percent   diagnostic. How close the student got.
    complete                      the column the grade table consumes: yes
                                  when the student pushed ANYTHING beyond the
                                  untouched starter, no when the repository
                                  is still the starter byte for byte.
    changed                       the file that produced the yes, so a
                                  disputed cell can be checked without
                                  re-running anything.

THREE SCARS
    complete is computed BEFORE the grader runs, on a checkout that has just
    been cleaned, because restore overwrites the provided files and a build
    leaves artifacts, and either would muddy the comparison.

    The set of starter files is `Assignment.starter_files()`, the SAME
    function `template` uses to publish. Written twice they drift, and the
    symptom is a student marked incomplete over a file that was never
    published.

    If EVERY submission fails to load at the same point, that is a fact
    about this machine, not about the class, and the gradebook is NOT
    written (--write-anyway overrides).

THE MEASURES
    Printed on every run, not hidden behind a flag:
      complete never regresses    any yes -> no for the same commit, against
                                  the previous gradebook, is a bug in the
                                  comparison and is printed loudly.
      grading is reproducible     --verify-reproducible grades twice and
                                  compares the two gradebooks byte for byte.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from .. import assignment as asg
from .. import config as cfg
from .. import grading, out, roster as rostermod

FIELDS = ["username", "name", "section", "score", "max_score", "percent",
          "complete", "changed", "status", "commit", "repo"]


def _git(argv, timeout=300):
    try:
        return subprocess.run(["git", *argv], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not on PATH")


def sync_checkout(url: str, dest: Path, as_of: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Clone or update dest, then park it on the commit to grade.
    Returns (sha, error). A missing repository is a normal outcome."""
    if dest.exists():
        proc = _git(["-C", str(dest), "fetch", "--quiet", "--all", "--tags", "--prune"])
        if proc.returncode != 0:
            return None, f"fetch failed: {proc.stderr.strip()[:200]}"
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = _git(["clone", "--quiet", url, str(dest)])
        if proc.returncode != 0:
            err = proc.stderr.strip()
            if "not found" in err.lower() or "does not exist" in err.lower() \
                    or "could not read" in err.lower():
                return None, "no repository"
            return None, f"clone failed: {err[:200]}"

    head = _git(["-C", str(dest), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    branch = head.stdout.strip() if head.returncode == 0 else "origin/main"
    if as_of:
        rev = _git(["-C", str(dest), "rev-list", "-1", f"--before={as_of}", branch])
        sha = rev.stdout.strip()
        if not sha:
            return None, f"no commits at or before {as_of}"
    else:
        rev = _git(["-C", str(dest), "rev-parse", branch])
        if rev.returncode != 0:
            return None, "no commits on the default branch"
        sha = rev.stdout.strip()

    for argv in (["-C", str(dest), "checkout", "--quiet", "--force", sha],
                 ["-C", str(dest), "clean", "-qfdx"]):
        proc = _git(argv)
        if proc.returncode != 0:
            return None, f"checkout failed: {proc.stderr.strip()[:200]}"
    return sha, None


def submission_state(checkout: Path, a: asg.Assignment) -> Tuple[str, str]:
    """Compare a freshly cleaned checkout against the untouched starter.
    Returns (complete, changed): ("yes"|"no"|"", reason)."""
    if not a.starter.is_dir():
        return "", f"no starter folder at {a.starter}"
    baseline = a.starter_files()
    reasons: List[str] = []
    for rel in baseline:
        theirs = checkout / rel
        if not theirs.is_file():
            reasons.append(f"deleted {rel}")
        elif theirs.read_bytes() != (a.starter / rel).read_bytes():
            reasons.append(f"edited {rel}")
    baseline_set = set(baseline)
    for path in sorted(checkout.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(checkout)
        if rel.parts[0] in (".git", ".github"):
            continue
        if not asg.keep(rel):
            continue
        if rel.as_posix() not in baseline_set:
            reasons.append(f"added {rel.as_posix()}")
    if not reasons:
        return "no", "untouched starter"

    # Lead with the most informative change: the deliverable, not README.md.
    def interest(reason: str):
        name = reason.split(" ", 1)[1]
        dull = Path(name).name in asg.INFORMATIONAL or name.endswith(".md")
        return (1 if dull else 0, reason)
    reasons.sort(key=interest)
    head = reasons[0]
    if len(reasons) > 1:
        head += f" (+{len(reasons) - 1} more)"
    return "yes", head


def grade_one(course, a, student, outdir: Path, as_of, grade: bool) -> dict:
    username = student["username"]
    repo = course.student_repo(a.id, username)
    url = f"https://github.com/{course.org}/{repo}.git"
    checkout = outdir / "checkouts" / username
    row = {k: "" for k in FIELDS}
    row.update(username=username, name=rostermod.display_name(student),
               section=student.get("section", ""), repo=course.full(repo))
    row["_build_failed"] = None
    row["_first_error"] = ""

    sha, err = sync_checkout(url, checkout, as_of)
    if err:
        row["status"] = err
        return row
    row["commit"] = sha[:7]
    row["complete"], row["changed"] = submission_state(checkout, a)
    if not grade:
        row["status"] = "collected"
        return row

    commit_url = f"https://github.com/{course.org}/{repo}/commit/{sha}"
    run = grading.run_grader(course, a, checkout, username=username, sha=sha,
                             commit_url=commit_url)
    (outdir / "logs" / f"{username}.log").write_text(run["log"], encoding="utf-8")
    if run["error"]:
        row["status"] = f"{run['error']}; see logs/{username}.log"
        return row
    result = run["result"]
    row["_build_failed"] = grading.build_failed(result)
    row["_first_error"] = grading.first_error_line(run["log"])
    score, max_score = result.get("score", 0), result.get("max-score", 0)
    row["score"], row["max_score"] = score, max_score
    row["percent"] = round(100 * score / max_score, 1) if max_score else ""
    row["status"] = "did not load" if row["_build_failed"] else "graded"
    (outdir / "results" / f"{username}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    feedback = checkout / "feedback.md"
    if feedback.is_file():
        shutil.copyfile(feedback, outdir / "feedback" / f"{username}.md")
    usernames = result.get("usernames") or []
    if usernames and usernames != [username]:
        row["status"] += f" (result.json names {usernames}, expected [{username}])"
    return row


def read_gradebook(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["username"]: r for r in csv.DictReader(fh)}


def write_gradebook(path: Path, rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)


def grade_all(course, a, roster, outdir: Path, as_of, grade: bool, jobs: int,
              quiet: bool = False) -> List[dict]:
    for sub in ("results", "feedback", "logs", "checkouts"):
        (outdir / sub).mkdir(parents=True, exist_ok=True)
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(grade_one, course, a, s, outdir, as_of, grade): s for s in roster}
        for fut in concurrent.futures.as_completed(futures):
            student = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:          # never let one student stop the batch
                row = {k: "" for k in FIELDS}
                row.update(username=student["username"], status=f"grader crashed: {exc}")
                row["_build_failed"], row["_first_error"] = None, ""
            rows.append(row)
            if not quiet:
                mark = "ok " if row["status"] in ("graded", "collected") else "!! "
                detail = (f"{row['score']}/{row['max_score']}" if row["status"] == "graded"
                          else row["status"])
                comp = f"complete={row['complete'] or '?'}"
                out.say(f"  {mark}{row['username']:<24} {comp:<13} {detail}")
    rows.sort(key=lambda r: (r["section"], r["username"].lower()))
    return rows


def run(course: cfg.Course, argv, collect_only: bool = False) -> int:
    verb = "collect" if collect_only else "marks"
    ap = argparse.ArgumentParser(prog=f"{course.course} {verb}",
                                 description=("Clone every repository and stop." if collect_only
                                              else "Clone, grade, and write the gradebook."))
    ap.add_argument("assignment")
    ap.add_argument("--as-of", metavar="TIMESTAMP",
                    help="grade the last commit at or before this instant, e.g. 2026-10-14T23:59:59-04:00")
    ap.add_argument("--students", help="comma-separated usernames; default all")
    ap.add_argument("--jobs", type=int, default=4, help="repositories processed in parallel")
    if not collect_only:
        ap.add_argument("--write-anyway", action="store_true",
                        help="write the gradebook even if nothing loaded for anybody")
        ap.add_argument("--verify-reproducible", action="store_true",
                        help="grade twice and confirm the gradebooks are byte-identical")
    args = ap.parse_args(argv)

    try:
        a = asg.load(course, args.assignment)
        roster = rostermod.select(rostermod.participants(course.roster), args.students)
    except asg.AssignmentError as exc:
        out.say(f"error: {exc}")
        out.say(f"  Grading someone else's course? Pull the setup from GitHub with:")
        out.say(f"    {course.course} fetch {args.assignment}")
        return 1
    except rostermod.RosterError as exc:
        out.say(f"error: {exc}")
        return 1

    if not collect_only and not a.is_auto:
        out.say(f"{a.id} is graded by hand, so there is no autograder to run.")
        out.say(f"  Download everyone's work:      {course.course} collect {a.id}")
        out.say(f"  Get a CSV to type marks into:  {course.course} sheet {a.id}")
        return 1
    if not collect_only:
        for p in a.problems():
            out.problem(p)
        if a.problems():
            if a.is_auto and not a.bundle.is_dir():
                # The usual reason a grader lands here: the bundle is the one
                # part of an assignment that is never on GitHub.
                out.say(f"  The grading bundle is not on GitHub and `fetch` cannot get it.")
                out.say(f"  Ask the instructor for:  {course.course} access {a.id} --share")
                out.say(f"  Meanwhile `{course.course} collect {a.id}` and "
                        f"`{course.course} sheet {a.id}` both work.")
            else:
                out.say(f"  Fix these first, then:  {course.course} verify {a.id}")
            return 1

    outdir = course.grading_dir(a.id)
    outdir.mkdir(parents=True, exist_ok=True)
    grade = not collect_only

    out.say(f"{'Collecting' if collect_only else 'Grading'} {a.id} for {len(roster)} participant(s)")
    if grade:
        out.say(f"  bundle : {a.bundle}")
        out.say(f"  {grading.runtime_report(a)}")
    out.say(f"  output : {outdir}")
    if args.as_of:
        out.say(f"  as of  : {args.as_of}")
    out.say()

    rows = grade_all(course, a, roster, outdir, args.as_of, grade, args.jobs)

    if collect_only:
        untouched = sum(1 for r in rows if r["complete"] == "no")
        missing = sum(1 for r in rows if not r["commit"])
        previous = read_pull_state(outdir)
        updated, fresh = mark_since_last(rows, previous)
        out.say()
        out.say(f"{len(rows) - missing} repositor{'y' if len(rows) - missing == 1 else 'ies'} collected, "
                f"{untouched} untouched starter(s), {missing} missing")
        out.say(f"{outdir / 'checkouts'}")
        report_since_last(previous, updated, fresh, rows, "collect")
        if updated or fresh:
            out.say(f"\n  Only those students, as a marking sheet:  "
                    f"{course.course} sheet {a.id} --updated")
        write_pull_state(outdir, rows)
        return 0

    # ── the toolchain guard ─────────────────────────────────────────────
    attempted = [r for r in rows if r.get("_build_failed") is not None]
    broke = [r for r in attempted if r["_build_failed"]]
    fault = len(attempted) >= 2 and len(broke) == len(attempted) and \
        len({r["_first_error"] for r in broke}) == 1
    sample = broke[0] if broke else None
    for r in rows:
        r.pop("_first_error", None)
        r.pop("_build_failed", None)
    if fault and not args.write_anyway:
        out.say()
        out.say(out.red("STOPPED: nothing loaded, for anybody."))
        out.say(f"  All {len(attempted)} submissions failed at the same point. That is the")
        out.say("  signature of a broken runtime on THIS machine, not of a class who all")
        out.say("  made the same mistake.")
        if sample:
            out.say(f"  logs/{sample['username']}.log says: {grading.first_error_line((outdir / 'logs' / (sample['username'] + '.log')).read_text(errors='replace'))}")
        out.say(f"  {grading.runtime_report(a)}")
        out.say(f"  {outdir / 'gradebook.csv'} was NOT touched. If these zeros are real, re-run with --write-anyway.")
        return 2

    gradebook = outdir / "gradebook.csv"
    previous = read_gradebook(gradebook)
    if gradebook.is_file():
        shutil.copyfile(gradebook, outdir / "gradebook.previous.csv")
    write_gradebook(gradebook, rows)
    (outdir / "run.json").write_text(json.dumps({
        "assignment": a.id, "as_of": args.as_of or "",
        "graded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "participants": len(rows)}, indent=2) + "\n", encoding="utf-8")

    graded = [r for r in rows if r["status"] == "graded"]
    perfect = [r for r in graded if r["score"] == r["max_score"]]
    complete = [r for r in rows if r["complete"] == "yes"]
    out.say()
    out.say(f"graded {len(graded)}/{len(rows)}   full marks {len(perfect)}")
    out.say(f"complete {len(complete)}/{len(rows)}   (pushed something beyond the starter)")
    problems = [r for r in rows if r["status"] != "graded"]
    if problems:
        out.say(f"needs attention ({len(problems)}):")
        for r in problems:
            out.say(f"  {r['username']:<24} {r['status']}")

    # ── measure: complete never regresses ──────────────────────────────
    regressions = []
    for r in rows:
        old = previous.get(r["username"])
        if old and old.get("complete") == "yes" and r["complete"] == "no" \
                and old.get("commit") == r["commit"]:
            regressions.append(r["username"])
    if previous:
        if regressions:
            out.say(out.red(f"\nCOMPLETE REGRESSED for {len(regressions)} student(s) on the same commit: "
                            f"{', '.join(regressions)}"))
            out.say(out.red("  A yes that becomes a no for the same commit is a bug in the comparison,"))
            out.say(out.red("  not a student who un-did their work. Do not use this gradebook until"))
            out.say(out.red(f"  it is understood. The previous run is in {outdir / 'gradebook.previous.csv'}."))
        else:
            out.say(out.green("complete never regressed (checked against the previous gradebook)"))

    pull_previous = read_pull_state(outdir)
    pull_updated, pull_fresh = mark_since_last(rows, pull_previous)
    report_since_last(pull_previous, pull_updated, pull_fresh, rows, "run")
    write_pull_state(outdir, rows)

    out.say(f"\ngradebook: {gradebook}")
    cfg.append_history(course.root, f"marks {a.id}: graded {len(graded)}/{len(rows)}, complete {len(complete)}/{len(rows)}"
                       + (f", as of {args.as_of}" if args.as_of else ""))

    # ── measure: grading is reproducible ───────────────────────────────
    if args.verify_reproducible:
        out.say("\nGrading a second time to check reproducibility...")
        second = grade_all(course, a, roster, outdir, args.as_of, True, args.jobs, quiet=True)
        for r in second:
            r.pop("_first_error", None)
            r.pop("_build_failed", None)
        tmp = outdir / "gradebook.second.csv"
        write_gradebook(tmp, second)
        if tmp.read_bytes() == gradebook.read_bytes():
            out.say(out.green("reproducible: the two gradebooks are byte-identical"))
            tmp.unlink()
        else:
            out.say(out.red("NOT REPRODUCIBLE: the two gradebooks differ."))
            out.say(out.red(f"  Something in the grader is non-deterministic (a clock, an unordered"))
            out.say(out.red(f"  iteration, randomness, a network call). Compare:"))
            out.say(f"    {gradebook}\n    {tmp}")
            return 3
    return 0 if not regressions else 4


# collect.csv: the record of what was last pulled off GitHub, written by
# BOTH collect and marks so the two share one notion of "when I last
# looked". It is NOT a gradebook and holds no scores; `sheet` reads it to
# fill complete/changed when no gradebook exists, and both verbs read it to
# work out what moved since last time.
PULL_FIELDS = ["username", "complete", "changed", "commit", "status",
               "since_last", "pulled_at"]


def read_pull_state(outdir: Path) -> dict:
    """{username: row} from the previous collect.csv, or {} the first time."""
    path = outdir / "collect.csv"
    if not path.is_file():
        return {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return {r["username"]: r for r in csv.DictReader(fh) if r.get("username")}
    except (OSError, csv.Error):
        return {}


def mark_since_last(rows: List[dict], previous: dict):
    """Annotate every row with since_last, and return (updated, new).

    The comparison is on the COMMIT, not on a timestamp: a student who
    pushed and then force-pushed back to where they were has not moved, and
    a clock that disagrees between two machines cannot make this wrong.

        new         no row last time, or last time there was no repository
        updated     a different commit than last time: re-read this one
        unchanged   the same commit
        (blank)     no repository to compare

    First run of all: everyone is new, which reads as noise, so the caller
    says "first pull" instead of listing them.
    """
    updated, fresh = [], []
    for r in rows:
        old = previous.get(r["username"])
        if not r.get("commit"):
            r["since_last"] = ""
        elif old is None or not (old.get("commit") or "").strip():
            r["since_last"] = "new"
            fresh.append(r["username"])
        elif old["commit"] != r["commit"]:
            r["since_last"] = "updated"
            updated.append(r["username"])
        else:
            r["since_last"] = "unchanged"
    return updated, fresh


def write_pull_state(outdir: Path, rows: List[dict]) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows:
        r.setdefault("since_last", "")
        r["pulled_at"] = stamp
    path = outdir / "collect.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PULL_FIELDS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)


def report_since_last(previous: dict, updated: List[str], fresh: List[str],
                      rows: List[dict], verb: str) -> None:
    """The block a grader actually reads: who moved since last time."""
    if not previous:
        out.say(f"\nFirst {verb} of this assignment; {len([r for r in rows if r.get('commit')])} "
                f"repositor{'y' if len([r for r in rows if r.get('commit')]) == 1 else 'ies'} recorded. "
                f"Next time this will say what changed.")
        return
    when = ""
    for r in previous.values():
        when = (r.get("pulled_at") or "").replace("T", " ").replace("Z", " UTC")
        if when:
            break
    unchanged = sum(1 for r in rows if r.get("since_last") == "unchanged")
    out.say(f"\nSince your last {verb}" + (f" ({when})" if when else "") + ":")
    if updated:
        out.say(out.yellow(f"  {len(updated)} updated   ") + ", ".join(updated))
    if fresh:
        out.say(f"  {len(fresh)} new       " + ", ".join(fresh))
    if unchanged:
        out.say(out.dim(f"  {unchanged} unchanged"))
    if not updated and not fresh:
        out.say(out.dim("  nothing moved"))
