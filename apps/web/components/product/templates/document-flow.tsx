import type { ReactNode } from "react";
import type { CoverLetterDocument, ResumeDocument } from "@/lib/api-types";
import type { TemplateArtifact, TemplateId } from "@/components/product/templates/template-definitions";
import { buildDocumentModel } from "@/components/product/templates/document-model";
import { ResumePage } from "@/components/product/templates/resume-classic";

type DocumentFlowProps = {
  artifact: TemplateArtifact;
  template: TemplateId;
  text: string;
  resumeDocument?: ResumeDocument | null;
  coverLetterDocument?: CoverLetterDocument | null;
  printable?: boolean;
};

export function DocumentFlow({ artifact, template, text, resumeDocument, coverLetterDocument, printable = false }: DocumentFlowProps) {
  const className = `t1-document-flow t1-${template} ${printable ? "t1-document-print" : ""}`;
  if (artifact === "resume" && resumeDocument) return <article className={className}><StructuredResume document={resumeDocument} /></article>;
  if (artifact === "cover-letter" && coverLetterDocument) return <article className={className}><StructuredCoverLetter document={coverLetterDocument} /></article>;

  const legacy = buildDocumentModel(artifact, text);
  return <article className={className}>
    {legacy.tier === 3 ? <ResumePage page={{ kind: "structured", headerLines: legacy.headerLines, sections: legacy.sections }} /> : <pre className="t1-document-verbatim">{text}</pre>}
  </article>;
}

function StructuredResume({ document }: { document: ResumeDocument }) {
  return <>
    {(document.candidate_name || document.professional_headline || document.contact_lines.length > 0) && <header className="t1-doc-header">
      {document.candidate_name && <h1 className="t1-doc-name">{document.candidate_name}</h1>}
      {document.professional_headline && <p className="t1-doc-headline">{document.professional_headline}</p>}
      {document.contact_lines.length > 0 && <p className="t1-doc-contact">{document.contact_lines.join(" · ")}</p>}
    </header>}
    {document.summary && <Section title="Professional Summary"><p>{document.summary}</p></Section>}
    {document.skill_groups.length > 0 && <Section title="Technical Skills"><div className="t1-skill-groups">{document.skill_groups.map((group, index) => <p key={`${group.label}-${index}`}><strong>{group.label}{group.label ? ": " : ""}</strong>{group.items.join(", ")}</p>)}</div></Section>}
    {document.experience.length > 0 && <Section title="Professional Experience">{document.experience.map((entry, index) => <section key={`${entry.employer}-${entry.title}-${index}`} className="t1-entry"><div className="t1-entry-heading"><strong>{[entry.employer, entry.location].filter(Boolean).join(" · ")}</strong><span>{entry.date_range}</span></div>{entry.title && <p className="t1-entry-title">{entry.title}</p>}{entry.bullets.length > 0 && <ul>{entry.bullets.map((bullet, bulletIndex) => <li key={`${bullet}-${bulletIndex}`}>{bullet}</li>)}</ul>}</section>)}</Section>}
    {document.education.length > 0 && <Section title="Education">{document.education.map((entry, index) => <section key={`${entry.institution}-${index}`} className="t1-entry"><div className="t1-entry-heading"><strong>{[entry.institution, entry.location].filter(Boolean).join(" · ")}</strong><span>{entry.date_range}</span></div>{entry.degree && <p className="t1-entry-title">{entry.degree}</p>}{entry.details.map((detail, detailIndex) => <p key={`${detail}-${detailIndex}`}>{detail}</p>)}</section>)}</Section>}
    {document.certifications.length > 0 && <Section title="Certifications"><ul>{document.certifications.map((item, index) => <li key={`${item.name}-${index}`}>{[item.name, item.date, item.link].filter(Boolean).join(" · ")}</li>)}</ul></Section>}
    {document.remaining_sections.map(({ heading, lines }, index) => <Section key={`${heading}-${index}`} title={heading}>{lines.map((line, lineIndex) => <p key={`${line}-${lineIndex}`}>{line}</p>)}</Section>)}
  </>;
}

function StructuredCoverLetter({ document }: { document: CoverLetterDocument }) {
  const recipient = [document.recipient_name, document.recipient_title, document.recipient_company, ...document.recipient_address].filter(Boolean);
  return <>
    {(document.sender_name || document.sender_contact_lines.length > 0) && <header className="t1-letter-sender"><h1 className="t1-doc-name">{document.sender_name}</h1>{document.sender_contact_lines.length > 0 && <p className="t1-doc-contact">{document.sender_contact_lines.join(" · ")}</p>}</header>}
    {document.date && <p className="t1-letter-date">{document.date}</p>}
    {recipient.length > 0 && <address className="t1-letter-recipient">{recipient.map((line, index) => <span key={`${line}-${index}`}>{line}</span>)}</address>}
    {document.target_role && <p className="t1-letter-role">Re: {document.target_role}</p>}
    {document.greeting && <p className="t1-letter-greeting">{document.greeting}</p>}
    <div className="t1-letter-body">{document.body_paragraphs.map((paragraph, index) => <p key={`${paragraph}-${index}`}>{paragraph}</p>)}</div>
    {document.closing && <p className="t1-letter-closing">{document.closing}</p>}
    {document.signature_name && <p className="t1-letter-signature">{document.signature_name}</p>}
  </>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="t1-section"><h2>{title}</h2><div className="t1-section-body">{children}</div></section>;
}
