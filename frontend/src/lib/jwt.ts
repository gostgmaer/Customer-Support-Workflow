/**
 * Decodes a JWT payload WITHOUT verifying its signature. This is safe only
 * because it is used exclusively to drive client-side UI decisions (which
 * nav links to show, which route group to redirect into) - every actual
 * authorization decision is re-checked server-side on every request (see
 * docs/SECURITY.md). Never trust this for anything security-sensitive.
 */
export function decodeJwtPayload<T = Record<string, unknown>>(token: string): T | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json = decodeURIComponent(
      atob(padded)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join("")
    );
    return JSON.parse(json) as T;
  } catch {
    return null;
  }
}

export function isJwtExpired(token: string): boolean {
  const payload = decodeJwtPayload<{ exp?: number }>(token);
  if (!payload?.exp) return false;
  return Date.now() >= payload.exp * 1000;
}
