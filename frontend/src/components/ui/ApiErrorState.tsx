import { Alert } from "@/components/ui/Alert";
import { ApiError } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/get-error-message";

/**
 * Consistent, HTTP-status-aware error display for a failed page-level
 * data fetch (a useQuery `.isError` state). NOT for form/mutation errors
 * (login, register, create-integration, etc.) - there, the backend's own
 * message ("Invalid username or password") is already the right thing to
 * show as-is via a plain <Alert>, and a 401 there means "wrong
 * credentials," not "your session expired."
 *
 * 401 here always means the session just expired mid-use - apiFetch
 * (lib/api/client.ts) already logs the user out on a 401, which flips
 * AuthGuard's session check and triggers a redirect to login within a
 * render or two, so this shows a calm "redirecting" message rather than
 * a scary error for what's about to self-resolve.
 */
export function ApiErrorState({ error }: { error: unknown }) {
  const status = error instanceof ApiError ? error.status : undefined;

  if (status === 401) {
    return (
      <Alert variant="info" title="Your session has expired">
        Redirecting you to sign in again…
      </Alert>
    );
  }

  if (status === 403) {
    return (
      <Alert variant="error" title="You don't have permission to view this">
        {getErrorMessage(error)}
      </Alert>
    );
  }

  if (status === 429) {
    return (
      <Alert variant="error" title="Too many requests">
        Please wait a moment and try again.
      </Alert>
    );
  }

  if (status !== undefined && status >= 500) {
    return (
      <Alert variant="error" title="Something went wrong on our end">
        Please try again in a moment. If this keeps happening, contact support.
      </Alert>
    );
  }

  return <Alert variant="error">{getErrorMessage(error)}</Alert>;
}
