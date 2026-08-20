"use client";

import { useFormStatus } from "react-dom";

export function SubmitButton({ idle, pending }: { idle: string; pending: string }) {
  const status = useFormStatus();
  return (
    <button type="submit" disabled={status.pending}>
      {status.pending ? pending : idle}
    </button>
  );
}
