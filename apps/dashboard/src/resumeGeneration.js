export const resumesUrl = "/api/resumes";

export function canQueueResumeGeneration({
  selectedJob,
  selectedApproval,
  hasActiveRequest,
  selectedResumeId,
}) {
  return Boolean(
    selectedJob && selectedApproval && !hasActiveRequest && selectedResumeId,
  );
}

export function resumeGenerationRequestOptions(resumeId) {
  if (!resumeId) {
    throw new Error("source resume selection is required");
  }

  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId }),
  };
}
