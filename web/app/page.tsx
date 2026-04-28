import { getServerClient } from "@/lib/supabase";
import Link from "next/link";

export const dynamic = "force-dynamic";

async function getStats() {
  const supabase = getServerClient();
  const tables = [
    "scripts",
    "script_deployments",
    "custom_fields",
    "custom_record_types",
    "system_notes",
    "changes",
  ] as const;
  const counts: Record<string, number> = {};
  for (const t of tables) {
    const { count } = await supabase.from(t).select("*", { count: "exact", head: true });
    counts[t] = count ?? 0;
  }
  const { data: lastRun } = await supabase
    .from("sync_runs")
    .select("started_at,status,duration_ms,stats")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  return { counts, lastRun };
}

const TILES = [
  { key: "scripts", label: "Scripts", href: "/scripts" },
  { key: "script_deployments", label: "Deployments", href: "/deployments" },
  { key: "custom_fields", label: "Custom fields", href: "/fields" },
  { key: "custom_record_types", label: "Custom records", href: "/custom-records" },
  { key: "system_notes", label: "System notes", href: "/changes" },
  { key: "changes", label: "Changements détectés", href: "/changes" },
];

export default async function HomePage() {
  const { counts, lastRun } = await getStats();
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Vue d'ensemble</h1>
        <p className="text-muted-foreground mt-1">
          État courant du compte NetSuite sandbox NDK et historique des modifications.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {TILES.map((t) => (
          <Link
            key={t.key}
            href={t.href}
            className="border rounded-lg p-4 hover:bg-muted transition"
          >
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {t.label}
            </div>
            <div className="text-3xl font-semibold mt-1">
              {counts[t.key]?.toLocaleString("fr-FR") ?? 0}
            </div>
          </Link>
        ))}
      </div>

      {lastRun && (
        <section className="border rounded-lg p-4">
          <h2 className="font-semibold mb-2">Dernière synchronisation</h2>
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Démarrée</dt>
            <dd>{new Date(lastRun.started_at).toLocaleString("fr-FR")}</dd>
            <dt className="text-muted-foreground">Statut</dt>
            <dd>
              <span
                className={
                  "inline-block px-2 py-0.5 rounded text-xs " +
                  (lastRun.status === "success"
                    ? "bg-green-100 text-green-800"
                    : lastRun.status === "partial"
                    ? "bg-yellow-100 text-yellow-800"
                    : "bg-red-100 text-red-800")
                }
              >
                {lastRun.status}
              </span>
            </dd>
            <dt className="text-muted-foreground">Durée</dt>
            <dd>{lastRun.duration_ms ? `${(lastRun.duration_ms / 1000).toFixed(1)}s` : "—"}</dd>
          </dl>
          {lastRun.stats && (
            <pre className="mt-3 code bg-muted p-3 rounded overflow-x-auto">
              {JSON.stringify(lastRun.stats, null, 2)}
            </pre>
          )}
        </section>
      )}
    </div>
  );
}
