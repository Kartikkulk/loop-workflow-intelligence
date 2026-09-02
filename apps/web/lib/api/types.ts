/** Response types, mirroring the backend Pydantic models. */

export interface Variance {
  step_order_entropy: number;
  parameter_spread: number;
  branch_count: number;
  judgement_ratio: number;
  variant_count: number;
  dominant_variant_share: number;
}

export interface ClusterSummary {
  id: string;
  name: string;
  description: string;
  signature: string[];
  apps: string[];
  instance_count: number;
  distinct_users: number;
  user_ids: string[];
  teams: string[];
  median_duration_ms: number;
  instances_per_user_per_week: number;
  annual_hours: number;
  is_organisational: boolean;
  context_switches_total: number;
  interruption_tax_hours: number;
  automatability: number;
  variance_breakdown: Variance;
  build_effort: number;
  priority: number;
  do_not_automate: boolean;
  reasoning: string;
  has_automation: boolean;
  automation_id: string | null;
}

export interface ClusterUser {
  user_id: string;
  team: string;
  instance_count: number;
  median_duration_ms: number;
  annual_hours: number;
}

export interface StepNode {
  index: number;
  app: string;
  action: string;
  object_type: string;
  label: string;
  median_duration_ms: number;
  alternatives: string[];
}

export interface SignatureVariant {
  signature: string[];
  count: number;
  share: number;
}

export interface ClusterDetail extends ClusterSummary {
  users: ClusterUser[];
  step_graph: StepNode[];
  variants: SignatureVariant[];
}

export interface ClusterList {
  total: number;
  recommended: ClusterSummary[];
  not_recommended: ClusterSummary[];
  total_annual_hours: number;
  total_interruption_tax_hours: number;
}

export type InvestigationRelationship =
  | "same_workflow"
  | "optional_step"
  | "conditional_step"
  | "separate_workflow"
  | "insufficient_evidence";

export interface InvestigationEvidence {
  evidence_id: string;
  evidence_type: string;
  source: "atlas_catalog" | "deterministic_stats";
  description: string;
  supporting_ids: string[];
  facts: Record<string, unknown>;
}

export interface InvestigationConclusion {
  relationship: InvestigationRelationship;
  confidence: number;
  reasoning: string;
  evidence_ids: string[];
  evidence_gaps: string[];
  subject: string;
  weakened: boolean;
}

export interface InvestigationResult {
  status: "ok" | "insufficient_evidence" | "unavailable" | "invalid";
  generated_by: "llm" | "fallback";
  model_name: string;
  candidate_workflow_id: string;
  conclusions: InvestigationConclusion[];
  semantic_relationships: {
    kind: string;
    from_token: string;
    to_token: string;
    confidence: number;
    evidence_ids: string[];
    evidence_gaps: string[];
    weakened: boolean;
  }[];
  evidence: InvestigationEvidence[];
  variant_statistics: {
    variant_token: string;
    base_pattern_frequency: number;
    variant_frequency: number;
    variant_rate: number;
    variant_position: string;
    associated_context_keys: string[];
    evidence_id: string;
  }[];
  evidence_gaps: string[];
  investigation_notes: string[];
  final_decision: "safe_to_continue" | "insufficient_evidence";
}

export interface ValidatedProposal {
  proposal_id: string;
  status: "validated" | "rejected";
  validation_score: number;
  issues: string[];
}

export interface ValidationResult {
  validated: ValidatedProposal[];
  rejected: ValidatedProposal[];
  notes: string[];
}

export interface ClusterInvestigationResponse {
  cluster_id: string;
  investigation: InvestigationResult;
  validation: ValidationResult;
  automation_eligible: boolean;
}

export type CandidateStatus = "observed" | "candidate" | "investigated" | "validated";

export interface CandidateWorkflow {
  workflow_id: string;
  name: string;
  signature_tokens: string[];
  session_count: number;
  occurrence_count: number;
  distinct_users: number;
  apps: string[];
  first_seen: string;
  last_seen: string;
  confidence: number;
  status: CandidateStatus;
  investigation: InvestigationResult | null;
  validation: ValidationResult | null;
  automation_id: string | null;
  automation_trust_level: string | null;
}

export interface CandidateWorkflowList {
  source: "browser_extension";
  total: number;
  items: CandidateWorkflow[];
}

export interface CandidateInvestigationResponse {
  candidate: CandidateWorkflow;
  result: InvestigationResult;
}

export interface CandidateValidationResponse {
  candidate: CandidateWorkflow;
  result: ValidationResult;
}

export interface CandidateAutomationResponse {
  workflow_id: string;
  cluster_id: string;
  automation_id: string;
  trust_level: string;
  generated_by: string;
}

export interface Sop {
  cluster_id: string;
  name: string;
  markdown: string;
  generated_by: string;
}

export type TrustLevel = "OBSERVE" | "SUGGEST" | "SHADOW" | "ASSIST" | "AUTONOMOUS";

export const TRUST_LADDER: TrustLevel[] = [
  "OBSERVE",
  "SUGGEST",
  "SHADOW",
  "ASSIST",
  "AUTONOMOUS",
];

export interface TrustState {
  level: TrustLevel;
  next_level: TrustLevel | null;
  confidence: number;
  runs_in_window: number;
  runs_required: number;
  average_score: number;
  threshold: number;
  critical_mismatches: number;
  can_promote: boolean;
  should_demote: boolean;
  blockers: string[];
}

export interface Step {
  id: string;
  type: string;
  connector: string;
  description: string;
  inputs: Record<string, unknown>;
  outputs: string[];
  depends_on: string[];
}

export interface Rule {
  condition: string;
  action: string;
  source: string;
  evidence_count: number;
  signature_key?: string | null;
}

export interface AutomationSummary {
  id: string;
  cluster_id: string;
  name: string;
  description: string;
  trust_level: TrustLevel;
  confidence: number;
  shadow_run_count: number;
  critical_mismatch_count: number;
  replay_accuracy: number | null;
  replay_total: number;
  replay_human_count: number;
  coverage: number;
  generated_by: string;
  annual_hours: number;
  step_count: number;
  created_at: string;
}

export interface AutomationDetail extends AutomationSummary {
  trigger: { type?: string; filter?: Record<string, unknown> };
  steps: Step[];
  guards: { requires_approval_if: string | null; irreversible: string[] };
  rules: Rule[];
  trust: TrustState;
  trust_history: { level: string; reason: string; at?: string }[];
  open_exception_count: number;
  pending_patch_count: number;
}

export interface ReplayFailure {
  event_id: string;
  reason: string;
  expected: Record<string, unknown>;
  predicted: Record<string, unknown>;
  diff_fields: string[];
  critical: boolean;
}

export interface ReplayReport {
  total: number;
  correct: number;
  accuracy: number;
  needs_approval: number;
  errored: number;
  not_comparable: number;
  days: number;
  failures: ReplayFailure[];
  failure_modes: Record<string, number>;
}

export interface ShadowRun {
  id: string;
  sequence: number;
  trigger_event_id: string | null;
  predicted: Record<string, unknown>;
  observed: Record<string, unknown>;
  field_matches: Record<string, boolean>;
  score: number;
  critical_mismatch: boolean;
  note: string;
  created_at: string;
}

export interface ShadowRunList {
  total: number;
  items: ShadowRun[];
  trust: TrustState;
}

export interface PromoteResult {
  ok: boolean;
  level: TrustLevel;
  message: string;
  trust: TrustState;
}

export interface ExceptionCase {
  id: string;
  automation_id: string;
  automation_name: string;
  reason: string;
  input_features: Record<string, unknown>;
  signature_key: string;
  confidence: number;
  status: string;
  human_decision: string | null;
  human_note: string | null;
  created_at: string;
}

export interface ExceptionList {
  total: number;
  open_count: number;
  items: ExceptionCase[];
}

export interface Patch {
  id: string;
  automation_id: string;
  automation_name: string;
  kind: string;
  step_id: string | null;
  field: string | null;
  from_value: string | null;
  to_value: string | null;
  confidence: number;
  auto_applicable: boolean;
  status: string;
  rationale: string;
  rule: { condition?: string; action?: string } | null;
  evidence_count: number;
  proposed_by: string;
  created_at: string;
}

export interface PatchList {
  total: number;
  proposed_count: number;
  items: Patch[];
}

export interface RoiAutomation {
  id: string;
  name: string;
  trust_level: TrustLevel;
  coverage: number;
  annual_hours: number;
  interruption_tax_hours: number;
  replay_accuracy: number | null;
  shadow_run_count: number;
}

export interface CoveragePoint {
  automation_id: string;
  automation_name: string;
  sequence: number;
  coverage: number;
  score: number;
}

export interface RoiReport {
  projected_annual_hours: number;
  realised_annual_hours: number;
  interruption_tax_hours: number;
  interruption_tax_recovered_hours: number;
  total_clusters: number;
  automatable_clusters: number;
  do_not_automate_clusters: number;
  total_automations: number;
  autonomous_count: number;
  average_coverage: number;
  trust_distribution: { level: TrustLevel; count: number }[];
  automations: RoiAutomation[];
  coverage_trend: CoveragePoint[];
}

export interface ConnectorInfo {
  name: string;
  mock_available: boolean;
  live_available: boolean;
  required_credentials: string[];
  api: string;
  active: string;
}

export interface SystemStatus {
  mock_connectors: boolean;
  connectors: ConnectorInfo[];
  llm_available: boolean;
  llm_model: string;
  llm_calls: number;
  llm_fallbacks: number;
  llm_estimated_cost_usd: number;
  event_count: number;
  cluster_count: number;
  automation_count: number;
  settings: Record<string, number | string>;
}

export interface IngestResult {
  ok: boolean;
  events_ingested: number;
  events_rejected: number;
  errors: string[];
  source: string;
  clusters_detected: number;
  workflow_name: string | null;
}

export interface BreakSchemaResult {
  ok: boolean;
  events_updated: number;
  message: string;
  patches_proposed: number;
  automations_affected: string[];
}

export interface SimulateResult {
  ok: boolean;
  runs: ShadowRun[];
  trust: TrustState;
  level: TrustLevel;
}

// ── observation sources ─────────────────────────────────────────────────────

export interface Capability {
  kind: string;
  label: string;
  summary: string;
  sees: string[];
  blind_to: string[];
  setup: string;
  effort: string;
  invasiveness: string;
  coverage_estimate: number;
  available: boolean;
  unavailable_reason: string;
}

export interface ObservationSource {
  id: string;
  kind: string;
  label: string;
  user_id: string;
  team: string;
  status: string;
  capture_scope: string;
  consent_granted: boolean;
  denylist: string[];
  event_count: number;
  rejected_count: number;
  last_event_at: string | null;
  created_at: string;
}

export interface Coverage {
  connected_sources: number;
  total_sources: number;
  estimated_coverage: number;
  apps_observed: { app: string; events: number }[];
  distinct_apps: number;
  total_events: number;
  observed_events: number;
  kinds_connected: string[];
}

export interface SourceList {
  total: number;
  items: ObservationSource[];
  capabilities: Capability[];
  coverage: Coverage;
}

export interface RegisterSourceResult {
  source: ObservationSource;
  token: string;
  consent_text: string;
  collector_config: Record<string, unknown>;
}

export interface ToolStatus {
  app: string;
  observed: boolean;
  events: number;
}

export interface Domain {
  key: string;
  label: string;
  summary: string;
  team: string;
  people: number;
  workflow_name: string;
  step_count: number;
  tools: ToolStatus[];
  is_template: boolean;
  tool_coverage: number;
  annual_hours: number;
  interruption_hours: number;
  reclaimable_hours: number;
  effort_reduction: number;
  do_not_automate: boolean;
}

export interface DomainList {
  total: number;
  items: Domain[];
  unwatched_tools: string[];
}

export interface MonitorableTool {
  key: string;
  label: string;
  reads: string;
  api: string;
  credentials: string[];
  missing_credentials: string[];
  needs_admin: boolean;
  connected: boolean;
}

export interface ToolInventory {
  total: number;
  connected: number;
  items: MonitorableTool[];
}

/* ── Connecting your own accounts ─────────────────────────────────────────── */

/**
 * One sign-in button on the Sources page.
 *
 * Note what is missing: there is no `client_secret`. The API never sends one
 * back, so no component can render one and no screenshot can leak one.
 */
export interface Provider {
  key: string;
  label: string;
  /** What LOOP reads once connected, in plain words. */
  reads: string;
  scopes: string[];
  /** True once this person has supplied their own client id and secret. */
  configured: boolean;
  setup_url: string;
  setup_steps: string[];
  /** The exact value to paste into the provider's redirect-URI field. */
  redirect_uri: string;
  client_id_env: string;
  client_secret_env: string;
  /** Truncated, so the person can tell which app it is. */
  client_id_hint: string;
  has_secret: boolean;
  connected: boolean;
  account_label: string;
  last_sync_at: string | null;
  events_imported: number;
  last_error: string | null;
}

export interface ProviderList {
  items: Provider[];
  connected_count: number;
}

export interface SyncResult {
  provider: string;
  /** Negative when disconnecting: that many events were deleted. */
  events_imported: number;
  total_events: number;
  clusters_found: number;
  message: string;
}

export interface StartOut {
  authorize_url: string;
}
