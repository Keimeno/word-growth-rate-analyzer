/**
 * How the generated client (src/api/generated/) fetches: same origin, JSON, errors as the
 * API words them ({"error": "…"}). Basic auth rides along with the browser's credentials.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(url, { ...init, headers });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      body !== null && typeof body === "object" && "error" in body && typeof body.error === "string"
        ? body.error
        : response.statusText;
    throw new ApiError(response.status, message);
  }
  // the body is what the schema says: the API's models and these types come from one source
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion
  return body as T;
}

/** What a generated hook fails with, whatever the schema calls the error's body. */
export type ErrorType<_Body> = ApiError;
