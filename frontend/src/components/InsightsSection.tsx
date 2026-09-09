import type { Insight, Source } from "../types/status.ts";

const TYPE_LABEL: Record<string, string> = {
  TREND: "Trend",
  CONCEPT: "Concept",
  COMPARISON: "Comparison",
};

function sourceNames(sourceIds: string[], sources: Source[]): string {
  const names = sourceIds
    .map((id) => sources.find((s) => s.id === id))
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s!.publisher || s!.title || s!.url);
  return names.length ? names.join(", ") : "Unattributed";
}

export function InsightsSection({ insights, sources }: { insights: Insight[]; sources: Source[] }) {
  if (insights.length === 0) return null;
  return (
    <div className="report-section">
      <h3>Trends & concepts ({insights.length})</h3>
      <div className="insights-grid">
        {insights.map((insight) => (
          <div className="insight-card" key={insight.id}>
            <span className="insight-tag">{TYPE_LABEL[insight.type] ?? insight.type}</span>
            <h4>{insight.title}</h4>
            <p>{insight.body}</p>
            <span className="insight-citation">{sourceNames(insight.source_ids, sources)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
