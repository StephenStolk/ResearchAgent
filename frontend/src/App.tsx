import { useState } from "react";
import "./App.css";
import type { ResearchStatus, ResearchPacket } from "./types/status.ts";
import { ChartsSection } from "./components/ChartsSection.tsx";
import { InsightsSection } from "./components/InsightsSection.tsx";

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const [query, setQuery] = useState<string>("");
  const [status, setStatus] = useState<ResearchStatus>("idle");
  const [packet, setPacket] = useState<ResearchPacket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const startResearch = async () => {
    if (!query.trim()) return;

    setStatus("researching");
    setError(null);
    setAskAnswer(null);

    try {
      const response = await fetch(`${API_BASE}/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });

      if (!response.ok) {
        throw new Error(`Research request failed (${response.status})`);
      }

      const data: ResearchPacket = await response.json();
      setPacket(data);
      setStatus("complete");
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  };

  const askQuestion = async () => {
    if (!packet || !question.trim()) return;
    setAsking(true);
    try {
      const response = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: packet.job_id, question }),
      });
      const data = await response.json();
      setAskAnswer(data.answer);
    } catch (err) {
      console.error(err);
      setAskAnswer("Couldn't reach the research agent for that question.");
    } finally {
      setAsking(false);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") startResearch();
  };

  const reset = () => {
    setQuery("");
    setPacket(null);
    setAskAnswer(null);
    setStatus("idle");
  };

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <span className="logo-mark">R</span>
          <span>Research</span>
        </div>

        <div className="connection">
          <span className="status-dot" />
          Ready
        </div>
      </header>

      <main>
        {status === "idle" && (
          <section className="hero">
            <div className="hero-label">AI RESEARCH AGENT</div>

            <h1>
              Research anything.
              <br />
              Get the answer.
            </h1>

            <p className="hero-description">
              Search the web, verify claims against their sources, and turn
              scattered information into an evidence-backed research report.
            </p>

            <div className="search-box">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="What do you want to research?"
                autoFocus
              />

              <button onClick={startResearch} disabled={!query.trim()}>
                →
              </button>
            </div>

            <div className="examples">
              <span>Try</span>
              <button onClick={() => setQuery("NVIDIA finances")}>NVIDIA finances</button>
              <button onClick={() => setQuery("Tesla financials")}>Tesla financials</button>
              <button onClick={() => setQuery("AMD vs NVIDIA")}>AMD vs NVIDIA</button>
            </div>
          </section>
        )}

        {status === "researching" && (
          <section className="research">
            <div className="research-header">
              <div>
                <div className="hero-label">RESEARCHING</div>
                <h2>{query}</h2>
              </div>
              <div className="spinner" />
            </div>

            <div className="steps">
              <ResearchStep number="01" title="Planning queries" state="active" />
              <ResearchStep number="02" title="Finding & fetching sources" state="waiting" />
              <ResearchStep number="03" title="Extracting & verifying claims" state="waiting" />
              <ResearchStep number="04" title="Building report" state="waiting" />
            </div>

            <div className="research-note">
              The agent is searching, fetching pages, extracting claims and
              checking each one against its cited evidence. This runs
              synchronously, so it can take a little while.
            </div>
          </section>
        )}

        {status === "error" && (
          <section className="research">
            <div className="hero-label">SOMETHING WENT WRONG</div>
            <h2>{error}</h2>
            <button className="new-button" onClick={reset} style={{ marginTop: 24 }}>
              Try again
            </button>
          </section>
        )}

        {status === "complete" && packet && (
          <section className="report">
            <div className="report-header">
              <div>
                <div className="hero-label">
                  RESEARCH REPORT <StatusBadge status={packet.status} />
                </div>
                <h2>{packet.topic}</h2>
              </div>
              <button className="new-button" onClick={reset}>
                New research
              </button>
            </div>

            {packet.content && packet.content.metrics.length > 0 && (
              <div className="metrics">
                {packet.content.metrics.slice(0, 3).map((m) => (
                  <Metric key={m.claim_id} label={m.metric ?? "Metric"} value={m.value_text} />
                ))}
              </div>
            )}

            <div className="report-section">
              <h3>Overview</h3>
              <p>{packet.summary || "No summary could be generated for this topic."}</p>
            </div>

            <ChartsSection charts={packet.charts} sources={packet.sources} />

            <InsightsSection insights={packet.insights} sources={packet.sources} />

            <div className="report-section">
              <h3>Key findings ({packet.claims.filter((c) => c.status === "SUPPORTS" || c.status === "PARTIAL").length} verified)</h3>
              {packet.claims
                .filter((c) => c.status === "SUPPORTS" || c.status === "PARTIAL")
                .slice(0, 10)
                .map((c, i) => (
                  <div className="finding" key={c.id}>
                    <span>{String(i + 1).padStart(2, "0")}</span>
                    <p>
                      {c.text} <VerificationTag status={c.status} />
                    </p>
                  </div>
                ))}
              {packet.claims.filter((c) => c.status === "SUPPORTS" || c.status === "PARTIAL").length === 0 && (
                <p style={{ color: "#888", fontSize: 14 }}>No claims cleared verification for this topic.</p>
              )}
            </div>

            {packet.conflicts.length > 0 && (
              <div className="report-section">
                <h3>Conflicting information ({packet.conflicts.length})</h3>
                {packet.conflicts.map((conf) => (
                  <div className="finding" key={conf.id}>
                    <span>!</span>
                    <p>{conf.description}</p>
                  </div>
                ))}
              </div>
            )}

            <div className="report-section">
              <h3>Sources ({packet.sources.length})</h3>
              {packet.sources.slice(0, 10).map((s, i) => (
                <div className="source" key={s.id}>
                  <span>[{i + 1}]</span>
                  <span>
                    {s.title || s.publisher || s.url} · <em style={{ color: "#999" }}>{s.tier.replace("tier", "Tier ").replace("_", " ")}</em>
                  </span>
                </div>
              ))}
            </div>

            <div className="report-section">
              <h3>Ask a follow-up</h3>
              <div className="search-box" style={{ maxWidth: 560 }}>
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && askQuestion()}
                  placeholder="Ask something grounded in this research..."
                />
                <button onClick={askQuestion} disabled={!question.trim() || asking}>
                  {asking ? "…" : "→"}
                </button>
              </div>
              {askAnswer && (
                <p style={{ marginTop: 16, color: "#333", fontSize: 14, lineHeight: 1.7 }}>{askAnswer}</p>
              )}
            </div>

            {packet.status !== "VERIFIED" && (
              <div className="report-section">
                <h3>Pipeline notes</h3>
                <p style={{ color: "#888", fontSize: 12, whiteSpace: "pre-wrap" }}>
                  {packet.stage_notes.join("\n")}
                </p>
              </div>
            )}
          </section>
        )}
      </main>

      <footer>
        <span>Research Agent</span>
        <span>LangGraph · OpenRouter</span>
      </footer>
    </div>
  );
}

type ResearchStepProps = {
  number: string;
  title: string;
  state: "waiting" | "active" | "complete";
};

function ResearchStep({ number, title, state }: ResearchStepProps) {
  return (
    <div className={`step ${state}`}>
      <div className="step-number">{state === "complete" ? "✓" : number}</div>
      <span>{title}</span>
      {state === "active" && <div className="step-loader" />}
    </div>
  );
}

type MetricProps = { label: string; value: string };

function Metric({ label, value }: MetricProps) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <strong style={{ fontSize: 18, lineHeight: 1.4 }}>{value}</strong>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "VERIFIED" ? "verified" : status === "PARTIAL" ? "partial" : "needs-review";
  return <span className={`status-badge ${cls}`}>{status.replace("_", " ")}</span>;
}

function VerificationTag({ status }: { status: string }) {
  const cls = status === "SUPPORTS" ? "supports" : "partial";
  return <span className={`verification-tag ${cls}`}>{status}</span>;
}

export default App;
