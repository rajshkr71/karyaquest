CREATE TABLE IF NOT EXISTS resume_generation_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  approval_id UUID NOT NULL REFERENCES resume_generation_approvals(id) ON DELETE CASCADE,
  resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_resume_generation_requests_job_id
  ON resume_generation_requests(job_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_generation_requests_active_job
  ON resume_generation_requests(job_id)
  WHERE status IN ('queued', 'processing');
