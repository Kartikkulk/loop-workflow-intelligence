"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_MOCK, apiUrl } from "@/lib/api/client";
import { keys } from "@/lib/api/queries";
import type { TrustState } from "@/lib/api/types";

interface StreamPayload {
  automation_id: string;
  name: string;
  trust: TrustState;
  shadow_run_count: number;
  coverage: number;
  replay_accuracy: number | null;
  at: string;
}

/**
 * Subscribes to the server-sent trust stream.
 *
 * This is what makes the confidence bar move on its own: a shadow run landing
 * anywhere — including one triggered from another tab or from curl during a
 * demo — pushes new state here without a refetch or a poll.
 */
export function useTrustStream(automationId: string | undefined) {
  const client = useQueryClient();
  const [payload, setPayload] = useState<StreamPayload | null>(null);
  const [connected, setConnected] = useState(false);
  const previousLevel = useRef<string | null>(null);

  useEffect(() => {
    if (!automationId) return;
    // Mock mode has no server to stream from. Reporting "not connected" is
    // correct: the trust bar then renders from the cached query instead of
    // pretending to be live.
    if (API_MOCK) return;

    const source = new EventSource(apiUrl(`/api/v1/automations/${automationId}/stream`));

    source.onopen = () => setConnected(true);

    source.addEventListener("trust", (event) => {
      try {
        const next = JSON.parse((event as MessageEvent).data) as StreamPayload;
        setPayload(next);

        // A level change means the ladder moved, so the cached detail and the
        // aggregate views are now wrong.
        if (previousLevel.current && previousLevel.current !== next.trust.level) {
          void client.invalidateQueries({ queryKey: keys.automation(automationId) });
          void client.invalidateQueries({ queryKey: keys.automations });
          void client.invalidateQueries({ queryKey: keys.roi });
        }
        previousLevel.current = next.trust.level;
      } catch {
        /* a malformed frame should not take down the stream */
      }
    });

    source.onerror = () => {
      setConnected(false);
      // EventSource reconnects on its own; closing here would prevent that.
    };

    return () => {
      source.close();
      setConnected(false);
    };
  }, [automationId, client]);

  return { payload, connected };
}
