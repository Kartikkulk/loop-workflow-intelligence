/** Typed React Query hooks. The only way a component reads or writes server state. */

"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { http, setToken } from "./client";
import { isAwaitingApproval } from "./types";
import type {
  ActivityPage,
  CurrentUser,
  UserList,
  AutomationDetail,
  AutomationSummary,
  DryRunResult,
  GeneratedCode,
  ValidationReport,
  N8nPushResult,
  N8nRunList,
  ObservationSource,
  BreakSchemaResult,
  ClusterDetail,
  ClusterList,
  DomainList,
  ExceptionList,
  IngestResult,
  PatchList,
  ProviderList,
  PromoteResult,
  ReplayReport,
  RegisterSourceResult,
  RoiReport,
  ShadowRunList,
  SourceList,
  ToolInventory,
  SimulateResult,
  Sop,
  StartOut,
  SyncResult,
  SystemStatus,
} from "./types";

export const keys = {
  clusters: ["clusters"] as const,
  cluster: (id: string) => ["clusters", id] as const,
  sop: (id: string) => ["clusters", id, "sop"] as const,
  automations: ["automations"] as const,
  automation: (id: string) => ["automations", id] as const,
  shadowRuns: (id: string) => ["automations", id, "shadow-runs"] as const,
  exceptions: ["exceptions"] as const,
  patches: ["patches"] as const,
  roi: ["roi"] as const,
  system: ["system"] as const,
  sources: ["sources"] as const,
  domains: ["domains"] as const,
  tools: ["tools"] as const,
  providers: ["providers"] as const,
};

type Options<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

export function useCurrentUser() {
  return useQuery({
    queryKey: ["auth", "me"] as const,
    queryFn: () => http.get<CurrentUser>("/api/v1/auth/me"),
    // Asked once per load and kept: a sign-in state that silently refetches
    // mid-session can bounce someone to the login screen while they work.
    staleTime: Infinity,
    retry: false,
  });
}

export function useLoginUsers() {
  return useQuery({
    queryKey: ["auth", "users"] as const,
    queryFn: () => http.get<UserList>("/api/v1/auth/users"),
    staleTime: Infinity,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      http.post<CurrentUser>("/api/v1/auth/login", body),
    onSuccess: (user) => {
      setToken(user.token);
      void client.invalidateQueries();
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => http.post<CurrentUser>("/api/v1/auth/logout"),
    onSuccess: () => {
      setToken("");
      void client.invalidateQueries();
    },
  });
}

export function useClusters(options?: Options<ClusterList>) {
  return useQuery({
    queryKey: keys.clusters,
    queryFn: () => http.get<ClusterList>("/api/v1/clusters"),
    ...options,
  });
}

export function useCluster(id: string) {
  return useQuery({
    queryKey: keys.cluster(id),
    queryFn: () => http.get<ClusterDetail>(`/api/v1/clusters/${id}`),
    enabled: Boolean(id),
  });
}

export function useSop(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.sop(id),
    queryFn: () => http.get<Sop>(`/api/v1/clusters/${id}/sop`),
    enabled: enabled && Boolean(id),
    staleTime: Infinity,
  });
}

export function useAutomations() {
  return useQuery({
    queryKey: keys.automations,
    queryFn: () => http.get<{ total: number; items: AutomationDetail[] }>("/api/v1/automations"),
  });
}

export function useAutomation(id: string) {
  return useQuery({
    queryKey: keys.automation(id),
    queryFn: () => http.get<AutomationDetail>(`/api/v1/automations/${id}`),
    enabled: Boolean(id),
  });
}

export function useGeneratedCode(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["generated-code", id] as const,
    queryFn: () => http.get<GeneratedCode>(`/api/v1/automations/${id}/code`),
    enabled: enabled && Boolean(id),
  });
}

export function useValidateAutomation(id: string) {
  return useMutation({
    mutationFn: () => http.post<ValidationReport>(`/api/v1/automations/${id}/validate`),
  });
}

export function useDryRun(id: string) {
  return useMutation({
    mutationFn: () => http.post<DryRunResult>(`/api/v1/automations/${id}/dry-run`),
  });
}

export function useShadowRuns(id: string) {
  return useQuery({
    queryKey: keys.shadowRuns(id),
    queryFn: () => http.get<ShadowRunList>(`/api/v1/automations/${id}/shadow-runs`),
    enabled: Boolean(id),
  });
}

export function useExceptions() {
  return useQuery({
    queryKey: keys.exceptions,
    queryFn: () => http.get<ExceptionList>("/api/v1/exceptions"),
  });
}

export function usePatches() {
  return useQuery({
    queryKey: keys.patches,
    queryFn: () => http.get<PatchList>("/api/v1/patches"),
  });
}

export function useRoi() {
  return useQuery({
    queryKey: keys.roi,
    queryFn: () => http.get<RoiReport>("/api/v1/analytics/roi"),
  });
}

/**
 * Everything currently waiting on a human decision, as one number.
 *
 * An automation that has not reached ASSIST is not running — it is proposed.
 * Counting those alongside open exceptions and un-applied patches is what makes
 * the sidebar badge mean "you have this many decisions to make".
 */
export function useApprovalCount(): number {
  const automations = useAutomations();
  const exceptions = useExceptions();
  const patches = usePatches();

  const proposed = (automations.data?.items ?? []).filter(isAwaitingApproval).length;

  return proposed + (exceptions.data?.open_count ?? 0) + (patches.data?.proposed_count ?? 0);
}

export function useTools() {
  return useQuery({
    queryKey: keys.tools,
    queryFn: () => http.get<ToolInventory>("/api/v1/tools"),
  });
}

export function useDomains() {
  return useQuery({
    queryKey: keys.domains,
    queryFn: () => http.get<DomainList>("/api/v1/domains"),
  });
}

export function useSources() {
  return useQuery({
    queryKey: keys.sources,
    queryFn: () => http.get<SourceList>("/api/v1/sources"),
    // Coverage changes as a collector reports in, so this view refreshes on its
    // own while someone is watching the onboarding screen.
    refetchInterval: 5_000,
  });
}

export function useRegisterSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      kind: string;
      label: string;
      user_id: string;
      team?: string;
      capture_scope?: string;
      consent: boolean;
      denylist?: string[];
    }) => http.post<RegisterSourceResult>("/api/v1/sources", body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.sources });
      void client.invalidateQueries({ queryKey: keys.system });
    },
  });
}

export function useUpdateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      status?: string;
      capture_scope?: string;
      denylist?: string[];
    }) => http.patch<ObservationSource>(`/api/v1/sources/${id}`, patch),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.sources }),
  });
}

export function useRevokeSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.del<{ ok: boolean; message: string; events_deleted: number }>(
        `/api/v1/sources/${id}`,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.sources });
      void client.invalidateQueries({ queryKey: keys.clusters });
      void client.invalidateQueries({ queryKey: keys.system });
    },
  });
}

export function useRedetect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      http.post<{ ok: boolean; clusters_detected: number }>("/api/v1/ingest/redetect"),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useSystem() {
  return useQuery({
    queryKey: keys.system,
    queryFn: () => http.get<SystemStatus>("/api/v1/system"),
  });
}

/** Invalidates everything a write could plausibly have changed. */
function useRefreshAll() {
  const client = useQueryClient();
  return () => {
    for (const key of [
      keys.clusters,
      keys.automations,
      keys.exceptions,
      keys.patches,
      keys.roi,
      keys.system,
    ]) {
      void client.invalidateQueries({ queryKey: key });
    }
  };
}

export function useGenerateAutomation() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ clusterId, override }: { clusterId: string; override?: boolean }) =>
      http.post<AutomationDetail>(`/api/v1/clusters/${clusterId}/generate-automation`, {
        override_do_not_automate: Boolean(override),
      }),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.cluster(variables.clusterId) });
      refresh();
    },
  });
}

/**
 * Reject a discovered workflow from the Discovery screen.
 *
 * The candidate is hidden from the recommended list, not deleted — detection
 * would rediscover it from the event log. Reversible with useRestoreCluster.
 */
export function useDismissCluster() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<{ id: string; dismissed: boolean; message: string }>(
        `/api/v1/clusters/${id}/dismiss`,
        {},
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clusters }),
  });
}

export function useRestoreCluster() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<{ id: string; dismissed: boolean; message: string }>(
        `/api/v1/clusters/${id}/restore`,
        {},
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clusters }),
  });
}

export function useReplay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, days }: { id: string; days: number }) =>
      http.post<ReplayReport>(`/api/v1/automations/${id}/replay`, { days }),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      void client.invalidateQueries({ queryKey: keys.roi });
    },
  });
}

export function useSimulateShadow() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({
      id,
      count,
      forceMismatch,
    }: {
      id: string;
      count: number;
      forceMismatch?: boolean;
    }) =>
      http.post<SimulateResult>("/api/v1/demo/simulate-shadow-run", {
        automation_id: id,
        count,
        force_mismatch: Boolean(forceMismatch),
      }),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      void client.invalidateQueries({ queryKey: keys.shadowRuns(variables.id) });
      refresh();
    },
  });
}

export function usePromote() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) =>
      http.post<PromoteResult>(`/api/v1/automations/${id}/promote`, { force: Boolean(force) }),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      refresh();
    },
  });
}

/**
 * Approve a proposed workflow by creating it in n8n.
 *
 * The workflow arrives there switched off and with no accounts attached, so
 * approving decides that the work is worth automating without connecting
 * anything. Finishing it is a deliberate second act, in n8n, by a person.
 */
export function useApproveToN8n() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id, schedule }: { id: string; schedule?: string }) =>
      http.post<N8nPushResult>(
        `/api/v1/automations/${id}/n8n?schedule=${schedule ?? "hourly"}`,
        {},
      ),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      refresh();
    },
  });
}

/**
 * The final sign-off, pressed after reviewing (and possibly editing) the draft
 * in n8n. Building the draft (useApproveToN8n) and approving it are two acts on
 * purpose: a person gets to look at exactly what will run, change it in n8n, and
 * only then confirm.
 */
export function useApproveAutomation() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<AutomationSummary>(`/api/v1/automations/${id}/approve`, {}),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      refresh();
    },
  });
}

/**
 * How the exported workflow is getting on inside n8n.
 *
 * Polled rather than fetched once: the interesting moment is the first run
 * after somebody wires up the accounts, and that happens while this screen is
 * open. Without polling the person has to reload to find out whether the
 * configuration they just typed actually works.
 */
/**
 * The raw event stream, newest first.
 *
 * This exists so "Kriyā AI watched your work" is something a person can check
 * rather than take on trust. It is the evidence behind every discovery, and if
 * it is empty then nothing downstream is real either.
 */
export function useActivity(limit = 100, source?: string, app?: string) {
  // Filters go to the server, not to the fetched page. Filtering a page of 200
  // in the browser would only ever search the most recent 200 events, which on
  // a real log is a filter that quietly lies.
  const params = new URLSearchParams({ limit: String(limit) });
  if (source) params.set("source", source);
  if (app) params.set("app", app);
  const query = params.toString();

  return useQuery({
    queryKey: ["activity", query] as const,
    queryFn: () => http.get<ActivityPage>(`/api/v1/ingest/events?${query}`),
    refetchInterval: 5_000,
  });
}

export function useN8nRuns(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["n8n-runs", id] as const,
    queryFn: () => http.get<N8nRunList>(`/api/v1/automations/${id}/n8n/runs`),
    enabled,
    refetchInterval: 10_000,
  });
}

export function useDemote() {
  const client = useQueryClient();
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<PromoteResult>(`/api/v1/automations/${id}/demote`),
    onSuccess: (_data, variables) => {
      void client.invalidateQueries({ queryKey: keys.automation(variables.id) });
      refresh();
    },
  });
}

export function useResolveException() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id, decision, note }: { id: string; decision: string; note?: string }) =>
      http.post<{ ok: boolean; message: string; rules_proposed: number }>(
        `/api/v1/exceptions/${id}/resolve`,
        { decision, note: note ?? null },
      ),
    onSuccess: refresh,
  });
}

export function useApplyPatch() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<{ ok: boolean; message: string }>(`/api/v1/patches/${id}/apply`),
    onSuccess: refresh,
  });
}

export function useRejectPatch() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      http.post<{ ok: boolean; message: string }>(`/api/v1/patches/${id}/reject`),
    onSuccess: refresh,
  });
}

export function useBreakSchema() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: () => http.post<BreakSchemaResult>("/api/v1/demo/break-schema", {}),
    onSuccess: refresh,
  });
}

export function useSeedExceptions() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ id, count }: { id: string; count: number }) =>
      http.post<{ ok: boolean; message: string }>(
        `/api/v1/demo/seed-exceptions?automation_id=${id}&count=${count}`,
      ),
    onSuccess: refresh,
  });
}

export function useResetDemo() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => http.post<{ ok: boolean; message: string }>("/api/v1/demo/reset"),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useDescribeWorkflow() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ description }: { description: string }) =>
      http.post<IngestResult>("/api/v1/ingest/describe", { description, weeks: 12 }),
    onSuccess: refresh,
  });
}

export function useUploadLog() {
  const refresh = useRefreshAll();
  return useMutation({
    mutationFn: ({ file }: { file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return http.postForm<IngestResult>("/api/v1/ingest/upload", form);
    },
    onSuccess: refresh,
  });
}


/* ── Connecting your own accounts ─────────────────────────────────────────── */

export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => http.get<ProviderList>("/api/v1/connect/providers"),
  });
}

/** Save the client id and secret from this person's own OAuth app. */
export function useSaveCredentials() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      provider,
      ...body
    }: {
      provider: string;
      client_id: string;
      client_secret: string;
    }) => http.put<ProviderList>(`/api/v1/connect/${provider}/credentials`, body),
    onSuccess: (data) => client.setQueryData(keys.providers, data),
  });
}

export function useForgetCredentials() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider }: { provider: string }) =>
      http.del<ProviderList>(`/api/v1/connect/${provider}/credentials`),
    onSuccess: (data) => {
      client.setQueryData(keys.providers, data);
      void client.invalidateQueries({ queryKey: keys.clusters });
      void client.invalidateQueries({ queryKey: keys.system });
    },
  });
}

/**
 * Ask the API for the provider's sign-in URL, then leave for it.
 *
 * The redirect happens here rather than server-side because the browser has to
 * arrive at the provider as a top-level navigation — a fetch that followed the
 * redirect would land the sign-in page inside a JSON response.
 */
export function useStartConnect() {
  return useMutation({
    mutationFn: async ({ provider }: { provider: string }) => {
      const { authorize_url } = await http.get<StartOut>(
        `/api/v1/connect/${provider}/start`,
      );
      window.location.href = authorize_url;
      return authorize_url;
    },
  });
}

/** Read the account, store what it did, and re-run detection over everything. */
export function useSyncProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider }: { provider: string }) =>
      http.post<SyncResult>(`/api/v1/connect/${provider}/sync`),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useDisconnect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider }: { provider: string }) =>
      http.del<SyncResult>(`/api/v1/connect/${provider}`),
    onSuccess: () => client.invalidateQueries(),
  });
}
