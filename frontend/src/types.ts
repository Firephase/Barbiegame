export type Epistemic = "verified" | "interpretation" | "uncertain" | "ai_inference";

export interface Author {
  name: string;
  given?: string | null;
  family?: string | null;
  orcid?: string | null;
  affiliation?: string | null;
}

export interface QualitySignal {
  dimension: string;
  verdict: "strong" | "adequate" | "weak" | "unknown" | "caution";
  explanation: string;
  weight: number;
}

export interface SourceQuality {
  tier: string;
  signals: QualitySignal[];
  summary: string;
  caveats: string[];
}

export interface Passage {
  id: string;
  source_id: string;
  text: string;
  page?: number | null;
  section?: string | null;
  start_seconds?: number | null;
  score?: number | null;
}

export interface Source {
  id: string;
  kind: string;
  title: string;
  url?: string | null;
  doi?: string | null;
  authors: Author[];
  container_title?: string | null;
  site_name?: string | null;
  published?: string | null;
  is_peer_reviewed?: boolean | null;
  is_open_access?: boolean | null;
  retracted?: boolean | null;
  cited_by_count?: number | null;
  evidentiary: string;
  abstract?: string | null;
  full_text_retrieved: boolean;
  retrieval_note?: string | null;
  retrieved_by: string;
  quality?: SourceQuality | null;
  passages?: Passage[];
  extra: Record<string, unknown>;
  /* present on project source listings */
  passage_count?: number;
  origin?: string;
  starred?: boolean;
  excluded?: boolean;
  citation?: string | null;
  has_file?: boolean;
}

export interface Citation {
  source_id: string;
  passage_ids: string[];
  quote?: string | null;
  locator?: string | null;
}

export interface Claim {
  id: string;
  text: string;
  status: Epistemic;
  citations: Citation[];
  verification_note?: string | null;
  support_score?: number | null;
  contested_by: string[];
}

export interface Position {
  stance: string;
  source_ids: string[];
  note?: string | null;
}

export interface Disagreement {
  topic: string;
  positions: Position[];
  assessment?: string | null;
}

export interface TraceStep {
  stage: string;
  detail: string;
  data: Record<string, unknown>;
  duration_ms?: number | null;
}

export interface Trace {
  queries_issued: string[];
  providers_used: string[];
  providers_unavailable: { provider: string; reason: string }[];
  sources_considered: number;
  sources_selected: string[];
  sources_rejected: { title: string; reason: string }[];
  assumptions: string[];
  steps: TraceStep[];
  computations: Record<string, unknown>[];
  limitations: string[];
}

export interface Answer {
  id: string;
  question: string;
  mode: string;
  summary: string;
  claims: Claim[];
  sources: Source[];
  disagreements: Disagreement[];
  open_questions: string[];
  trace: Trace;
  warnings: string[];
  created_at: string;
  /* server-side extras */
  citations?: Record<string, string>;
  confidence_breakdown?: Record<Epistemic, number>;
  followups?: string[];
}

export interface Project {
  id: string;
  name: string;
  question: string;
  description: string;
  settings: Record<string, unknown>;
  archived: boolean;
  created_at: string;
  updated_at: string;
  source_count: number;
  message_count: number;
  note_count: number;
  passage_count: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  mode: string;
  content: string;
  answer?: Answer | null;
  created_at: string;
}

export interface Note {
  id: string;
  title: string;
  body: string;
  source_ids: string[];
  tags: string[];
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResearchMode {
  name: string;
  label: string;
  description: string;
  max_sources: number;
  searches_web: boolean;
  searches_academic: boolean;
  requires_reasoning_model: boolean;
}

export interface Capabilities {
  modes: ResearchMode[];
  citation_styles: { id: string; label: string }[];
  export_formats: string[];
  chart_forms: string[];
  explanation_levels: { id: string; label: string }[];
  depths: string[];
  source_types: string[];
}

export interface ProviderInfo {
  capability: string;
  name: string;
  available: boolean;
  reason: string;
  requires_credentials: boolean;
  [key: string]: unknown;
}

export interface ProvidersReport {
  capabilities: Record<
    string,
    { available: boolean; active: string | null; selected: string[]; providers: ProviderInfo[] }
  >;
  configuration: Record<string, unknown>;
  degraded: string[];
}

export interface Controls {
  max_sources: number;
  date_from: string | null;
  date_to: string | null;
  source_types: string[];
  academic_only: boolean;
  web_only: boolean;
  open_access_only: boolean;
  include_preprints: boolean;
  language: string | null;
  region: string | null;
  domains_include: string[];
  domains_exclude: string[];
}

export interface ChartSeries {
  name: string;
  x: (string | number)[];
  y: number[];
  error?: number[] | null;
  color: string;
  labels?: string[] | null;
}

export interface ChartSpec {
  form: string;
  title: string;
  subtitle: string;
  x: { label: string; unit: string; scale: string; min: number | null; max: number | null };
  y: { label: string; unit: string; scale: string; min: number | null; max: number | null };
  series: ChartSeries[];
  legend: boolean;
  direct_labels: boolean;
  table_view: boolean;
  caption: string;
  notes: string[];
  matrix?: (number | null)[][] | null;
  matrix_rows?: string[] | null;
  matrix_cols?: string[] | null;
  diverging: boolean;
  mode: "light" | "dark";
  palette: {
    categorical: string[];
    chrome: Record<string, string>;
    sequential: string[];
    diverging: Record<string, string>;
  };
  dataset?: string;
  artifact_id?: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  weight: number;
  detail: string;
  source_ids: string[];
  meta: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { nodes: number; edges: number; by_kind: Record<string, number> };
}

export interface Diagram {
  id: string;
  kind: string;
  title: string;
  source: string;
  dialect: string;
  node_count: number;
  edge_count: number;
  notes: string[];
  revision: number;
  renderer: string;
}

export interface ApiError {
  code: string;
  message: string;
  detail: Record<string, unknown>;
}
