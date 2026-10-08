import type { ExtractApiError } from "../extract/api";
import type { ErrorDescription, ExtractStage } from "../extract/describe-error";

/** Plain-language title and explanation for an error on the Discover page. */
export function describeDiscoverError(
  error: ExtractApiError,
  stage: ExtractStage,
  apiUrl: string,
): ErrorDescription {
  switch (error.kind) {
    case "network":
      return stage === "poll"
        ? {
            title: "Lost contact with the server",
            message: `${apiUrl} stopped answering. The search may still be running there, so trying again checks on it rather than starting over.`,
          }
        : {
            title: "Couldn't reach the server",
            message: `Nothing answered at ${apiUrl}. Check that PolymerData is running (double-click PolymerData to start it, or run ./start.sh), and that this page is open at a localhost address.`,
          };
    case "bad-response":
      return {
        title: "The server's answer couldn't be read",
        message: `Something answered at ${apiUrl}, but not the way the extraction server does. Check that VITE_EXTRACT_API_URL points at it.`,
        detail: error.message,
      };
    case "rejected":
      return { title: "The server couldn't start this search", message: error.message };
    case "job-lost":
      return {
        title: "The server lost this search",
        message: "It forgets its searches when it restarts, so this one has to start again.",
      };
    case "http":
      return {
        title: "The server ran into a problem",
        message: `It answered with an error (HTTP ${error.status ?? "unknown"}).`,
        detail: error.message === `HTTP ${error.status}` ? undefined : error.message,
      };
    case "failed":
      return {
        title: "The search failed",
        message: "Its reason:",
        detail: error.message,
      };
  }
}
