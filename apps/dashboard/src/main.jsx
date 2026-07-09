import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [status, setStatus] = useState("Loading jobs...");

  useEffect(() => {
    fetch("/api/jobs")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`API returned ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        const items = Array.isArray(data) ? data : data.items ?? [];
        setJobs(items);
        setSelectedJobId(items[0]?.id ?? "");
        setStatus("");
      })
      .catch((error) => {
        setStatus(`Unable to load jobs: ${error.message}`);
      });
  }, []);

  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? null;

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">KaryaQuest</p>
        <h1>Job Review Dashboard</h1>
        <p>Review imported jobs before resume generation or application automation.</p>
      </section>

      {status && <div className="status">{status}</div>}

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
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
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
                  </tr>
                ))}
                {jobs.length === 0 && !status && (
                  <tr>
                    <td colSpan="5" className="empty">No jobs found.</td>
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
              </dl>

              <a className="sourceLink" href={selectedJob.source_url} target="_blank" rel="noreferrer">
                Open source posting
              </a>

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
