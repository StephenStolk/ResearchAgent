export type ResearchStatus = "idle" | "researching" | "complete" | "error";

export type ReportStatus = "VERIFIED" | "PARTIAL" | "NEEDS_REVIEW";
export type VerificationStatus =
  | "SUPPORTS"
  | "PARTIAL"
  | "CONTRADICTS"
  | "INSUFFICIENT"
  | "OUTDATED"
  | "UNVERIFIED";

export interface Source {
  id: string;
  url: string;
  canonical_url: string;
  title?: string | null;
  publisher?: string | null;
  tier: string;
  authority_score: number;
}

export interface Claim {
  id: string;
  text: string;
  claim_type: string;
  importance: "HIGH" | "MEDIUM" | "LOW";
  metric?: string | null;
  date?: string | null;
  evidence_ids: string[];
  status: VerificationStatus;
  verification_confidence?: number | null;
  verification_notes?: string | null;
}

export interface Conflict {
  id: string;
  claim_ids: string[];
  description: string;
  resolved: boolean;
}

export interface ContentViews {
  article_sections: { heading: string; body: string; claim_ids: string[] }[];
  executive_brief: string[];
  timeline: { date: string | null; text: string; claim_id: string }[];
  metrics: { metric: string | null; value_text: string; claim_id: string }[];
  flags: string[];
}

export interface ResearchPacket {
  job_id: string;
  topic: string;
  status: ReportStatus;
  created_at: number;
  sources: Source[];
  claims: Claim[];
  conflicts: Conflict[];
  insights: Insight[];
  charts: ChartSpec[];
  open_questions: string[];
  summary?: string | null;
  content?: ContentViews | null;
  stage_notes: string[];
  stage_timings_ms: Record<string, number>;
}

export interface ChartSeries {
  name: string;
  values: (number | null)[];
}

export interface ChartSpec {
  id: string;
  chart_type: "bar" | "line" | "pie" | "scatter" | "correlation";
  title: string;
  x_labels: string[];
  series: ChartSeries[];
  claim_ids: string[];
  source_ids: string[];
  note?: string | null;
}

export type InsightType = "TREND" | "CONCEPT" | "COMPARISON";

export interface Insight {
  id: string;
  type: InsightType;
  title: string;
  body: string;
  evidence_ids: string[];
  source_ids: string[];
  confidence: number;
}
