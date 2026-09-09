import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec, Source } from "../types/status.ts";

// Vibrant but soothing — muted-saturation hues that stay legible against
// the black-and-white chrome without turning garish.
const PALETTE = ["#5B8DEF", "#4CC9A0", "#F2B84B", "#EF7C8E", "#8E7CC3", "#5EC8D8"];

function citationLabel(sourceIds: string[], sources: Source[]): string {
  const names = sourceIds
    .map((id) => sources.find((s) => s.id === id))
    .filter(Boolean)
    .slice(0, 3)
    .map((s) => s!.publisher || s!.title || s!.url);
  if (names.length === 0) return "No source citations available.";
  const suffix = sourceIds.length > names.length ? ` +${sourceIds.length - names.length} more` : "";
  return `Sources: ${names.join(", ")}${suffix}`;
}

function ChartCard({ chart, sources }: { chart: ChartSpec; sources: Source[] }) {
  const data = chart.x_labels.map((label, i) => {
    const row: Record<string, string | number | null> = { label };
    chart.series.forEach((s) => {
      row[s.name] = s.values[i] ?? null;
    });
    return row;
  });

  return (
    <div className="chart-card">
      <h4>{chart.title}</h4>
      <div className="chart-body">
        {chart.chart_type === "bar" && (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#888" }} axisLine={{ stroke: "#ddd" }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #eee", borderRadius: 0 }} />
              {chart.series.map((s, i) => (
                <Bar key={s.name} dataKey={s.name} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        {chart.chart_type === "line" && (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#888" }} axisLine={{ stroke: "#ddd" }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #eee", borderRadius: 0 }} />
              {chart.series.map((s, i) => (
                <Line
                  key={s.name}
                  type="monotone"
                  dataKey={s.name}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}

        {chart.chart_type === "pie" && (
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={data}
                dataKey={chart.series[0]?.name}
                nameKey="label"
                innerRadius={55}
                outerRadius={95}
                paddingAngle={2}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="#fff" strokeWidth={2} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #eee", borderRadius: 0 }} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#666" }} />
            </PieChart>
          </ResponsiveContainer>
        )}

        {chart.chart_type === "correlation" && chart.series.length >= 2 && (
          <ResponsiveContainer width="100%" height={260}>
            <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis
                type="number"
                dataKey="x"
                name={chart.series[0].name}
                tick={{ fontSize: 11, fill: "#888" }}
                axisLine={{ stroke: "#ddd" }}
                tickLine={false}
              />
              <YAxis
                type="number"
                dataKey="y"
                name={chart.series[1].name}
                tick={{ fontSize: 11, fill: "#888" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #eee", borderRadius: 0 }} cursor={{ strokeDasharray: "3 3" }} />
              <Scatter
                data={chart.x_labels.map((label, i) => ({
                  label,
                  x: chart.series[0].values[i],
                  y: chart.series[1].values[i],
                }))}
                fill={PALETTE[0]}
              />
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>

      {chart.note && <p className="chart-note">{chart.note}</p>}
      <p className="chart-citation">{citationLabel(chart.source_ids, sources)}</p>
    </div>
  );
}

export function ChartsSection({ charts, sources }: { charts: ChartSpec[]; sources: Source[] }) {
  if (charts.length === 0) return null;
  return (
    <div className="report-section">
      <h3>Visualized data ({charts.length})</h3>
      <div className="charts-grid">
        {charts.map((chart) => (
          <ChartCard key={chart.id} chart={chart} sources={sources} />
        ))}
      </div>
    </div>
  );
}
