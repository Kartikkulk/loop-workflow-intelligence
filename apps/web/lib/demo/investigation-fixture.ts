/**
 * Captured from the generic Phase 5C investigation scenario.
 *
 * The backend Investigator is currently a service, not an HTTP endpoint, so the
 * console cannot fetch a persisted InvestigationResult yet. Keeping this small
 * display fixture separate prevents it being mistaken for live cluster data.
 */
export const INVESTIGATION_FIXTURE = {
  source: "Phase 5C demo fixture",
  candidate: "Source to destination handling",
  status: "ok",
  relationship: "conditional_step",
  confidence: 0.78,
  executions: 100,
  users: 10,
  coreSteps: [
    "app_a:source_action:record",
    "app_b:transform_action:record",
    "app_c:destination_action:record",
  ],
  variantStep: "app_d:followup_action:record",
  variantExecutions: 20,
  variantRate: 0.2,
  contextSignal: "needs_followup",
  evidenceIds: ["variant_stats_01", "context_var_01", "field_overlap_02"],
  sourceDestinationFields: ["entity_name", "amount", "date"],
  evidenceGaps: [] as string[],
} as const;
