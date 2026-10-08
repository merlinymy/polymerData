import { describe, expect, it } from "vitest";
import { ExtractApiError, type ExtractApiErrorKind } from "./api";
import { describeExtractError, retryActionFor, type RetryAction } from "./describe-error";

const API = "http://127.0.0.1:8000";
const error = (kind: ExtractApiErrorKind, message = "reason", status?: number) =>
  new ExtractApiError(kind, message, status);

describe("retryActionFor", () => {
  const cases: [ExtractApiErrorKind, RetryAction, RetryAction][] = [
    // kind          after submit   after poll
    ["network", "resubmit", "resume"],
    ["bad-response", "resubmit", "resume"],
    ["http", "resubmit", "resume"],
    ["job-lost", "resubmit", "resubmit"],
    ["failed", "resubmit", "resubmit"],
    ["rejected", null, null],
  ];

  it.each(cases)("%s: %s after submitting, %s while checking", (kind, afterSubmit, afterPoll) => {
    expect(retryActionFor(error(kind), "submit")).toBe(afterSubmit);
    expect(retryActionFor(error(kind), "poll")).toBe(afterPoll);
  });
});

describe("describeExtractError", () => {
  it("says where it looked and what to check when nothing answers", () => {
    const { title, message } = describeExtractError(error("network"), "submit", API);
    expect(title).toBe("Couldn't reach the extraction server");
    expect(message).toContain(API);
    expect(message).toContain("double-click PolymerData");
    expect(message).toContain("localhost");
  });

  it("says the job may still be running when contact is lost mid-extraction", () => {
    const { title, message } = describeExtractError(error("network"), "poll", API);
    expect(title).toBe("Lost contact with the extraction server");
    expect(message).toContain("may still be running");
  });

  it("shows the server's own reason for refusing the input", () => {
    const { title, message } = describeExtractError(
      error("rejected", "Give at least one feature name.", 400),
      "submit",
      API,
    );
    expect(title).toBe("The server couldn't start this extraction");
    expect(message).toBe("Give at least one feature name.");
  });

  it("explains a lost job as one the server doesn't have, or was running when it stopped", () => {
    const { title, message } = describeExtractError(error("job-lost"), "poll", API);
    expect(title).toBe("The server lost this extraction");
    expect(message).toContain("no extraction with this id");
    expect(message).toContain("still running when the server stopped");
  });

  it("passes a failed job's reason through as detail", () => {
    const described = describeExtractError(
      error("failed", "claude: usage limit reached"),
      "poll",
      API,
    );
    expect(described.title).toBe("The extraction failed");
    expect(described.detail).toBe("claude: usage limit reached");
  });

  it("names the status of an error answer, adding the server's detail only when it has one", () => {
    expect(describeExtractError(error("http", "HTTP 502", 502), "submit", API)).toEqual({
      title: "The extraction server ran into a problem",
      message: "It answered with an error (HTTP 502).",
      detail: undefined,
    });
    expect(describeExtractError(error("http", "Something broke", 500), "poll", API).detail).toBe(
      "Something broke",
    );
  });

  it("points at the configured URL when the answer isn't the extraction server's", () => {
    const described = describeExtractError(error("bad-response", "Got HTML"), "submit", API);
    expect(described.message).toContain("VITE_EXTRACT_API_URL");
    expect(described.detail).toBe("Got HTML");
  });
});
