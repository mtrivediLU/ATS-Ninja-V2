# T1 document templates

The web app provides two session-local presentation templates for the existing
Resume and Cover Letter artifacts: **Classic ATS** and **Modern ATS**. The
feature is intentionally frontend-only. It does not rewrite, reorder, score,
validate, persist, or send document content.

## Mapping and safety

The mapper uses the narrowest safe route available from the current API shape:

1. Resume text with standalone recognized headings uses a deterministic
   heading/section presentation model (Tier 3).
2. Cover letters, tabular/column-like resumes, and unknown structures use the
   closed verbatim fallback (Tier 4). The exact supplied text is displayed and
   exported without inferred fields or rewritten prose.

The API currently supplies plain text and optional engine-provided LaTeX, not
structured recipient, contact, or resume-section fields. No template invents
those fields. A local edit stays local to the current React session and is
always labelled **not revalidated**; it is never sent to the API or persisted.

## Interaction and exports

Choose **Template** from a Resume or Cover Letter workspace, then switch
Classic/Modern with the radio cards or arrow keys. The preview has page
controls, zoom/fit controls, a print preview dialog, and a Download / Print
menu. Browser printing uses Letter pages and native browser print / Save as
PDF. No PDF service is used.

Exports are local only:

- `.txt` is the exact current visible text.
- `.tex` is the exact existing engine-provided LaTeX and is disabled when it is
  unavailable. It is explicitly labelled when a local edit is not represented.
- Print / Save as PDF uses the selected visual template.

Filename shape is `{company}-{role}-{artifact}-{template}-ats`, omitting
unavailable company/role values and applying the existing safe filename
normalization.

## Accessibility and responsive behavior

Template cards form a labelled radio group with arrow-key selection. The export
menu supports arrow-key navigation and Escape. Print preview traps focus,
restores focus to its trigger, and closes with Escape. Mobile keeps the preview
inside its viewport with no page-level horizontal scroll; desktop uses a
two-column picker/preview layout.

## Verification

Run the focused pure tests with:

```bash
pnpm --filter @ats-ninja/web test
```

Then run the web lint, typecheck, and production build gates from the repository
root. The Docker/browser verification procedure and its observed result are
recorded in the pull request body for the implementation change.
