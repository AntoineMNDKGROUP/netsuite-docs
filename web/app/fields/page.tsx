import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function FieldsPage() {
  const supabase = getServerClient();
  const { data, count } = await supabase
    .from("custom_fields")
    .select("*", { count: "exact" })
    .order("label")
    .limit(200);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Custom fields</h1>
        <span className="text-sm text-muted-foreground">
          {(count ?? 0).toLocaleString("fr-FR")} résultats — affichage limité aux 200 premiers
        </span>
      </div>
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left">
            <tr>
              <th className="px-3 py-2">Label</th>
              <th className="px-3 py-2">Field ID</th>
              <th className="px-3 py-2">Catégorie</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Statut</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((f) => (
              <tr key={f.ns_internal_id} className="border-t">
                <td className="px-3 py-2">{f.label}</td>
                <td className="px-3 py-2 code text-muted-foreground">{f.field_id}</td>
                <td className="px-3 py-2">
                  <span className="text-xs bg-muted rounded px-2 py-0.5">{f.field_category}</span>
                </td>
                <td className="px-3 py-2">{f.field_type ?? "—"}</td>
                <td className="px-3 py-2">{f.is_inactive ? "inactif" : "actif"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
