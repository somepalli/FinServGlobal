import "server-only";

import type { components } from "./api-schema";

export type Answer = components["schemas"]["Answer"];
export type Citation = components["schemas"]["Citation"];
export type ComplianceAssessment = components["schemas"]["ComplianceAssessment"];
export type PostureReport = components["schemas"]["PostureReport"];
export type QueryRequest = components["schemas"]["QueryRequest"];
// TransactionPayload has a Decimal field, so FastAPI emits separate
// validation/serialization schemas. This app only ever sends the payload
// (never receives one back), so the input variant is the correct shape.
export type TransactionPayload = components["schemas"]["TransactionPayload-Input"];
export type TransactionDescriptionRequest =
  components["schemas"]["TransactionDescriptionRequest"];

class ApiUnavailableError extends Error {}

function endpoint(path: string): string {
  const baseUrl = process.env.API_BASE_URL;
  if (!baseUrl) {
    throw new Error("API_BASE_URL is not configured");
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function authHeaders(): Record<string, string> {
  const apiKey = process.env.COMPLIANCE_API_KEY;
  if (!apiKey) {
    throw new Error("COMPLIANCE_API_KEY is not configured");
  }
  return { "X-API-Key": apiKey };
}

async function errorMessage(response: globalThis.Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string") {
      return (body as { detail: string }).detail;
    }
  } catch {
    // Response body was not JSON; fall through to the generic message.
  }
  return `API request failed (${response.status})`;
}

async function post<Response>(path: string, body: unknown): Promise<Response> {
  let response: globalThis.Response;
  try {
    response = await fetch(endpoint(path), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (error: unknown) {
    throw new ApiUnavailableError(
      "Compliance API is unavailable. Start its local services and retry.",
      { cause: error },
    );
  }
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as Response;
}

async function get<Response>(path: string): Promise<Response> {
  let response: globalThis.Response;
  try {
    response = await fetch(endpoint(path), { headers: authHeaders(), cache: "no-store" });
  } catch (error: unknown) {
    throw new ApiUnavailableError(
      "Compliance API is unavailable. Start its local services and retry.",
      { cause: error },
    );
  }
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as Response;
}

export function queryRegulations(request: QueryRequest): Promise<Answer> {
  return post<Answer>("/query", request);
}

export function screenTransaction(
  request: TransactionPayload,
): Promise<ComplianceAssessment> {
  return post<ComplianceAssessment>("/screen", request);
}

export function screenTransactionDescription(
  request: TransactionDescriptionRequest,
): Promise<ComplianceAssessment> {
  return post<ComplianceAssessment>("/screen/from-description", request);
}

export function getPostureReport(start?: string, end?: string): Promise<PostureReport> {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const query = params.size ? `?${params.toString()}` : "";
  return get<PostureReport>(`/reports/posture${query}`);
}
