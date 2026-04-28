import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function CustomRecordsPage() {
  const supabase = getServerClient();
  const { data, count } = await supabase
    .from("custom_record_types")
    .select("*", { count: "exact" })
    .order("name");

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Custom records</h1>
        <span className="text-sm text-muted-foreground">
          {(count ?? 0).toLocaleString("fr-FR")} résultats
        </span>
      </div>
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left">
            <tr>
              <th className="px-3 py-2">Nom</th>
              <th className="px-3 py-2">Record ID</th>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2">Statut</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((r) => (
              <tr key={r.ns_internal_id} className="border-t">
                <td className="px-3 py-2 font-medium">{r.name}</td>
                <td className="px-3 py-2 code text-muted-foreground">{r.record_id}</td>
                <td className="px-3 py-2 text-muted-foreground">{r.description ?? "—"}</td>
                <td className="px-3 py-2">{r.is_inactive ? "inactif" : "actif"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
