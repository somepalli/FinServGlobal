"use server";

import {
  queryRegulations,
  screenTransaction,
  screenTransactionDescription,
  type QueryRequest,
  type TransactionPayload,
} from "./api";
import type { QueryState, ScreenState } from "./action-state";

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

export async function assessTransactionDescription(
  _previous: ScreenState,
  formData: FormData,
): Promise<ScreenState> {
  const description = String(formData.get("description") ?? "").trim();
  if (!description) {
    return { result: null, error: "Describe the transaction." };
  }
  try {
    return { result: await screenTransactionDescription({ description }), error: null };
  } catch (error: unknown) {
    return { result: null, error: message(error) };
  }
}
