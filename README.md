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
