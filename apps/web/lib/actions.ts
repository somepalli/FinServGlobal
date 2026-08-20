"use server";

import {
  queryRegulations,
  screenTransaction,
  type Answer,
  type ComplianceAssessment,
  type QueryRequest,
  type TransactionPayload,
} from "./api";

export type QueryState = { result: Answer | null; error: string | null };
export type ScreenState = {
  result: ComplianceAssessment | null;
  error: string | null;
};

export const initialQueryState: QueryState = { result: null, error: null };
export const initialScreenState: ScreenState = { result: null, error: null };

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed";
}

export async function askQuestion(
  _previous: QueryState,
  formData: FormData,
): Promise<QueryState> {
  const question = String(formData.get("question") ?? "").trim();
  const asOf = String(formData.get("as_of") ?? "").trim();
  if (!question) {
    return { result: null, error: "Enter a regulatory question." };
  }
  const request: QueryRequest = { question, ...(asOf ? { as_of: asOf } : {}) };
  try {
    return { result: await queryRegulations(request), error: null };
  } catch (error: unknown) {
    return { result: null, error: message(error) };
  }
}

function transactionFrom(raw: string): TransactionPayload {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Transaction JSON must be an object.");
  }
  const transaction = value as Record<string, unknown>;
  if (typeof transaction.txn_id !== "string" || !transaction.txn_id.trim()) {
    throw new Error("Transaction JSON must include a non-empty txn_id.");
  }
  return transaction as TransactionPayload;
}

export async function assessTransaction(
  _previous: ScreenState,
  formData: FormData,
): Promise<ScreenState> {
  try {
    const request = transactionFrom(String(formData.get("transaction") ?? ""));
    return { result: await screenTransaction(request), error: null };
  } catch (error: unknown) {
    return { result: null, error: message(error) };
  }
}
