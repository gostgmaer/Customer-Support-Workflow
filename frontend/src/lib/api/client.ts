import { useAuthStore } from "@/store/auth-store";
import type { ApiErrorBody, ErrorCode } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Thrown for every non-2xx response. Carries the backend's structured
 * error body (see docs/API.md's "Errors" section) rather than a generic
 * message, so callers can branch on `code` (e.g. show a field error for
 * VALIDATION_ERROR, force logout for AUTHENTICATION_ERROR). */
export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.retryable = body.retryable;
    this.details = body.details;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  /** Skip attaching the stored bearer token (login/register/health). */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path, API_BASE_URL);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function handleResponse<T>(response: Response, anonymous: boolean | undefined): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : undefined;

  if (!response.ok) {
    if (response.status === 401 && !anonymous) {
      // The token is gone/expired server-side - drop the local session so
      // the UI reflects reality instead of retrying with a dead token.
      useAuthStore.getState().logout();
    }
    const errorBody: ApiErrorBody = payload ?? {
      code: "UNKNOWN_ERROR",
      message: response.statusText || "Request failed",
      retryable: false,
      severity: "medium",
      details: {},
    };
    throw new ApiError(response.status, errorBody);
  }

  return payload as T;
}

/**
 * The one place that calls `fetch()` in this app (see repository
 * conventions: "components should never call HTTP directly"). Every
 * feature's `api.ts` goes through this.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, anonymous } = options;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!anonymous) {
    const token = useAuthStore.getState().session?.token;
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  return handleResponse<T>(response, anonymous);
}

/**
 * Multipart file upload - deliberately separate from `apiFetch` rather
 * than a `body: FormData` branch there: a `FormData` body must NOT get an
 * explicit `Content-Type` header (the browser sets one itself, including
 * the multipart boundary), whereas `apiFetch` always sends
 * `application/json`. Same auth/error handling as `apiFetch` otherwise.
 */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = useAuthStore.getState().session?.token;
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(buildUrl(path), { method: "POST", headers, body: formData });
  return handleResponse<T>(response, false);
}

function filenameFromContentDisposition(header: string | null): string | undefined {
  const match = header?.match(/filename="?([^"]+)"?/);
  return match?.[1];
}

/**
 * Binary file download (e.g. a KB article's original uploaded file) -
 * separate from `apiFetch` because a successful response here is a raw
 * byte stream, not JSON; an error response is still the usual JSON error
 * body, so that path reuses `handleResponse`.
 */
export async function apiDownload(path: string): Promise<{ blob: Blob; filename?: string }> {
  const headers: Record<string, string> = {};
  const token = useAuthStore.getState().session?.token;
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(buildUrl(path), { headers });
  if (!response.ok) {
    await handleResponse(response, false);
  }
  return {
    blob: await response.blob(),
    filename: filenameFromContentDisposition(response.headers.get("content-disposition")),
  };
}
