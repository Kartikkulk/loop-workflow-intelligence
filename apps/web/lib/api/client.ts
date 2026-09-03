/**
 * The single HTTP boundary. Nothing outside this directory calls fetch.
 *
 * Errors are unwrapped into a readable message: FastAPI returns validation
 * detail as a nested array and error bodies as a `detail` object, and a UI that
 * renders `[object Object]` in a toast is worse than one that says nothing.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

/**
 * Mock mode: serve GETs from committed fixtures instead of the network.
 *
 * `NEXT_PUBLIC_API_MOCK=1 npm run dev` lets the frontend be developed with no
 * Python, no database and no running backend. Over a short deadline that is the
 * difference between two people working in parallel and one waiting for the
 * other. Fixtures are captured from the real API (`make fixtures`), so the
 * shapes are real rather than hand-written guesses that drift.
 */
export const API_MOCK = process.env.NEXT_PUBLIC_API_MOCK === "1";

/** Latency injected in mock mode, so loading states are actually exercised. */
const MOCK_DELAY_MS = 180;

async function mockRequest<T>(path: string, method: string): Promise<T> {
  const { default: fixtures } = await import("./fixtures.json");
  const table = fixtures as Record<string, unknown>;

  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));

  if (method !== "GET") {
    // Deliberately not faked. A mocked mutation would return success without
    // changing anything, so the UI would look correct while being wrong — worse
    // than an honest error that says which endpoint needs the real backend.
    throw new ApiError(
      `${method} ${path} needs the real API. Mock mode serves reads only — ` +
        "run `make api` in another terminal and drop NEXT_PUBLIC_API_MOCK.",
      501,
    );
  }

  const bare = path.split("?")[0];
  if (bare in table) return table[bare] as T;

  throw new ApiError(
    `No fixture for GET ${bare}. Add it to ENDPOINTS in ` +
      "apps/api/scripts/export_fixtures.py and re-run `make fixtures`.",
    404,
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function readDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (entry && typeof entry === "object" && "msg" in entry) {
          const loc = "loc" in entry && Array.isArray(entry.loc) ? entry.loc.join(".") : "";
          return loc ? `${loc}: ${String(entry.msg)}` : String(entry.msg);
        }
        return null;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") {
      const extra = typeof record.reasoning === "string" ? ` ${record.reasoning}` : "";
      return record.message + extra;
    }
    return JSON.stringify(detail);
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (API_MOCK) return mockRequest<T>(path, init?.method ?? "GET");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        // Never set this for FormData. The browser has to write
        // `multipart/form-data; boundary=…` itself, and the boundary is what
        // tells the server where each part starts — overriding it with
        // application/json left FastAPI unable to see the file at all, so a
        // perfectly good CSV came back as "body.file: Field required".
        ...(init?.body && !(init.body instanceof FormData)
          ? { "content-type": "application/json" }
          : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Is it running? Try \`make dev\`.`,
      0,
    );
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* a non-JSON error body is not itself an error */
    }
    const detail =
      body && typeof body === "object" && "detail" in body
        ? readDetail((body as { detail: unknown }).detail)
        : null;
    throw new ApiError(detail ?? `${response.status} ${response.statusText}`, response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Absolute URL for a download or an EventSource, which cannot use `http`. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
