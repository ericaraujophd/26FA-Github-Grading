#!/usr/bin/env python3
"""
docs/make-grader-setup.py, the source of docs/grader-setup.pdf.

    pip install reportlab && python3 docs/make-grader-setup.py

NOT PART OF THE TOOLKIT. The harness is Python standard library only and
must stay that way; this script builds one printable handout and is the one
place in this repository that needs a third-party package. Nothing imports
it, nothing runs it automatically, and the toolkit works without it.

Build the two-part walkthrough PDF: what Vic does to set his TA up, and what
the TA does to grade. Written with reportlab's Platypus so the text flows and
paginates itself.

Layout decisions worth knowing:
  - Two coloured section bands (instructor, then TA) so a reader can tell at a
    glance which half is theirs, and so Vic can hand the second half to the TA.
  - Commands in a boxed monospace block. Courier, because it is a base-14 font
    and needs no embedding.
  - Calvin maroon (#6E1C2E) for headings, since this goes to a colleague there.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

MAROON = colors.HexColor("#6E1C2E")
GOLD = colors.HexColor("#C49A2C")
INK = colors.HexColor("#1f2328")
DIM = colors.HexColor("#5b6068")
SOFT = colors.HexColor("#f4f5f7")
LINE = colors.HexColor("#d9dce0")

OUT = str(Path(__file__).resolve().parent / "grader-setup.pdf")

# The TA has to clone this to install the toolkit, so it is written into the
# page rather than left as a placeholder. Change it here and re-run if the
# repository ever moves.
TOOLKIT_REPO = "https://github.com/ericaraujophd/26FA-Github-Grading.git"
TITLE = "Giving a TA access to the student repositories"
SUB = "CS 262 course tooling  ·  coursekit  ·  September 2026"

styles = getSampleStyleSheet()
S = {}
S["title"] = ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold",
                            fontSize=17, leading=21, textColor=MAROON, alignment=TA_LEFT,
                            spaceAfter=2)
S["sub"] = ParagraphStyle("sub", fontName="Helvetica", fontSize=9, leading=12,
                          textColor=DIM, spaceAfter=14)
S["band"] = ParagraphStyle("band", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                           textColor=colors.white, spaceBefore=0, spaceAfter=0)
S["h2"] = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14,
                         textColor=MAROON, spaceBefore=12, spaceAfter=5)
S["body"] = ParagraphStyle("body", fontName="Helvetica", fontSize=9.6, leading=13.4,
                           textColor=INK, spaceAfter=6)
S["step"] = ParagraphStyle("step", parent=S["body"], leftIndent=16, firstLineIndent=-16,
                           spaceAfter=4)
S["note"] = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=9, leading=12.5,
                           textColor=DIM, leftIndent=16, spaceAfter=8)
S["code"] = ParagraphStyle("code", fontName="Courier", fontSize=8.6, leading=11.6,
                           textColor=INK)
S["foot"] = ParagraphStyle("foot", fontName="Helvetica", fontSize=7.5, leading=10,
                           textColor=DIM)


def band(text, colour=MAROON):
    """A full-width coloured strip introducing one half of the walkthrough."""
    t = Table([[Paragraph(text, S["band"])]], colWidths=[6.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colour),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def code(*lines):
    """One boxed block of commands, kept on a single page with its step."""
    body = "<br/>".join(l.replace("&", "&amp;").replace("<", "&lt;") for l in lines)
    t = Table([[Paragraph(body, S["code"])]], colWidths=[6.55 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Spacer(1, 2), t, Spacer(1, 8)]


def step(n, text):
    return Paragraph(f"<b>{n}.</b>&nbsp;&nbsp;{text}", S["step"])


def para(text):
    return Paragraph(text, S["body"])


def note(text):
    return Paragraph(text, S["note"])


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(2)
    canvas.line(0.8 * inch, 0.72 * inch, 7.7 * inch, 0.72 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DIM)
    canvas.drawString(0.8 * inch, 0.55 * inch,
                      "coursekit  ·  cs262 access  ·  full notes in docs/graders.md")
    canvas.drawRightString(7.7 * inch, 0.55 * inch, f"page {doc.page}")
    canvas.restoreState()


story = []
story.append(Paragraph(TITLE, S["title"]))
story.append(Paragraph(SUB, S["sub"]))
story.append(para(
    "Your TA does not need a copy of anyone's work emailed to them. They get "
    "read access to the student repositories and clone them themselves, with "
    "the same commands you use. Nothing is sent, nothing goes stale, and a "
    "late push costs them seconds. Part 1 is yours. Part 2 can be handed "
    "straight to the TA."))

# ── PART 1 ───────────────────────────────────────────────────────────
story.append(Spacer(1, 6))
story.append(band("PART 1  ·  What the instructor does, once per TA"))
story.append(Spacer(1, 10))

story.append(step(1, "<b>Get the TA's GitHub username.</b> Their login, not their "
                     "email address."))
story.append(step(2, "<b>Add one row to</b> <font face='Courier' size='9'>roster/roster.csv</font>. "
                     "The columns are "
                     "<font face='Courier' size='8.5'>username, first_name, last_name, email, "
                     "section, github_id, role</font>. The GitHub login goes in "
                     "<font face='Courier' size='9'>github_id</font>, and the role must be "
                     "<font face='Courier' size='9'>grader</font>:"))
story += code("tmiller,Tami,Miller,,,tmiller-gh,grader")
story.append(note("A grader is never given an assignment, never graded, and never "
                  "counted in the class size."))

story.append(step(3, "<b>Grant access.</b> The first line is a preview and changes "
                     "nothing; the second does it."))
story += code("cs262 access a04",
              "cs262 access a04 --go",
              "",
              "cs262 access --go          # every assignment at once")
story.append(note("This invites the TA to the organization (one invitation, not one per "
                  "repository) and grants read on all 42 student repositories plus the "
                  "template. Read, never write: the run prints “0 write accesses "
                  "granted”. From now on, assign --go grants it automatically for any "
                  "new repository."))

story.append(step(4, "<b>Build the folder the TA works from.</b>"))
story += code("cs262 access a04 --share ~/Desktop/cs262-grader")
story.append(note("A few kilobytes: course.json, the roster with email addresses "
                  "blanked, and each assignment's assignment.json, starter/, answers/ "
                  "and grading bundle. It also writes a README for the TA with Part 2 "
                  "in it, with your real course name filled in."))

story.append(step(5, "<b>Send the TA two things:</b> that folder, zipped, and this "
                     "repository, which holds the toolkit and page 2 of these notes:"))
story += code(TOOLKIT_REPO)

story.append(Spacer(1, 4))
story.append(para("<b>At any point:</b> <font face='Courier' size='9'>cs262 access a04</font> "
                  "on its own shows who has access to what, and "
                  "<font face='Courier' size='9'>cs262 access a04 --revoke --go</font> takes "
                  "it back."))

# ── PART 2 ───────────────────────────────────────────────────────────
story.append(PageBreak())
story.append(band("PART 2  ·  What the TA does", colors.HexColor("#2c4a5e")))
story.append(Spacer(1, 10))
story.append(para("Do steps 1 to 4 once. Step 5 is what you run for every assignment."))

story.append(step(1, "<b>Accept the GitHub invitation first.</b> It arrives by email and "
                     "expires after seven days. Until you accept it, the repositories are "
                     "invisible to you and step 3 will fail."))
story.append(step(2, "<b>Install the GitHub CLI</b> from cli.github.com, then:"))
story += code("gh auth login        # choose HTTPS when it asks",
              "gh auth setup-git    # lets git clone private repositories")
story.append(step(3, "<b>Install the toolkit and point it at the folder</b> your "
                     "instructor sent you. It needs git, python3 and node already "
                     "installed:"))
story += code(f"git clone {TOOLKIT_REPO} ~/coursekit",
              "cd ~/coursekit",
              "./install --non-interactive --course cs262 \\",
              "          --org Calvin-CS-classrooms \\",
              "          --folder ~/Desktop/cs262-grader")
story.append(note("If it stops on “gh org access”, step 1 is not done yet."))
story.append(step(4, "<b>Put the command on your PATH</b> if the installer says to: add "
                     "the line it prints to <font face='Courier' size='9'>~/.zshrc</font>, "
                     "open a new terminal, and check with "
                     "<font face='Courier' size='9'>cs262</font>."))
story.append(step(5, "<b>Grade.</b>"))
story += code("cs262 collect a04     # clones all 42 into ~/cs262-grading/a04/checkouts/",
              "cs262 sheet a04       # a CSV, sorted by last name, with empty mark columns",
              "",
              "# to grade what existed at the deadline, add to either one:",
              "#   --as-of \"2026-10-14T23:59:59-04:00\"")
story.append(note("Re-running collect updates the clones instead of downloading again, so "
                  "picking up a late push takes seconds."))
story.append(step(6, "<b>Fill in the CSV and send it back.</b> Type in the "
                     "<font face='Courier' size='9'>mark</font> and "
                     "<font face='Courier' size='9'>comment</font> columns in a spreadsheet. "
                     "Nothing reads it back automatically, so email it to the instructor."))

story.append(Spacer(1, 10))
story.append(Paragraph("If something looks wrong", S["h2"]))
rows = [
    ["I see no repositories at all",
     "You have not accepted the organization invitation. The instructor can "
     "re-send it; cs262 access names who is still pending."],
    ["One student says “no repository”",
     "That student has no GitHub username on the roster yet. Not your problem "
     "to fix; tell the instructor."],
    ["git asks for a password",
     "Run gh auth setup-git again."],
    ["The command is not found",
     "~/.local/bin is not on your PATH. See step 4."],
]
t = Table([[Paragraph(f"<b>{a}</b>", S["body"]), Paragraph(b, S["body"])] for a, b in rows],
          colWidths=[2.1 * inch, 4.8 * inch])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (0, -1), 0),
]))
story.append(t)

doc = BaseDocTemplate(OUT, pagesize=letter,
                      leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                      topMargin=0.75 * inch, bottomMargin=0.95 * inch,
                      title=TITLE, author="Eric Araujo")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])
doc.build(story)
print("wrote", OUT)
