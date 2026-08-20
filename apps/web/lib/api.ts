import "server-only";

import type { components } from "./api-schema";

export type Answer = components["schemas"]["Answer"];
export type Citation = components["schemas"]["Citation"];
export type ComplianceAssessment = components["schemas"]["ComplianceAssessment"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type TransactionPayload = components["schemas"]["TransactionPayload"];

function endpoint(path: string): string {
  const baseUrl = process.env.API_BASE_URL;
  if (!baseUrl) {
    throw new Error("API_BASE_URL is not configured");
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function post<Response>(path: string, body: unknown): Promise<Response> {
  const response = await fetch(endpoint(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
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
