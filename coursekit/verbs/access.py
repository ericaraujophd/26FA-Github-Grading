"""
access, read access to the student repositories, for a grader.
==============================================================

    cs108 access a04                      # preview: who would get what
    cs108 access a04 --go
    cs108 access --go                     # every assignment that has repositories
    cs108 access a04 --revoke --go        # take it away, end of term
    cs108 access a04 --share ~/for-grader # a folder the grader can work from

THE PROBLEM THIS SOLVES
    A grader needs every student's repository for one assignment. Cloning
    them yourself and sending the folder is the wrong shape: it is half a
    gigabyte, it is stale the moment a student pushes, it carries names and
    email addresses through email, and it has to be done again for every
    assignment.

    Instead the grader gets READ access to the repositories and clones them
    himself, with the same `collect` the instructor uses. Nothing is sent,
    nothing goes stale, and a late push is one `collect` away.

WHO IS A GRADER
    A roster row with `role=grader` and a `github_id`:

        username,first_name,last_name,email,section,github_id,role
        tmiller,Tami,Miller,,,tmiller-gh,grader

    Graders are never distributed to, never graded, and never counted in
    the class size. They are on the roster because the roster is the
    course's list of people.

WHAT IT DOES, PER GRADER
    1. Invites him to the organization if he is not already a member.
       GitHub requires him to accept. This step matters: without
       organization membership, every repository sends its own invitation,
       so a class of forty-two would mean forty-two emails to accept
       instead of one.
    2. Grants `pull` (read) on every EXISTING student repository for the
       assignment, and on the template repository so he can see exactly
       what students were given.

    Read, never write. A grader cannot push to a student's repository, and
    no flag in this toolkit will give him that.

    Idempotent: re-run it when a late student's repository appears, or when
    you add a second grader. Repositories he already has are left alone.

--revoke removes the repository access again. It does not remove him from
the organization; that is a deliberate act you do on GitHub, and it is
printed as a reminder.

--share writes a folder the grader can install the toolkit against:
course.json, the roster (email addresses blanked), each assignment's
assignment.json and starter/, and the solution side (answers/ and the
grading bundle) so they can compare against the reference and run `marks`
on an autograded assignment. --no-solutions leaves that half out, for a
grader who only needs to clone. Nothing about it touches GitHub, so it
needs no --go.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List

from .. import assignment as asg
from .. import config as cfg
from .. import ghcli, out, roster as rostermod

# GitHub's role names for a collaborator, weakest first. Anything in this
# list means the grader can already read the repository, so `access` leaves
# it alone rather than downgrading someone who was given more on purpose.
CAN_READ = ("read", "triage", "write", "maintain", "admin")


def graders_or_explain(course: cfg.Course) -> List[dict]:
    """The roster's grader rows, or an empty list plus an explanation."""
    try:
        rows = rostermod.read_rows(course.roster)
    except rostermod.RosterError as exc:
        out.say(f"error: {exc}")
        return []
    graders = [r for r in rows if r["role"] in rostermod.GRADER_ROLES]
    if not graders:
        out.say(f"No graders on the roster, so there is nobody to give access to.")
        out.say(f"  Add a row to {course.roster} with role=grader and their GitHub login:")
        out.say(f"    username,first_name,last_name,email,section,github_id,role")
        out.say(f"    tmiller,Tami,Miller,,,tmiller-gh,grader")
        out.say(f"  Then:  {course.course} access <assignment> --go")
        return []
    return graders


def assignments_with_repos(course: cfg.Course, wanted: str, have: Dict[str, dict],
                           participants: List[dict]) -> List[str]:
    """Assignment ids that actually have repositories to grant on."""
    ids = [wanted] if wanted else asg.list_ids(course)
    out_ids = []
    for aid in ids:
        if any(course.student_repo(aid, p["username"]) in have for p in participants):
            out_ids.append(aid)
        elif wanted:
            out_ids.append(aid)          # named explicitly: report it, even if empty
    return out_ids


def share(course: cfg.Course, dest: Path, wanted: str, graders: List[dict],
          solutions: bool = True) -> int:
    """Write a folder a grader can run the toolkit against.

    What goes in: course.json, roster/roster.csv with email addresses
    blanked, and for each assignment its assignment.json, starter/, and
    (unless --no-solutions) answers/ and the grading bundle. A grader who
    has the bundle can run `marks` on an autograded assignment, which is
    the difference between a grader who can grade and one who can only
    download. The templates folder stays behind: publishing is the
    instructor's job, not theirs.
    """
    dest = Path(dest).expanduser()
    if dest.exists() and any(dest.iterdir()):
        out.say(f"error: {dest} already exists and is not empty; pick another folder")
        return 1
    ids = [wanted] if wanted else asg.list_ids(course)

    (dest / "roster").mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in course.data.items() if k in cfg.DESCRIPTIONS}
    data["grading"] = f"~/{course.course}-grading"
    (dest / cfg.CONFIG_NAME).write_text(
        __import__("json").dumps(data, indent=2) + "\n", encoding="utf-8")

    rows = rostermod.read_rows(course.roster)
    for r in rows:
        r["email"] = ""              # the grader does not need them to clone
    rostermod.write_rows(dest / "roster" / "roster.csv", rows)

    copied = []
    for aid in ids:
        src = course.assignment_dir(aid)
        if not src.is_dir():
            continue
        (dest / "assignments" / aid).mkdir(parents=True, exist_ok=True)
        for name in (asg.ASSIGNMENT_JSON, "README.md"):
            if (src / name).is_file():
                shutil.copyfile(src / name, dest / "assignments" / aid / name)
        starter = course.starter(aid)
        if starter.is_dir():
            shutil.copytree(starter, dest / "assignments" / aid / "starter",
                            ignore=shutil.ignore_patterns(*asg.SKIP_NAMES),
                            dirs_exist_ok=True)
        if solutions:
            if course.answers(aid).is_dir():
                shutil.copytree(course.answers(aid), dest / "assignments" / aid / "answers",
                                ignore=shutil.ignore_patterns(*asg.SKIP_NAMES),
                                dirs_exist_ok=True)
            if course.bundle(aid).is_dir():
                shutil.copytree(course.bundle(aid), dest / "autograders" / aid,
                                ignore=shutil.ignore_patterns(*asg.SKIP_NAMES),
                                dirs_exist_ok=True)
        copied.append(aid)

    names = ", ".join(rostermod.display_name(g) for g in graders) or "your grader"
    (dest / "README.md").write_text(f"""# {course.title} ({course.course}), for the grader

Everything here is read-only as far as GitHub is concerned: with this folder
and read access to the organization, you can download every student's work
for an assignment. You cannot push to a student repository.

## Once

1. Install the GitHub CLI from https://cli.github.com, then:

       gh auth login
       gh auth setup-git

2. Accept the invitation to the `{course.org}` organization (an email from
   GitHub). Without it the repositories are invisible to you.

3. Install the toolkit (ask {course.title}'s instructor for the repository),
   then from inside this folder:

       ./install --course {course.course} --org {course.org} --folder "$(pwd)"

## Every time you grade

    {course.course} collect {copied[0] if copied else 'a04'}
    {course.course} sheet {copied[0] if copied else 'a04'}

On an autograded assignment, `{course.course} marks <assignment>` runs the
grader instead and writes a gradebook. {"The reference solutions are in each assignment's answers/ folder." if solutions else "The reference solutions are not in this folder; ask the instructor."}

`collect` clones every student's repository into
`~/{course.course}-grading/<assignment>/checkouts/<username>/` and stops.
Re-running it updates the clones rather than starting again, so a late push
costs seconds.

`sheet` writes a CSV with one row per student, sorted by last name, with
empty `mark` and `comment` columns for you to type into. It never overwrites
a sheet that already has marks in it.

To grade exactly what existed at the deadline:

    {course.course} collect {copied[0] if copied else 'a04'} --as-of "2026-10-14T23:59:59-04:00"

## What is not here

The workflow templates, and anything that publishes to GitHub. You have read
access to the repositories and nothing more: you cannot push to a student's
work, and no command here will let you.

Prepared for {names}.
""", encoding="utf-8")

    out.say(f"wrote {dest}")
    out.say(f"  course.json, roster/roster.csv (email addresses blanked),")
    out.say(f"  and {len(copied)} assignment(s): {', '.join(copied) or 'none'}")
    if solutions:
        out.say(f"  including answers/ and the grading bundles, so the grader can run `marks`")
        out.say(f"  (leave them out with --no-solutions)")
    else:
        out.say(f"  starter/ only; answers/ and the grading bundles were left out")
    out.say(f"\n  Send the folder to the grader, then give them access:")
    out.say(f"    {course.course} access {wanted or '<assignment>'} --go")
    return 0


def run(course: cfg.Course, argv) -> int:
    ap = argparse.ArgumentParser(prog=f"{course.course} access",
                                 description="Give a grader read access to the student repositories.")
    ap.add_argument("assignment", nargs="?", help="default: every assignment that has repositories")
    ap.add_argument("--go", action="store_true", help="perform it (default is a preview)")
    ap.add_argument("--revoke", action="store_true", help="remove access instead of granting it")
    ap.add_argument("--share", metavar="DIR",
                    help="write a folder the grader can run the toolkit from (touches no GitHub)")
    ap.add_argument("--no-solutions", dest="solutions", action="store_false",
                    help="with --share: leave answers/ and the grading bundles out")
    args = ap.parse_args(argv)

    graders = graders_or_explain(course)
    if args.share:
        return share(course, Path(args.share), args.assignment, graders, args.solutions)
    if not graders:
        return 1

    no_id = [g["username"] for g in graders if not g["github_id"]]
    graders = [g for g in graders if g["github_id"]]
    for username in no_id:
        out.bad_line(username, "no github_id in the roster, so nothing can be granted")
    if not graders:
        return 1

    try:
        ghcli.require_auth()
        participants = rostermod.participants(course.roster)
        gh = ghcli.Gh(course.org)
        have = gh.repos()
    except (ghcli.GhUnavailable, rostermod.RosterError) as exc:
        out.say(f"error: {exc}")
        return 1

    ids = assignments_with_repos(course, args.assignment, have, participants)
    if not ids:
        out.say("No assignment has any student repositories yet, so there is nothing to grant.")
        out.say(f"  Hand one out first:  {course.course} assign <assignment> --go")
        return 1

    verb = "Revoking" if args.revoke else "Granting"
    out.say(f"{'PREVIEW: ' if not args.go else ''}{verb} read access for "
            f"{len(graders)} grader{'' if len(graders) == 1 else 's'} on "
            f"{len(ids)} assignment{'' if len(ids) == 1 else 's'}")
    for g in graders:
        out.say(f"  grader   : {g['github_id']:<20} {rostermod.display_name(g)}")
    out.say(f"  org      : {course.org}")
    out.say()

    # ── organization membership ────────────────────────────────────────
    # One invitation, accepted once, instead of one invitation per
    # repository. Skipped entirely when revoking: membership is not ours to
    # take away here.
    pending = []
    if not args.revoke:
        for g in graders:
            login = g["github_id"]
            state = ghcli.membership_state(course.org, login)
            if state == "active":
                out.skip_line(login, "already a member of the organization")
                continue
            if state == "pending":
                pending.append(login)
                out.skip_line(login, "invited, has not accepted yet")
                continue
            if not args.go:
                pending.append(login)
                out.ok_line(login, "would be invited to the organization")
                continue
            state, err = ghcli.invite(course.org, login)
            if err:
                out.bad_line(login, err)
                return 1
            pending.append(login)
            out.ok_line(login, "invited to the organization")
        out.say()

    # ── per repository ─────────────────────────────────────────────────
    granted = removed = already = failed = 0
    for aid in ids:
        targets = [course.full(course.template_repo(aid))] if course.template_repo(aid) in have else []
        for p in participants:
            name = course.student_repo(aid, p["username"])
            if name in have:
                targets.append(course.full(name))
        if not targets:
            out.say(f"  {aid}: no repositories yet")
            continue

        changed_here = []
        for full in targets:
            current = ghcli.collaborators(full)
            for g in graders:
                login = g["github_id"]
                has = current.get(login.lower(), "") in CAN_READ
                if args.revoke:
                    if not has:
                        already += 1
                        continue
                    if not args.go:
                        removed += 1
                        changed_here.append(f"{full.split('/')[-1]} ({login})")
                        continue
                    err = ghcli.revoke_access(full, login)
                    if err:
                        failed += 1
                        out.bad_line(full.split("/")[-1], err)
                    else:
                        removed += 1
                else:
                    if has:
                        already += 1
                        continue
                    if not args.go:
                        granted += 1
                        changed_here.append(f"{full.split('/')[-1]} ({login})")
                        continue
                    err = ghcli.grant_access(full, login, "pull")
                    if err:
                        failed += 1
                        out.bad_line(full.split("/")[-1], err)
                    else:
                        granted += 1
        word = "would change" if not args.go else ("revoked" if args.revoke else "granted")
        out.ok_line(aid, f"{len(targets)} repositor{'y' if len(targets) == 1 else 'ies'}; "
                         f"{len(changed_here) if not args.go else (removed if args.revoke else granted)} {word}")

    out.say()
    did = "would be" if not args.go else ""
    if args.revoke:
        out.say(f"{removed} access(es) {did + ' removed' if did else 'removed'}, "
                f"{already} already absent, {failed} failure(s)")
        if args.go:
            out.say(f"  They are still members of {course.org}. Remove them by hand at")
            out.say(f"  https://github.com/orgs/{course.org}/people when the term is over.")
    else:
        out.say(f"{granted} access(es) {did + ' granted' if did else 'granted'}, "
                f"{already} already had read, {failed} failure(s)")
        out.say(out.green(f"0 write accesses {did + ' granted' if did else 'granted'} "
                          f"(a grader gets read, and only read)"))
        if pending and args.go:
            out.say(f"\nWaiting on {', '.join(pending)} to accept the organization invitation.")
            out.say("  Until then the repositories are invisible to them. Re-run this after they accept.")
        if args.go:
            out.say(f"\nThe grader now runs, on their own machine:")
            out.say(f"  {course.course} collect {ids[0]}     (clones every repository, nothing else)")
            out.say(f"  {course.course} sheet {ids[0]}       (a CSV to type marks into)")
            out.say(f"They need a course folder to do that: {course.course} access {ids[0]} --share ~/for-grader")

    if not args.go:
        out.preview_footer(f"{course.course} access {args.assignment or ''}".rstrip()
                           + (" --revoke" if args.revoke else ""))
    else:
        cfg.append_history(course.root, f"access {'revoked' if args.revoke else 'granted'} for "
                           f"{', '.join(g['github_id'] for g in graders)} on {', '.join(ids)}")
    return 1 if failed else 0
