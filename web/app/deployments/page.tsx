import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function DeploymentsPage() {
  const supabase = getServerClient();
  const { data, count } = await supabase
    .from("script_deployments")
    .select("*", { count: "exact" })
    .order("title");

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Deployments</h1>
        <span className="text-sm text-muted-foreground">
          {(count ?? 0).toLocaleString("fr-FR")} résultats
        </span>
      </div>
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left">
            <tr>
              <th className="px-3 py-2">Title</th>
              <th className="px-3 py-2">Deployment ID</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Deployed</th>
              <th className="px-3 py-2">Log level</th>
              <th className="px-3 py-2">Run as</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((d) => (
              <tr key={d.ns_internal_id} className="border-t hover:bg-muted/40">
                <td className="px-3 py-2">{d.title}</td>
                <td className="px-3 py-2 code text-muted-foreground">{d.deployment_id}</td>
                <td className="px-3 py-2">{d.status}</td>
                <td className="px-3 py-2">{d.is_deployed ? "✓" : "—"}</td>
                <td className="px-3 py-2">{d.log_level}</td>
                <td className="px-3 py-2">{d.execute_as_role ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
