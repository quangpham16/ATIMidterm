export const API_URL = (import.meta.env?.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const TOKEN_KEY = "case_foundry_token";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(payload) {
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((issue) => {
      const field = issue.loc?.at(-1);
      const message = issue.msg?.replace(/^Value error, /, "") || "Invalid value";
      return field ? `${field.charAt(0).toUpperCase()}${field.slice(1)}: ${message}` : message;
    }).join(". ");
  }
  return "Something went wrong. Please try again.";
}

export async function request(path, options = {}, token) {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Unable to connect to the server. Check your connection and try again.", 0);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorMessage(payload || {}), response.status);
  if (payload === null) throw new ApiError("The server returned an invalid response. Please try again.", response.status);
  return payload;
}
