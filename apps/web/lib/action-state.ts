import type { Answer, ComplianceAssessment } from "./api";

export type QueryState = { result: Answer | null; error: string | null };
export type ScreenState = {
  result: ComplianceAssessment | null;
  error: string | null;
};

export const initialQueryState: QueryState = { result: null, error: null };
export const initialScreenState: ScreenState = { result: null, error: null };
