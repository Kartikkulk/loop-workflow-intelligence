/** Response types, mirroring the backend Pydantic models. */

export interface Variance {
  step_order_entropy: number;
  parameter_spread: number;
  branch_count: number;
  judgement_ratio: number;
  variant_count: number;
  dominant_variant_share: number;
  /** Mean similarity of observed runs to each other, 0–1. */
  sequence_similarity: number;
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
  /** Automation Potential, 0-100. A ranking heuristic, not a prediction. */
  potential: number;
  potential_factors: { factor: string; measured: number | null; weight: number | null; points: number }[];
  variance_breakdown: Variance;
  build_effort: number;
  priority: number;
  do_not_automate: boolean;
  reasoning: string;
  /** How strong the evidence is: "early" | "moderate" | "strong". */
  evidence_level: string;
  /** True while the case rests on few observations. */
  requires_more_observation: boolean;
  /** Rejected on Discovery; hidden from the recommended list. */
  dismissed: boolean;
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
  /** n8n's id, once a review draft has been built there. Empty until then. */
  n8n_workflow_id: string;
  /** Final human sign-off, after reviewing the draft in n8n. */
  approved: boolean;
}

/**
 * Where an automation sits in the discovery -> approval -> automation flow.
 *
 * These three answers used to be spelled out separately on the approvals page,
 * on the automations page and in the nav badge, and they drifted: the approvals
 * page learned that an exported workflow has already been decided, the other two
 * never did. The result was a loop — Automations sent you to Approvals to
 * approve something Approvals had already filtered out, the badge counted it
 * forever, and the automation itself rendered nowhere. One definition, used by
 * all three, is what stops that happening again.
 */
export function isAwaitingApproval(automation: AutomationSummary): boolean {
  return !automation.approved && !isRunning(automation);
}

/** A person said yes — the final approval, after reviewing the n8n draft. */
export function isApproved(automation: AutomationSummary): boolean {
  return automation.approved || isRunning(automation);
}

/** A review draft has been built in n8n and is waiting to be opened/edited. */
export function hasReviewDraft(automation: AutomationSummary): boolean {
  return Boolean(automation.n8n_workflow_id);
}

/** Allowed to act on its own. Anything below ASSIST is built but switched off. */
export function isRunning(automation: AutomationSummary): boolean {
  return automation.trust_level === "ASSIST" || automation.trust_level === "AUTONOMOUS";
}

export interface ExecutionPlan {
  method: string;
  rationale: string;
  confidence: number;
  decided_by: string;
  alternative_method: string;
  alternative_rationale: string;
  factors: string[];
}

export interface ValidationFinding {
  check: string;
  detail: string;
  step_id: string;
  blocking: boolean;
}

export interface ValidationReport {
  ok: boolean;
  passed: string[];
  findings: ValidationFinding[];
  blocking_count: number;
}

export interface DryRunStep {
  step_id: string;
  connector: string;
  action: string;
  status: string;
  outputs: Record<string, unknown>;
  error: string | null;
}

export interface DryRunResult {
  status: string;
  steps: DryRunStep[];
  would_have: string[];
  held_by_guard: boolean;
  guard_reason: string | null;
  side_effects_performed: number;
}

export interface ObservedVariable {
  name: string;
  placeholder: string;
  step_token: string;
  key: string;
  samples: string[];
  distinct_count: number;
  occurrences: number;
}

export interface ObservedConstant {
  name: string;
  step_token: string;
  key: string;
  value: string;
  occurrences: number;
}

export interface GeneratedCode {
  method: string;
  filename: string;
  source: string;
  requirements: string[];
  caveats: string[];
  line_count: number;
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
  execution: ExecutionPlan | null;
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

export interface N8nPushResult {
  ok: boolean;
  workflow_id: string;
  /** Where to open the created workflow and choose its accounts. */
  configure_url: string;
  needs_credentials: string[];
  notes: string[];
  message: string;
}

export interface ActivityEvent {
  id: string;
  user_id: string;
  team: string;
  timestamp: string;
  app: string;
  action: string;
  object_type: string;
  duration_ms: number;
  payload: Record<string, unknown>;
  session_id: string | null;
  source: string;
}

export interface SourceFacet {
  value: string;
  count: number;
}

export interface ActivityPage {
  total: number;
  items: ActivityEvent[];
  sources: SourceFacet[];
  apps: SourceFacet[];
}

export interface N8nRun {
  id: string;
  status: string;
  started_at: string;
  finished_at: string;
  failed_node: string;
  error: string;
}

export interface N8nRunList {
  ok: boolean;
  workflow_id: string;
  configure_url: string;
  active: boolean;
  total: number;
  succeeded: number;
  failed: number;
  items: N8nRun[];
  message: string;
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

export interface DiscoveredWorkflow {
  id: string;
  name: string;
  occurrences: number;
  apps: string[];
  annual_hours: number;
  automatability: number;
}

export interface IngestResult {
  ok: boolean;
  events_ingested: number;
  events_rejected: number;
  errors: string[];
  source: string;
  clusters_detected: number;
  workflow_name: string | null;
  workflows: DiscoveredWorkflow[];
  sessions: number;
  applications: number;
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
  /** What Kriyā AI reads once connected, in plain words. */
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

export interface CurrentUser {
  username: string;
  name: string;
  signed_in: boolean;
  login_required: boolean;
  /** Sent back as `Authorization: Bearer`. Empty except on the login response. */
  token: string;
}

export interface UserOption {
  username: string;
  name: string;
}

export interface UserList {
  users: UserOption[];
  login_required: boolean;
}

export interface RunStep {
  step_id: string;
  connector: string;
  action: string;
  status: string;
  detail: string;
}

export interface RunItem {
  item: string;
  status: string;
  detail: string;
  steps: RunStep[];
}

export interface RunResult {
  ok: boolean;
  processed: number;
  completed: number;
  held: number;
  failed: number;
  side_effects: string[];
  items: RunItem[];
  message: string;
  dry_run: boolean;
}

