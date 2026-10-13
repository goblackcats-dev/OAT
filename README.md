# OAT rubric helper

Fills in the John A. Logan College Online Course Assessment (OAT) rubric PDF.

## Status
- [x] `oat/pdf_fill.py`: overlays scores/notes onto `rubric.pdf` (the PDF is flat, no form fields)
- [x] `oat/scoring.py`: proposes the Section 4/5/6 summary bands from item scores
- [x] `oat/collect.py`: D2L collector (Playwright, runs locally, you log in yourself); tested only against a mock server
- [x] `oat/analyze.py`: rule-based scorer (proposals + review list + copyright flags)
- [x] `oat/run.py`: one-click pipeline (login -> collect -> score -> filled PDF); `OAT.bat` launcher; `.github/workflows/build-exe.yml` builds `OAT.exe`
- [x] Override scores by editing `OAT_output/<id>/scores.json`, then `OAT.exe --refill <id>`

## Use
    pip install -r requirements.txt
    python -m oat.pdf_fill examples/sample_scores.json rubric.pdf filled.pdf

Scores: `1` present/accomplished, `0` not present in all courses / developing,
`X` not present, `NA` not applicable. Item ids are in `oat/rubric_spec.py`.

## Collect a course (run on your own computer)
    git clone <this repo> && cd OAT
    python -m venv .venv
    .venv\Scripts\activate          # Windows   (Mac: source .venv/bin/activate)
    pip install -r requirements.txt
    playwright install chromium
    python -m oat.collect https://learn.jalc.edu/d2l/home/105329

A browser opens. Log in (MFA included). The script waits, then reads the course through D2L's
read-only API and saves `out/105329/course.json` plus screenshots. Your password is never
seen or stored; the login lives only in the local `session/` folder (git-ignored).
Calls your role can't make (e.g. gradebook as a non-instructor) are listed under `api_errors`.

## One click
Double-click `OAT.bat` (needs Python), or use `OAT.exe` from the GitHub Actions artifact "OAT-windows".
First run asks for the course URL and offers to save your D2L login in the Windows Credential
Manager (never in a file). Update it any time with `OAT.exe --set-login`; remove with `--forget-login`.
Output goes to `OAT_output/<course id>/`: the filled PDF, `review.md`, and editable `scores.json`.

## The three confirmations and the Claude prompt
Copyright (1.23), learner feedback (7.05) and external-tool accessibility (8.01) are the instructor's own statements.
The tool shows evidence for each, then records YOUR answer: type it when asked, or put it in a file and pass
`--answers answers.json` (`{"copyright":"yes","feedback":"no","accessibility":"skip"}`), or `--skip-questions`
to leave them unanswered. Every run also writes `OAT_output/<id>/claude_prompt.md`: upload it with `scores.json`
to Claude and ask it to review the scores and finish the PDF.

## Privacy
No student names or emails are stored. Qwickly (which lists students) is read for attendance dates only, with no
page text or screenshot kept. J1/Jenzabar is not read at all.

## Everything the tool now does (one run)
1. Logs in (saved login or by hand), lists the courses where you are an instructor, and lets you pick your OTHER online/hybrid/HyFlex
   courses once (remembered; `--pick-courses` to redo, `--courses 123,456` to name them). Every course is scored, then combined:
   **1 = in all courses, 0 = in some, X = in none**.
2. Per course: modules, quizzes, dropboxes, discussions, grades, announcements, files (Word/PowerPoint/PDF text, links, alt text).
3. Syllabus: reads the Syllabus tool; if it shows the Simple Syllabus account error it clicks the direct-login button, searches for the
   course, picks the semester and clicks View. Fallback: `--syllabus file.pdf`.
4. Qwickly attendance (dates only, never student names), the Panorama (ADA) report, and a fail-safe **student view** check (switches to the
   student view to read what students see, then switches back; logs out if it cannot switch back). Skip with `--no-student-view`.
5. Instructor activity as COUNTS only (discussion posts and replies, feedback on dropbox work). No post text, no student ids.
6. Link checker for outside links, dictionary evidence for possible typos, Section 5 "Course Objective(s)" and "Rubric" columns,
   consistency of the weekly modules.
7. Page 1 from the Assessment Schedule spreadsheet (`--schedule file.xlsx`, remembered): facilitator, representatives, new-member observer, date,
   plus the table of your other courses and the acknowledgement checkbox. It also lists the sessions where you are on the committee.
8. The three instructor-only confirmations (evidence, then YOUR answer) and `claude_prompt.md` for review in Claude.

Everything is a PROPOSAL. You review it; the committee decides.

### Unverified on the real site (first real run will show)
Qwickly Records tab, the Simple Syllabus dashboard steps, the student-view role switch, the Panorama report layout, the enrollments list.
Each fails soft: a step that cannot run is listed in `review.md` instead of guessing.
