/** Typed React Query hooks. The only way a component reads or writes server state. */

"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { http } from "./client";
import type {
  AutomationDetail,
  ObservationSource,
  BreakSchemaResult,
  ClusterDetail,
  ClusterList,
  ExceptionList,
  IngestResult,
  PatchList,
  PromoteResult,
  ReplayReport,
  RegisterSourceResult,
  RoiReport,
  ShadowRunList,
  SourceList,
  SimulateResult,
  Sop,
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
};

type Options<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

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
