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
  const [selectedJobId, setSelectedJobId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

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

    Promise.all([fetchJson("/api/jobs"), fetchJson("/api/job-scores")])
      .then(([jobsData, scoresData]) => {
        const items = Array.isArray(jobsData) ? jobsData : jobsData.items ?? [];
        const scores = Array.isArray(scoresData) ? scoresData : scoresData.items ?? [];
        setJobs(items);
        setScoresByJob(latestScoresByJob(scores));
        setSelectedJobId(items[0]?.id ?? "");
      })
      .catch((error) => {
        setErrorMessage(`Unable to load dashboard data: ${error.message}`);
        setJobs([]);
        setScoresByJob({});
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? null;
  const selectedScore = selectedJob ? scoresByJob[selectedJob.id] : null;

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">KaryaQuest</p>
        <h1>Job Review Dashboard</h1>
        <p>Review imported jobs before resume generation or application automation.</p>
      </section>

      {isLoading && <div className="status">Loading jobs and scores...</div>}
      {errorMessage && <div className="status error">{errorMessage}</div>}

      <div className="layout">
        <section className="card">
          <div className="cardHeader">
            <h2>Jobs</h2>
            <span>{jobs.length} total</span>
          </div>

          <div className="tableWrap">
            <table>
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
                {jobs.map((job) => {
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
              </dl>

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
