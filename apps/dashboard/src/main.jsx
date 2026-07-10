import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function latestScoresByJob(scores) {
  return scores.reduce((latest, score) => {
    const existing = latest[score.job_id];
    const scoreCreatedAt = new Date(score.created_at).getTime();
    const existingCreatedAt = existing ? new Date(existing.created_at).getTime() : 0;

    if (!existing || scoreCreatedAt > existingCreatedAt) {
      latest[score.job_id] = score;
    }

    return latest;
  }, {});
}

function formatScore(score) {
  if (!score) {
    return "Not scored";
  }
  return `${score.score}/100`;
}

function formatRecommendation(score) {
  return score?.recommendation?.replaceAll("_", " ") ?? "None yet";
}

function approvalsByJob(approvalRecords) {
  return approvalRecords.reduce((approvals, approval) => {
    approvals[approval.job_id] = approval;
    return approvals;
  }, {});
}

function requestsByJob(requestRecords) {
  return requestRecords.reduce((requests, request) => {
    const existing = requests[request.job_id];
    const requestCreatedAt = new Date(request.created_at).getTime();
    const existingCreatedAt = existing ? new Date(existing.created_at).getTime() : 0;

    if (!existing || requestCreatedAt > existingCreatedAt) {
      requests[request.job_id] = request;
    }

    return requests;
  }, {});
}

function formatTimestamp(value) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function ScoreList({ title, items }) {
  return (
    <div>
      <h4>{title}</h4>
      {items?.length ? (
        <ul className="scoreList">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">None recorded.</p>
      )}
    </div>
  );
}

function App() {
  const [jobs, setJobs] = useState([]);
  const [scoresByJob, setScoresByJob] = useState({});
  const [approvals, setApprovals] = useState({});
  const [requests, setRequests] = useState({});
  const [selectedJobId, setSelectedJobId] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [recommendationFilter, setRecommendationFilter] = useState("All");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [approvingJobId, setApprovingJobId] = useState("");
  const [requestingJobId, setRequestingJobId] = useState("");

  useEffect(() => {
    const fetchJson = (url) =>
      fetch(url).then((response) => {
        if (!response.ok) {
          throw new Error(`${url} returned ${response.status}`);
        }
        return response.json();
      });

    setIsLoading(true);
    setErrorMessage("");

    Promise.all([
      fetchJson("/api/jobs"),
      fetchJson("/api/job-scores"),
      fetchJson("/api/resume-generation-approvals"),
      fetchJson("/api/resume-generation-requests"),
    ])
      .then(([jobsData, scoresData, approvalsData, requestsData]) => {
        const items = Array.isArray(jobsData) ? jobsData : jobsData.items ?? [];
        const scores = Array.isArray(scoresData) ? scoresData : scoresData.items ?? [];
        const approvalRecords = Array.isArray(approvalsData)
          ? approvalsData
          : approvalsData.items ?? [];
        const requestRecords = Array.isArray(requestsData)
          ? requestsData
          : requestsData.items ?? [];
        setJobs(items);
        setScoresByJob(latestScoresByJob(scores));
        setApprovals(approvalsByJob(approvalRecords));
        setRequests(requestsByJob(requestRecords));
        setSelectedJobId(items[0]?.id ?? "");
      })
      .catch((error) => {
        setErrorMessage(`Unable to load dashboard data: ${error.message}`);
        setJobs([]);
        setScoresByJob({});
        setApprovals({});
        setRequests({});
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const statusOptions = [
    "All",
    ...Array.from(new Set(jobs.map((job) => job.status).filter(Boolean))).sort(),
  ];
  const recommendationOptions = [
    "All",
    "prepare_application",
    "reject",
    "None yet",
  ];
  const visibleJobs = jobs.filter(
    (job) => {
      const score = scoresByJob[job.id];
      const recommendation = score?.recommendation ?? "None yet";
      const statusMatches = statusFilter === "All" || job.status === statusFilter;
      const recommendationMatches =
        recommendationFilter === "All" || recommendation === recommendationFilter;

      return statusMatches && recommendationMatches;
    },
  );

  useEffect(() => {
    if (
      visibleJobs.length > 0
      && !visibleJobs.some((job) => job.id === selectedJobId)
    ) {
      setSelectedJobId(visibleJobs[0].id);
    }
    if (visibleJobs.length === 0 && selectedJobId) {
      setSelectedJobId("");
    }
  }, [selectedJobId, visibleJobs]);

  const selectedJob = visibleJobs.find((job) => job.id === selectedJobId) ?? null;
  const selectedScore = selectedJob ? scoresByJob[selectedJob.id] : null;
  const selectedApproval = selectedJob ? approvals[selectedJob.id] : null;
  const selectedRequest = selectedJob ? requests[selectedJob.id] : null;
  const selectedApprovalState = selectedApproval ? "approved" : "not_requested";
  const selectedRequestState = selectedRequest?.status ?? "not_requested";
  const hasActiveRequest =
    selectedRequest && ["queued", "processing"].includes(selectedRequest.status);
  const canRequestResumeApproval =
    selectedJob
    && selectedScore?.recommendation === "prepare_application"
    && !selectedApproval;
  const canQueueResumeRequest = selectedJob && selectedApproval && !hasActiveRequest;

  function requestResumeGenerationApproval(jobId) {
    setActionMessage("");
    setApprovingJobId(jobId);
    fetch(`/api/jobs/${jobId}/resume-generation-approval`, { method: "POST" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`approval request returned ${response.status}`);
        }
        return response.json();
      })
      .then((approval) => {
        setApprovals((current) => ({
          ...current,
          [approval.job_id]: approval,
        }));
        setActionMessage("Resume generation approval recorded.");
      })
      .catch((error) => {
        setActionMessage(`Unable to request approval: ${error.message}`);
      })
      .finally(() => {
        setApprovingJobId("");
      });
  }

  function createResumeGenerationRequest(jobId) {
    setActionMessage("");
    setRequestingJobId(jobId);
    fetch(`/api/jobs/${jobId}/resume-generation-requests`, { method: "POST" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`request creation returned ${response.status}`);
        }
        return response.json();
      })
      .then((request) => {
        setRequests((current) => ({
          ...current,
          [request.job_id]: request,
        }));
        setActionMessage("Resume generation request queued.");
      })
      .catch((error) => {
        setActionMessage(`Unable to queue request: ${error.message}`);
      })
      .finally(() => {
        setRequestingJobId("");
      });
  }

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">KaryaQuest</p>
        <h1>Job Review Dashboard</h1>
        <p>Review imported jobs before resume generation or application automation.</p>
      </section>

      {isLoading && <div className="status">Loading jobs and scores...</div>}
      {errorMessage && <div className="status error">{errorMessage}</div>}
      {actionMessage && <div className="status">{actionMessage}</div>}

      <div className="layout">
        <section className="card">
          <div className="cardHeader">
            <h2>Jobs</h2>
            <span>{visibleJobs.length} shown / {jobs.length} total</span>
          </div>

          <div className="filterBar">
            <div className="filterControl">
              <label htmlFor="status-filter">Status</label>
              <select
                id="status-filter"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
              >
                {statusOptions.map((statusOption) => (
                  <option key={statusOption} value={statusOption}>
                    {statusOption}
                  </option>
                ))}
              </select>
            </div>

            <div className="filterControl">
              <label htmlFor="recommendation-filter">Recommendation</label>
              <select
                id="recommendation-filter"
                value={recommendationFilter}
                onChange={(event) => setRecommendationFilter(event.target.value)}
              >
                {recommendationOptions.map((recommendationOption) => (
                  <option key={recommendationOption} value={recommendationOption}>
                    {recommendationOption}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="tableWrap">
            <table className="jobsTable">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Location</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Score</th>
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {visibleJobs.map((job) => {
                  const score = scoresByJob[job.id];
                  return (
                    <tr
                      key={job.id}
                      className={job.id === selectedJobId ? "selectedRow" : "clickableRow"}
                      onClick={() => setSelectedJobId(job.id)}
                      tabIndex="0"
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          setSelectedJobId(job.id);
                        }
                      }}
                    >
                      <td>{job.title}</td>
                      <td>{job.company}</td>
                      <td>{job.location || "Not specified"}</td>
                      <td><span className="pill">{job.status}</span></td>
                      <td>{job.source}</td>
                      <td>{formatScore(score)}</td>
                      <td>{formatRecommendation(score)}</td>
                    </tr>
                  );
                })}
                {jobs.length === 0 && !isLoading && !errorMessage && (
                  <tr>
                    <td colSpan="7" className="empty">No jobs found.</td>
                  </tr>
                )}
                {jobs.length > 0 && visibleJobs.length === 0 && !isLoading && !errorMessage && (
                  <tr>
                    <td colSpan="7" className="empty">No jobs match these filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="card detailPanel">
          <div className="cardHeader">
            <h2>Job Detail</h2>
          </div>

          {selectedJob ? (
            <div className="detailBody">
              <h3>{selectedJob.title}</h3>
              <dl className="metaGrid">
                <div>
                  <dt>Company</dt>
                  <dd>{selectedJob.company}</dd>
                </div>
                <div>
                  <dt>Location</dt>
                  <dd>{selectedJob.location || "Not specified"}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd><span className="pill">{selectedJob.status}</span></dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>{selectedJob.source}</dd>
                </div>
                <div>
                  <dt>Score</dt>
                  <dd>{formatScore(selectedScore)}</dd>
                </div>
                <div>
                  <dt>Recommendation</dt>
                  <dd>{formatRecommendation(selectedScore)}</dd>
                </div>
                <div>
                  <dt>Resume approval</dt>
                  <dd>{selectedApprovalState}</dd>
                </div>
                <div>
                  <dt>Resume request</dt>
                  <dd>{selectedRequestState}</dd>
                </div>
                {selectedRequest && (
                  <>
                    <div>
                      <dt>Processing started</dt>
                      <dd>{formatTimestamp(selectedRequest.processing_started_at)}</dd>
                    </div>
                    <div>
                      <dt>Completed</dt>
                      <dd>{formatTimestamp(selectedRequest.completed_at)}</dd>
                    </div>
                    <div>
                      <dt>Failed</dt>
                      <dd>{formatTimestamp(selectedRequest.failed_at)}</dd>
                    </div>
                    {selectedRequest.failure_reason && (
                      <div>
                        <dt>Failure reason</dt>
                        <dd>{selectedRequest.failure_reason}</dd>
                      </div>
                    )}
                  </>
                )}
              </dl>

              {canRequestResumeApproval && (
                <button
                  className="primaryAction"
                  type="button"
                  disabled={approvingJobId === selectedJob.id}
                  onClick={() => requestResumeGenerationApproval(selectedJob.id)}
                >
                  {approvingJobId === selectedJob.id
                    ? "Requesting approval..."
                    : "Approve resume generation"}
                </button>
              )}

              {canQueueResumeRequest && (
                <button
                  className="primaryAction"
                  type="button"
                  disabled={requestingJobId === selectedJob.id}
                  onClick={() => createResumeGenerationRequest(selectedJob.id)}
                >
                  {requestingJobId === selectedJob.id
                    ? "Queueing request..."
                    : "Queue resume generation"}
                </button>
              )}

              <a className="sourceLink" href={selectedJob.source_url} target="_blank" rel="noreferrer">
                Open source posting
              </a>

              <section className="scoreDetail">
                <ScoreList title="Strengths" items={selectedScore?.strengths} />
                <ScoreList title="Gaps" items={selectedScore?.gaps} />
              </section>

              <h4>Description</h4>
              <p className="description">{selectedJob.description || "No description available."}</p>
            </div>
          ) : (
            <div className="detailBody empty">Select a job to view details.</div>
          )}
        </aside>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
