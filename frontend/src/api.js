const configuredApiBase = import.meta.env.VITE_API_BASE?.trim();
if (import.meta.env.PROD && !configuredApiBase) {
  throw new Error("VITE_API_BASE must be configured for production builds.");
}
const API = configuredApiBase || "http://localhost:5000";
let csrfToken = null;

export class ApiError extends Error {
  constructor(message, status, data = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  let body = options.body;
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    if (!csrfToken) {
      const csrf = await fetch(`${API}/auth/csrf`, { credentials: "include" });
      const tokenData = await csrf.json();
      if (!csrf.ok || !tokenData.csrf_token) throw new ApiError("Could not establish a secure session.", csrf.status);
      csrfToken = tokenData.csrf_token;
    }
    headers.set("X-CSRF-Token", csrfToken);
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    }
  }
  const response = await fetch(`${API}${path}`, { ...options, method, headers, body, credentials: "include" });
  const data = await response.json().catch(() => ({}));
  if (data.csrf_token) csrfToken = data.csrf_token;
  if (!response.ok) throw new ApiError(data.error || `Request failed (${response.status}).`, response.status, data);
  return data;
}

export async function refreshCsrf() {
  const response = await fetch(`${API}/auth/csrf`, { credentials: "include" });
  const data = await response.json();
  if (!response.ok || !data.csrf_token) throw new ApiError("Could not establish a secure session.", response.status);
  csrfToken = data.csrf_token;
  return csrfToken;
}
