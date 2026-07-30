# Real-extraction fixture corpus

Real job postings and real resumes, supplied by the repository owner. Nothing
here is synthetic. Hand-written approximations of real documents are what let
every regression in this project's history survive its test suite, so a
substitute is never acceptable in this directory.

## Layout

```
candidate_resume.pymupdf.txt        the base resume, shared by every case
<case>/job_description.txt          the real posting
<case>/hand_labels.toml             ground truth, hand-written BEFORE the fix it validates
<case>/resume_ats_ninja.pymupdf.txt      what ATS-Ninja generated for that posting
<case>/resume_human_tailored.pymupdf.txt what the candidate tailored by hand
```

Resume text is PyMuPDF-extracted from the delivered PDF, so it is the same text
layer an ATS would read — including the layout defects that text layer carries.

## Anonymisation

Every resume redacts the same personal fields, using the same placeholders, so
the corpus is internally consistent and no PII enters git history:

| Real | Fixture |
|---|---|
| candidate name | `Candidate Name` / `CANDIDATE NAME` |
| phone | `000-000-0000` |
| personal email | `candidate@example.com` |
| LinkedIn | `linkedin.com/in/example-candidate` |
| personal site | `example.com` |
| credential IDs | `TEST-CRED-001` … `TEST-CRED-004` |

Everything the parsing and scoring tests actually exercise is preserved
verbatim: employers, job titles, dates, locations, education institutions,
certifications, skills, bullet prose, and the relocation/availability
statements. `Laurentian University` is an education institution, not PII, and
is kept.

## Jobscan baselines

`hand_labels.toml` `[meta]` carries externally supplied Jobscan scores. They are
recorded exactly as reported by Jobscan and are never estimated, interpolated,
or back-filled — a case with no score simply has none.
