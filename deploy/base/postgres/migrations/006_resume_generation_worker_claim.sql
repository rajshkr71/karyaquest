ALTER TABLE resume_generation_requests
  ADD COLUMN IF NOT EXISTS worker_id TEXT,
  ADD COLUMN IF NOT EXISTS claim_token UUID,
  ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

UPDATE resume_generation_requests
SET
  worker_id = COALESCE(worker_id, 'legacy-pre-claim'),
  claim_token = COALESCE(claim_token, gen_random_uuid()),
  attempt_count = CASE
    WHEN attempt_count > 0 THEN attempt_count
    ELSE 1
  END
WHERE status IN ('processing', 'completed', 'failed');

ALTER TABLE resume_generation_requests
  DROP CONSTRAINT IF EXISTS resume_generation_requests_attempt_count_check;

ALTER TABLE resume_generation_requests
  ADD CONSTRAINT resume_generation_requests_attempt_count_check
  CHECK (attempt_count >= 0);

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
      AND worker_id IS NULL
      AND claim_token IS NULL
      AND attempt_count = 0
    )
    OR (
      status = 'processing'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NULL
      AND failed_at IS NULL
      AND failure_reason IS NULL
      AND worker_id IS NOT NULL
      AND btrim(worker_id) <> ''
      AND claim_token IS NOT NULL
      AND attempt_count > 0
    )
    OR (
      status = 'completed'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NOT NULL
      AND failed_at IS NULL
      AND failure_reason IS NULL
      AND worker_id IS NOT NULL
      AND btrim(worker_id) <> ''
      AND claim_token IS NOT NULL
      AND attempt_count > 0
    )
    OR (
      status = 'failed'
      AND processing_started_at IS NOT NULL
      AND completed_at IS NULL
      AND failed_at IS NOT NULL
      AND failure_reason IS NOT NULL
      AND btrim(failure_reason) <> ''
      AND worker_id IS NOT NULL
      AND btrim(worker_id) <> ''
      AND claim_token IS NOT NULL
      AND attempt_count > 0
    )
  );
