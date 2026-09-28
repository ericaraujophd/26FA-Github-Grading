# Giving a grader the student repositories

A teaching assistant needs every student's work for one assignment. The
obvious move, cloning it all and sending the folder, is the wrong shape:
it is hundreds of megabytes, it is stale the moment a student pushes, it
carries names and email addresses through email, and it has to be done
again for every assignment.

Give them read access instead. They clone the repositories themselves,
with the same `collect` you use, and a late push costs them seconds.

## Once per grader

Add a row to `roster/roster.csv` with `role=grader` and their GitHub login:

```csv
username,first_name,last_name,email,section,github_id,role
tmiller,Tami,Miller,,,tmiller-gh,grader
```

A grader is never distributed to, never graded, and never counted in the
class size. They are on the roster because the roster is the course's list
of people.

## Handing out

`assign --go` grants it for you. Every repository it creates or finds is
granted read for every grader on the roster, so a repository handed out
today is visible to the grader today.

For everything already handed out, or after adding a grader mid-term:

```bash
cs108 access a04          # preview: who gets what
cs108 access a04 --go
cs108 access --go         # every assignment that has repositories
```

Both invite them to the organization (one invitation, accepted once) and
grant `pull`, read, on every existing student repository plus the
template, so they can see what students were given.

Read, never write. A grader cannot push to a student's repository and no
flag here will give them that. The run prints `0 write accesses granted`
every time, for the same reason `patch` prints `0 deliverables changed`.

Re-run it when you add a second grader. Repositories they already have are
left alone.

## What you send the grader

```bash
cs108 access a04 --share ~/Desktop/cs108-grader
```

`course.json`, the roster with email addresses blanked, each assignment's
`assignment.json` and `starter/`, and the solution side: `answers/` and
the grading bundles. With the bundle they can run `marks` on an autograded
assignment, which is the difference between a grader who can grade and one
who can only download. `--no-solutions` leaves that half out. It touches
nothing on GitHub, so it needs no `--go`.

Send them that folder and the toolkit, and they run, on their own machine:

```bash
gh auth login
gh auth setup-git
./install --course cs108 --org 26fa-cs108 --folder ~/Desktop/cs108-grader

cs108 collect a04     # clones every repository into ~/cs108-grading/a04/checkouts/
cs108 sheet a04       # a CSV to type marks into, sorted by last name
cs108 marks a04       # autograded assignments: runs the grader, writes a gradebook
```

`collect` updates existing clones rather than starting over, and takes
`--as-of "2026-10-14T23:59:59-04:00"` so they grade what existed at the
deadline. The generated folder carries a README saying all of this.

## Without installing anything

A grader who only wants the code, once, needs nothing but `gh`:

```bash
gh repo list 26fa-cs108 --limit 1000 --json name -q '.[].name' \
  | grep '^cs108-a04-' \
  | xargs -I{} gh repo clone 26fa-cs108/{} a04/{}
```

That gives them the repositories and nothing else: no `complete` column,
no deadline handling, no marks sheet.

## At the end of the term

```bash
cs108 access a04 --revoke --go
```

Removes the repository access. It does not remove them from the
organization: that is a deliberate act, and the command says so and gives
you the page to do it on.

## Where this stops

The toolkit never writes a grader's marks anywhere. They fill in the CSV
`sheet` produced and send it to you, and you take it wherever you keep
grades. `sheet` exports; nothing imports. Two files that both look
authoritative is how grades get lost.
