import type { ExtractApiError } from "./api";

/** Which call failed: starting the job, or checking on it. */
export type ExtractStage = "submit" | "poll";

/**
 * What "Try again" does. `resume` checks on the same job again — it may
 * still be running on the server, and starting another would only queue
 * behind it. `resubmit` starts a new job with the same file and features.
 * `null` offers no retry: the server refused the input itself.
 */
export type RetryAction = "resume" | "resubmit" | null;

export function retryActionFor(error: ExtractApiError, stage: ExtractStage): RetryAction {
  switch (error.kind) {
    case "rejected":
      return null;
    case "job-lost":
    case "failed":
      return "resubmit";
    case "network":
    case "bad-response":
    case "http":
      return stage === "poll" ? "resume" : "resubmit";
  }
}

export interface ErrorDescription {
  readonly title: string;
  readonly message: string;
  /** Technical text worth showing as-is, e.g. the server's own reason. */
  readonly detail?: string;
}

/** Plain-language title and explanation for an error on the Extract page. */
export function describeExtractError(
  error: ExtractApiError,
  stage: ExtractStage,
  apiUrl: string,
): ErrorDescription {
  switch (error.kind) {
    case "network":
      return stage === "poll"
        ? {
            title: "Lost contact with the extraction server",
            message: `${apiUrl} stopped answering. The extraction may still be running there, so trying again checks on it rather than starting over.`,
          }
        : {
            title: "Couldn't reach the extraction server",
            message: `Nothing answered at ${apiUrl}. Check that PolymerData is running (double-click PolymerData to start it, or run ./start.sh), and that this page is open at a localhost address — the server only answers pages served from this computer.`,
          };
    case "bad-response":
      return {
        title: "The server's answer couldn't be read",
        message: `Something answered at ${apiUrl}, but not the way the extraction server does. Check that VITE_EXTRACT_API_URL points at it.`,
        detail: error.message,
      };
    case "rejected":
      return { title: "The server couldn't start this extraction", message: error.message };
    case "job-lost":
      return {
        title: "The server lost this extraction",
        message:
          "It has no extraction with this id. One still running when the server stopped is lost, and has to start again from the beginning.",
      };
    case "http":
      return {
        title: "The extraction server ran into a problem",
        message: `It answered with an error (HTTP ${error.status ?? "unknown"}).`,
        detail: error.message === `HTTP ${error.status}` ? undefined : error.message,
      };
    case "failed":
      return {
        title: "The extraction failed",
        message: "The server couldn't get data out of this paper. Its reason:",
        detail: error.message,
      };
  }
}
