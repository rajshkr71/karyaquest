import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  const [jobs, setJobs] = useState([]);
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
        setJobs(Array.isArray(data) ? data : data.items ?? []);
        setStatus("");
      })
      .catch((error) => {
        setStatus(`Unable to load jobs: ${error.message}`);
      });
  }, []);

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">KaryaQuest</p>
        <h1>Job Review Dashboard</h1>
        <p>Review imported jobs before resume generation or application automation.</p>
      </section>

      {status && <div className="status">{status}</div>}

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
                <tr key={job.id}>
                  <td>
                    <a href={job.source_url} target="_blank" rel="noreferrer">
                      {job.title}
                    </a>
                  </td>
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
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
