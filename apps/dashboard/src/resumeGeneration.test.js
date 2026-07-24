import assert from "node:assert/strict";
import test from "node:test";

import {
  canQueueResumeGeneration,
  resumeGenerationRequestOptions,
  resumesUrl,
} from "./resumeGeneration.js";

test("dashboard fetches the available resumes collection", () => {
  assert.equal(resumesUrl, "/api/resumes");
});

test("queueing requires an explicit resume selection", () => {
  const state = {
    selectedJob: { id: "job-1" },
    selectedApproval: { id: "approval-1" },
    hasActiveRequest: false,
    selectedResumeId: "",
  };

  assert.equal(canQueueResumeGeneration(state), false);
  assert.throws(
    () => resumeGenerationRequestOptions(state.selectedResumeId),
    /source resume selection is required/,
  );
});

test("queue request sends only the selected resume id", () => {
  const resumeId = "fb936cab-0161-4780-b69d-bf6bc76a0119";

  assert.equal(canQueueResumeGeneration({
    selectedJob: { id: "job-1" },
    selectedApproval: { id: "approval-1" },
    hasActiveRequest: false,
    selectedResumeId: resumeId,
  }), true);
  assert.deepEqual(resumeGenerationRequestOptions(resumeId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId }),
  });
});
