# OAT rubric helper

Fills in the John A. Logan College Online Course Assessment (OAT) rubric PDF.

## Status
- [x] `oat/pdf_fill.py`: overlays scores/notes onto `rubric.pdf` (the PDF is flat, no form fields)
- [x] `oat/scoring.py`: proposes the Section 4/5/6 summary bands from item scores
- [ ] D2L collector (Playwright, runs locally, you log in yourself)
- [ ] Rule-based scorer: collected course data -> proposed item scores with evidence
- [ ] Review page to override scores before generating the PDF

## Use
    pip install -r requirements.txt
    python -m oat.pdf_fill examples/sample_scores.json rubric.pdf filled.pdf

Scores: `1` present/accomplished, `0` not present in all courses / developing,
`X` not present, `NA` not applicable. Item ids are in `oat/rubric_spec.py`.
