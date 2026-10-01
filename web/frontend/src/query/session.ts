import { fetchNewsAuto, fetchPending, fetchStatus } from "../api";
import type { NewsAutoStatus, StatusResponse } from "../types";
import { queryKeys } from "./keys";

export type SessionSnapshot = {
  status: StatusResponse;
  pending: unknown;
};

export async function fetchSessionSnapshot(): Promise<SessionSnapshot> {
  const [status, pend] = await Promise.all([fetchStatus(), fetchPending()]);
  return {
    status,
    pending: pend.pending ?? null,
  };
}

export { fetchNewsAuto, queryKeys };
export type { NewsAutoStatus };
