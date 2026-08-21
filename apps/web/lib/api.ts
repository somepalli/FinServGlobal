import "server-only";

import type { components } from "./api-schema";

export type Answer = components["schemas"]["Answer"];
export type Citation = components["schemas"]["Citation"];
export type ComplianceAssessment = components["schemas"]["ComplianceAssessment"];
export type PostureReport = components["schemas"]["PostureReport"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type TransactionPayload = components["schemas"]["TransactionPayload"];

class ApiUnavailableError extends Error {}

function endpoint(path: string): string {
  const baseUrl = process.env.API_BASE_URL;
  if (!baseUrl) {
    throw new Error("API_BASE_URL is not configured");
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function post<Response>(path: string, body: unknown): Promise<Response> {
  let response: globalThis.Response;
  try {
    response = await fetch(endpoint(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    throw new Error(`API request failed (${response.status})`);
  }
  return (await response.json()) as Response;
}

async function get<Response>(path: string): Promise<Response> {
  let response: globalThis.Response;
  try {
    response = await fetch(endpoint(path), { cache: "no-store" });
  } catch (error: unknown) {
    throw new ApiUnavailableError(
      "Compliance API is unavailable. Start its local services and retry.",
      { cause: error },
    );
  }
  if (!response.ok) {
    throw new Error(`API request failed (${response.status})`);
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

export function getPostureReport(start?: string, end?: string): Promise<PostureReport> {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const query = params.size ? `?${params.toString()}` : "";
  return get<PostureReport>(`/reports/posture${query}`);
}
