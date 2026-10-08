import { useEffect, useState, type SVGProps } from "react";
import { Button, Card, cn } from "@/components/ui";
import type { JobProgress } from "./api";
import { formatElapsed } from "./format";

export interface ExtractProgressProps {
  fileName: string;
  features: readonly string[];
  /** When the extraction was started, for the elapsed-time readout. For a
   *  job reopened from the address, the server's record of when it started. */
  startedAt: number;
  /** The step the server last reported. Absent while the PDF is still being
   *  sent, before the first status answer, or from a server that doesn't
   *  report steps: the bar then shows activity without an amount. */
  progress?: JobProgress;
  onNewExtraction: () => void;
}

/** Said when no step has been reported. */
const FALLBACK_NAME = "Working on it";
const FALLBACK_DESCRIPTION =
  "A paper the server has seen before takes about 30 seconds to 2 minutes; a new one about 5 minutes, because it's parsed first. The server runs one job at a time, so this also covers any wait for earlier ones.";

/** The current time, refreshed every `intervalMs` while mounted. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Shown while a job is starting and running: a progress bar, and the step
 * the server says the job is on, with a sentence about it. Only the step's
 * name is a live region, so a screen reader hears each step once as it
 * starts — not the elapsed time ticking, nor the same step every 3 seconds.
 */
export function ExtractProgress({
  fileName,
  features,
  startedAt,
  progress,
  onNewExtraction,
}: ExtractProgressProps) {
  const now = useNow(1000);

  return (
    <Card className="max-w-2xl">
      <div className="flex flex-col gap-5 p-4 sm:p-6">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="font-medium text-primary">Extracting data… this may take a few minutes</p>
            <p className="tabular text-sm text-muted">{formatElapsed(now - startedAt)} elapsed</p>
          </div>
          {/* Empty for a job reopened from the address until the server's
              first answer names it, a moment later. */}
          {fileName ? (
            <p className="break-words text-sm text-secondary">
              <span className="break-all text-primary">{fileName}</span> · {features.join(", ")}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-3">
          <ProgressBar progress={progress} />
          <div className="flex items-start gap-2.5">
            <Spinner className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <p role="status" className="text-sm font-medium text-primary">
                {progress?.name ?? FALLBACK_NAME}
              </p>
              <p className="text-sm text-secondary">
                {progress ? progress.description : FALLBACK_DESCRIPTION}
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-col-reverse gap-3 border-t border-subtle pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted">
            Starting over doesn't stop this job on the server, and a new one waits for it to finish.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={onNewExtraction}
            className="self-start sm:self-auto"
          >
            New extraction
          </Button>
        </div>
      </div>
    </Card>
  );
}

/**
 * The job's percent complete. It moves only at step boundaries — the server
 * can't see inside a MinerU parse or a model call — so the width eases from
 * one to the next. With no step reported yet it pulses instead: activity,
 * not an invented amount.
 */
function ProgressBar({ progress }: { progress?: JobProgress }) {
  const percent = progress ? Math.round(progress.percent) : undefined;
  return (
    <div className="flex items-center gap-3">
      <div
        role="progressbar"
        aria-label="Extraction progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={progress ? `${progress.name}, ${percent}%` : undefined}
        className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
      >
        {percent === undefined ? (
          <div className="h-full w-full rounded-full bg-accent/40 motion-safe:animate-pulse" />
        ) : (
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-700 ease-out motion-reduce:transition-none"
            style={{ width: `${percent}%` }}
          />
        )}
      </div>
      <span aria-hidden="true" className="tabular w-10 text-right text-sm text-secondary">
        {percent === undefined ? "" : `${percent}%`}
      </span>
    </div>
  );
}

export function Spinner({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("motion-safe:animate-spin", className)}
      {...props}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity={0.25} strokeWidth={3} />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth={3} strokeLinecap="round" />
    </svg>
  );
}
