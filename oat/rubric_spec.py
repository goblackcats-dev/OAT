"""Rubric structure for the Fall 2025 JALC OAT rubric (rubric.pdf).

Each item is (id, page, anchor). `anchor` is the text the row's first line starts
with on that page; pdf_fill.py uses it to find the row's position in the PDF.
"""

# Column x-ranges (PDF points) for the IDENTIFIED / NOTES columns on each page.
# ident = (x0, x1); notes = (x0, x1)
COLUMNS = {
    2: dict(ident=(263, 333), notes=(333, 592)),
    3: dict(ident=(302, 370), notes=(375, 592)),
    4: dict(ident=(156, 224), notes=(229, 592)),
    5: dict(ident=(184, 249), obj=(249, 323), rubric=(323, 369), notes=(369, 592)),
    6: dict(ident=(315, 383), notes=(388, 592)),
    7: dict(ident=(310, 383), notes=(388, 592)),
    8: dict(ident=(353, 418), notes=(423, 592)),
    9: dict(ident=(357, 422), notes=(428, 592)),
    10: dict(ident=(244, 312), notes=(317, 592)),
}

SECTIONS = {
    1: "Required Course Site Elements",
    2: "Learner Readiness",
    3: "Course Structure",
    4: "Active Learning Design",
    5: "Learning Assessment",
    6: "Communication/Course Delivery",
    7: "Learner Feedback",
    8: "Content & Resources",
    9: "Grades & Attendance",
}

# (id, page, anchor)
ITEMS = [
    # Section 1
    ("1.01", 2, "Course syllabus is available"),
    ("1.02", 2, "Course objectives are stated"),
    ("1.03", 2, "All required learning materials"),
    ("1.04", 2, "Textbook Information"),
    ("1.05", 2, "Tentative Course Schedule"),
    ("1.06", 2, "How to get started"),
    ("1.07", 2, "Welcome Message"),
    ("1.08", 2, "Course provides guidance on how to navigate"),
    ("1.09", 2, "Course Pacing and Structure"),
    ("1.10", 2, "Course includes step-by-step"),
    ("1.11", 2, "Netiquette posted"),
    ("1.12", 2, "Policy/Procedure/Statements"),
    ("1.13", 2, "Course provides support resources"),
    ("1.14", 2, "Students informed how to request"),
    ("1.15", 2, "Contact info for Disability"),
    ("1.16", 2, "Name"),
    ("1.17", 2, "Email"),
    ("1.18", 2, "Work Phone"),
    ("1.19", 2, "Response time stated"),
    ("1.20", 2, "Office Location"),
    ("1.21", 2, "Office Hours"),
    ("1.22", 2, "Degrees"),
    ("1.23", 2, "Verbal confirmation from instructor"),
    # Section 2
    ("2.01", 3, "Course Specific Technology"),
    ("2.02", 3, "D2L Online Orientation"),
    ("2.03", 3, "Technology skills are"),
    ("2.04", 3, "Learning styles"),
    ("2.05", 3, "Access to technology"),
    ("2.06", 3, "Other"),
    # Section 3
    ("3.01", 3, "Structure of course"),
    ("3.02", 3, "Course objectives are provided"),
    ("3.03", 3, "Overview provided"),
    ("3.04", 3, "All required course materials"),
    ("3.05", 3, "Course materials are free"),
    ("3.06", 3, "All modules, assignments"),
    ("3.07", 3, "A specific due date"),
    ("3.08", 3, "Course site navigation"),
    # Section 4 (scored 1 = incorporated)
    ("4.01", 4, "Online Discussion"),
    ("4.02", 4, "Role Playing"),
    ("4.03", 4, "Problem Solving"),
    ("4.04", 4, "Writing"),
    ("4.05", 4, "Group work"),
    ("4.06", 4, "Case Study"),
    ("4.07", 4, "Peer Review"),
    ("4.08", 4, "Interactive Media"),
    ("4.09", 4, "Other activity:"),
    ("4.10", 4, "Other activity:"),
    # Section 5
    ("5.01", 5, "Quiz / Exam"),
    ("5.02", 5, "Online discussion"),
    ("5.03", 5, "Student Self-Assessment"),
    ("5.04", 5, "Process by which"),
    ("5.05", 5, "Review (peer"),
    ("5.06", 5, "Case Study"),
    ("5.07", 5, "Project"),
    ("5.08", 5, "Paper (research"),
    ("5.09", 5, "Multimedia presentation"),
    ("5.10", 5, "Other learning assessment"),
    ("5.11", 5, "Other learning assessment"),
    # Section 6 - regular interaction
    ("6.01", 6, "Weekly Contact"),
    ("6.02", 6, "Monitor Student Progress"),
    ("6.03", 6, "Instructor Availability"),
    # substantive interaction
    ("6.04", 6, "Providing direct"),
    ("6.05", 6, "Assessing or providing"),
    ("6.06", 6, "Providing information"),
    ("6.07", 6, "Facilitating a group"),
    ("6.08", 6, "Other instructional"),
    # communication methods
    ("6.09", 7, "News/Announcements"),
    ("6.10", 7, "Class Discussion Form"),
    ("6.11", 7, "Discussions"),
    ("6.12", 7, "Feedback"),
    ("6.13", 7, "Video/Audio"),
    ("6.14", 7, "Synchronous"),
    ("6.15", 7, "Email"),
    ("6.16", 7, "Other"),
    # Section 7
    ("7.01", 8, "Early Check-In"),
    ("7.02", 8, "Midterm feedback"),
    ("7.03", 8, "End-of-course wrap-up"),
    ("7.04", 8, "Additional evaluation"),
    ("7.05", 8, "Verbal Confirmation:"),
    # Section 8
    ("8.01", 9, "External Tools"),
    ("8.02", 9, "Course Design & Navigation"),
    ("8.03", 9, "Text & Visual Design"),
    ("8.04", 9, "Images & Media"),
    ("8.05", 9, "Documents & Files"),
    ("8.06", 9, "Links & Interactivity"),
    ("8.07", 9, "LMS Accessibility"),
    ("8.08", 9, "Communication &"),
    ("8.09", 9, "Testing & Evaluation"),
    # Section 9
    ("9.01", 10, "Participation is taken"),
    ("9.02", 10, "Participation is visible"),
    ("9.03", 10, "Gradebook is complete"),
    ("9.04", 10, "Gradebook is organized"),
    ("9.05", 10, "Gradebook is a current"),
    ("9.06", 10, "Gradebook items are visible"),
    ("9.07", 10, "Overall/Current Grade"),
]

# Summary-band rows (a check mark is drawn in the IDENTIFIED column). (key, page, anchor)
BANDS = {
    4: [("Advanced", 4, "Advanced"), ("Essential", 4, "Essential"),
        ("Being Developed", 4, "Being Developed"), ("Not Evident", 4, "Not Evident")],
    5: [("Advanced", 5, "Advanced"), ("Essential", 5, "Essential"),
        ("Being Developed", 5, "Being Developed"), ("Not Evident", 5, "Not Evident")],
    6: [("Advanced", 7, "Advanced"), ("Essential", 7, "Essential"),
        ("Being Developed", 7, "Being Developed"), ("Not Evident", 7, "Not Evident")],
}

# Free-text boxes: key -> (page, anchor of the box's title line)
NOTE_BOXES = {
    "section1": (2, "SECTION 1 NOTES"), "section2": (3, "SECTION 2 NOTES"),
    "section3": (3, "SECTION 3 NOTES"), "section4": (4, "SECTION 4 NOTES"),
    "section5": (5, "SECTION 5 NOTES"), "section6": (7, "SECTION 6 NOTES"),
    "section7": (8, "SECTION 7 NOTES"), "section8": (9, "SECTION 8 NOTES"),
    "section9": (10, "SECTION 9 NOTES"),
    "strengths": (10, "AREAS OF STRENGTH NOTES"),
    "improvements": (10, "OPPORTUNITES FOR IMPROVEMENT NOTES"),
    "changes": (10, "CHANGES TO BE MADE NOTES"),
}

VALID_SCORES = {"X", "0", "1", "NA"}
