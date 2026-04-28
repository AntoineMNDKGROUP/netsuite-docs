import { getServerClient } from "@/lib/supabase";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function ChangesPage() {
  const supabase = getServerClient();
  const { data: changes } = await supabase
    .from("changes")
    .select("*")
    .order("changed_at", { ascending: false })
    .limit(100);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Changements récents</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Les 100 derniers changements détectés sur les objets NetSuite documentés.
        </p>
      </div>
      <ul className="space-y-3">
        {(changes ?? []).map((c) => (
          <li key={c.id} className="border rounded p-3 text-sm">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={
                  "text-xs px-2 py-0.5 rounded " +
                  (c.kind === "created"
                    ? "bg-green-100 text-green-700"
                    : c.kind === "updated"
                    ? "bg-blue-100 text-blue-700"
                    : "bg-red-100 text-red-700")
                }
              >
                {c.kind}
              </span>
              <span className="font-medium">{c.entity_type}</span>
              <span className="text-muted-foreground">→</span>
              <Link
                href={
                  c.entity_type === "script"
                    ? `/scripts/${encodeURIComponent(c.ns_internal_id)}`
                    : `#`
                }
                className="text-primary hover:underline"
              >
                {c.entity_label || c.ns_internal_id}
              </Link>
              <span className="text-muted-foreground ml-auto">
                {new Date(c.changed_at).toLocaleString("fr-FR")}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
