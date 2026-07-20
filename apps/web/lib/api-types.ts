export type KitStatus = "pending" | "processing" | "completed" | "failed";
export type ClaimStatus = "supported" | "repaired" | "rejected";

export type OutreachAudience =
  | "recruiter"
  | "hiring_manager"
  | "employee"
  | "teammate"
  | "alumni"
  | "professional_contact";

export type OutreachIntent =
  | "connect"
  | "direct_message"
  | "follow_up"
  | "informational"
  | "referral_request"
  | "shared_affiliation";

export interface OutreachContextInput {
  recipient_name?: string;
  recipient_title?: string;
  recipient_company?: string;
  audience?: OutreachAudience;
  requested_intent?: OutreachIntent;
  has_applied?: boolean;
  application_date?: string;
  application_status?: string;
  referral_contact_name?: string;
  shared_affiliation?: string;
  mutual_connection?: string;
  prior_meeting?: string;
  prior_conversation?: string;
  personalization_note?: string;
  portfolio_url?: string;
}

export interface KitCreateInput {
  resume_text: string;
  job_description: string;
  requested_mode?: string;
  questions_text?: string;
  include_resume: boolean;
  include_cover_letter: boolean;
  include_application_answers: boolean;
  include_job_fit: boolean;
  include_interview_prep: boolean;
  include_linkedin_outreach: boolean;
  outreach_context?: OutreachContextInput;
}

export type ResumeExtractionMethod = "pdf_text" | "docx_text" | "plain_text";

export interface ResumeExtraction {
  filename: string;
  mime_type: string;
  size_bytes: number;
  extraction_method: ResumeExtractionMethod;
  text: string;
  character_count: number;
  page_count: number | null;
  warnings: string[];
  truncated: boolean;
}

export interface EvidenceRef {
  source: string;
  locator: string;
  excerpt: string;
}

export interface Claim {
  id: string;
  artifact: string;
  claim_type: string;
  text: string;
  status: ClaimStatus | string;
  disposition: string;
  reason: string;
  evidence: EvidenceRef[];
}

export interface ArtifactValidation {
  status: string;
  fatal: boolean;
  errors: string[];
  warnings: string[];
  repaired_claims: number;
  rejected_claims: number;
}

export interface ResumeArtifact {
  text: string;
  latex: string;
  validation: ArtifactValidation;
  claims: Claim[];
  interview_probability: number | null;
  document?: ResumeDocument | null;
}

export interface CoverLetterArtifact {
  text: string;
  latex: string;
  validation: ArtifactValidation;
  claims: Claim[];
  document?: CoverLetterDocument | null;
}

export interface ResumeSkillGroup { label: string; items: string[]; }
export interface ResumeExperienceEntry { employer: string; title: string; location: string; date_range: string; bullets: string[]; }
export interface ResumeEducationEntry { institution: string; degree: string; location: string; date_range: string; details: string[]; }
export interface ResumeCertificationEntry { name: string; date: string; link: string; }
export interface RemainingResumeSection { heading: string; lines: string[]; }
export interface ResumeDocument {
  candidate_name: string;
  professional_headline: string;
  contact_lines: string[];
  summary: string;
  skill_groups: ResumeSkillGroup[];
  experience: ResumeExperienceEntry[];
  education: ResumeEducationEntry[];
  certifications: ResumeCertificationEntry[];
  remaining_sections: RemainingResumeSection[];
}
export interface CoverLetterDocument {
  sender_name: string;
  sender_contact_lines: string[];
  date: string;
  recipient_name: string;
  recipient_title: string;
  recipient_company: string;
  recipient_address: string[];
  target_role: string;
  greeting: string;
  body_paragraphs: string[];
  closing: string;
  signature_name: string;
}

export interface AnswerItem {
  question: string;
  answer: string;
}

export interface AnswerArtifact {
  items: AnswerItem[];
  text: string;
  validation: ArtifactValidation;
  claims: Claim[];
  placeholders: string[];
}

export interface RequirementAssessment {
  id: string;
  requirement: string;
  importance: string;
  must_have: boolean;
  classification: string;
  explanation: string;
  risk: string;
  permitted_positioning: string;
  evidence: EvidenceRef[];
}

export interface PositioningRecommendation {
  requirement_id: string;
  text: string;
}

export interface ConsistencyValidation {
  passed: boolean;
  errors: string[];
  repaired_violations: string[];
}

export interface GenerationMetadata {
  generation_mode: string;
  llm_available: boolean;
  provider: string;
  model: string;
  provider_calls: number;
  fallback_used: boolean;
}

export interface ValidationSummary {
  passed: boolean;
  fatal: boolean;
  error_count: number;
  warning_count: number;
  errors: string[];
  warnings: string[];
}

export interface JobFitArtifact {
  summary: string;
  requirement_coverage_score: number;
  fit_band: string;
  ats_keyword_score: number;
  interview_probability: number | null;
  requirements: RequirementAssessment[];
  strongest_matches: string[];
  adjacent_capabilities: string[];
  working_knowledge: string[];
  genuine_gaps: string[];
  must_have_gaps: string[];
  positioning_recommendations: PositioningRecommendation[];
  validation: ArtifactValidation;
  consistency: ConsistencyValidation;
  generation: GenerationMetadata;
  claims: Claim[];
  evidence: EvidenceRef[];
  warnings: string[];
  withheld: boolean;
}

export interface InterviewFocusArea {
  requirement_id: string;
  topic: string;
  classification: string;
  priority: string;
  guidance: string;
  evidence: EvidenceRef[];
}

export interface InterviewAnswerGuide {
  key_points: string[];
  statements_to_avoid: string[];
  suggested_answer: string;
  honest_gap_language: string;
  evidence: EvidenceRef[];
}

export interface InterviewQuestion {
  id: string;
  category: string;
  question: string;
  rationale: string;
  related_requirement_ids: string[];
  priority: string;
  answer_guide: InterviewAnswerGuide;
  evidence: EvidenceRef[];
  gap_relevance: string;
  validation: ArtifactValidation;
}

export interface StarStory {
  id: string;
  source_type: string;
  employer_or_institution: string;
  title_or_degree: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  completeness: string;
  missing_components: string[];
  safe_usage_guidance: string;
  evidence: EvidenceRef[];
  validation: ArtifactValidation;
}

export interface TechnicalStudyTopic {
  requirement_id: string;
  topic: string;
  reason: string;
  boundary: string;
  priority: string;
}

export interface GapHandlingGuide {
  requirement_id: string;
  requirement: string;
  classification: string;
  must_have: boolean;
  guidance: string;
  what_to_avoid: string[];
  evidence: EvidenceRef[];
}

export interface InterviewerQuestion {
  id: string;
  question: string;
  rationale: string;
  source: string;
}

export interface InterviewPrepArtifact {
  strategy_summary: string;
  focus_areas: InterviewFocusArea[];
  questions: InterviewQuestion[];
  star_stories: StarStory[];
  technical_study_topics: TechnicalStudyTopic[];
  gap_handling: GapHandlingGuide[];
  positioning_recommendations: PositioningRecommendation[];
  interviewer_questions: InterviewerQuestion[];
  validation: ArtifactValidation;
  consistency: ConsistencyValidation;
  generation: GenerationMetadata;
  claims: Claim[];
  evidence: EvidenceRef[];
  warnings: string[];
  withheld: boolean;
}

export interface OutreachContextRef {
  kind: string;
  field: string;
  excerpt: string;
}

export interface OutreachDraft {
  id: string;
  audience: string;
  intent: string;
  format: string;
  text: string;
  character_count: number;
  character_limit: number;
  target_company: string;
  target_role: string;
  personalization_fields: string[];
  call_to_action: string;
  evidence: EvidenceRef[];
  target_context: OutreachContextRef[];
  relationship_context: OutreachContextRef[];
  validation: ArtifactValidation;
}

export interface RelationshipValidation {
  passed: boolean;
  errors: string[];
  repaired_violations: string[];
}

export interface LinkedInOutreachArtifact {
  strategy_summary: string;
  drafts: OutreachDraft[];
  validation: ArtifactValidation;
  consistency: ConsistencyValidation;
  relationship_validation: RelationshipValidation;
  generation: GenerationMetadata;
  claims: Claim[];
  evidence: EvidenceRef[];
  target_context: OutreachContextRef[];
  relationship_context: OutreachContextRef[];
  warnings: string[];
  withheld: boolean;
}

export interface ApplicationKit {
  schema_version: string;
  engine_version: string;
  orchestration_version: string;
  requested_mode: string;
  resolved_mode: string;
  generation: GenerationMetadata;
  validation: ValidationSummary;
  resume: ResumeArtifact | null;
  cover_letter: CoverLetterArtifact | null;
  answers: AnswerArtifact | null;
  job_fit: JobFitArtifact | null;
  interview_prep: InterviewPrepArtifact | null;
  linkedin_outreach: LinkedInOutreachArtifact | null;
  warnings: string[];
}

export interface KitRead {
  id: string;
  status: KitStatus;
  requested_mode: string;
  include_resume: boolean;
  include_cover_letter: boolean;
  include_application_answers: boolean;
  include_job_fit: boolean;
  include_interview_prep: boolean;
  include_linkedin_outreach: boolean;
  result: ApplicationKit | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface KitSummary {
  id: string;
  status: KitStatus;
  created_at: string;
  updated_at: string;
}

export interface KitList {
  items: KitSummary[];
  total: number;
  limit: number;
  offset: number;
}
