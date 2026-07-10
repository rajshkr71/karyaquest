ALTER TABLE resume_generation_requests
  ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ;

ALTER TABLE resume_generation_requests
  DROP CONSTRAINT IF EXISTS resume_generation_requests_lifecycle_check;

ALTER TABLE resume_generation_requests
  ADD CONSTRAINT resume_generation_requests_lifecycle_check CHECK (
    (
      status = 'queued'
      AND processing_started_at IS NULL
      AND completed_at IS NULL
      AND failed_at IS NULL
      AND failure_reason IS NULL
    )
    OR (
      status = 'processing'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NULL
      AND failed_at IS NULL
      AND failure_reason IS NULL
    )
    OR (
      status = 'completed'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NOT NULL
      AND failed_at IS NULL
      AND failure_reason IS NULL
    )
    OR (
      status = 'failed'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NULL
      AND failed_at IS NOT NULL
      AND failure_reason IS NOT NULL
      AND btrim(failure_reason) <> ''
    )
  );
