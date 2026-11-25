export type ApiError = { error?: { code?: string; message?: string } };

function csrfToken() {
  if (typeof document === "undefined") return "";
  const token = document.cookie.split("; ").find((item) => item.startsWith("csrf_access_token="));
  return token ? decodeURIComponent(token.split("=").slice(1).join("=")) : "";
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isForm && options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes((options.method || "GET").toUpperCase())) {
    const csrf = csrfToken();
    if (csrf) headers.set("X-CSRF-TOKEN", csrf);
  }
  const response = await fetch(path, { ...options, headers, credentials: "include", cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((body as ApiError).error?.message || "We could not complete that request.");
  return body as T;
}
