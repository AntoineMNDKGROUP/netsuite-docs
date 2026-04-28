import { getServerClient } from "@/lib/supabase";
import Link from "next/link";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

interface PageProps {
  searchParams: { q?: string; type?: string; status?: string; page?: string };
}

export default async function ScriptsPage({ searchParams }: PageProps) {
  const q = (searchParams.q ?? "").trim();
  const type = searchParams.type ?? "";
  const status = searchParams.status ?? "all";
  const page = Math.max(1, parseInt(searchParams.page ?? "1", 10) || 1);

  const supabase = getServerClient();
  let query = supabase.from("scripts").select("*", { count: "exact" });

  if (q) query = query.or(`name.ilike.%${q}%,script_id.ilike.%${q}%`);
  if (type) query = query.eq("script_type", type);
  if (status === "active") query = query.eq("is_inactive", false);
  if (status === "inactive") query = query.eq("is_inactive", true);

  query = query
    .order("name", { ascending: true })
    .range((page - 1) * PAGE_SIZE, page * PAGE_SIZE - 1);

  const { data, count } = await query;

  // Liste distincte des types (pour le filtre)
  const { data: typeRows } = await supabase
    .from("scripts")
    .select("script_type")
    .order("script_type");
  const types = Array.from(new Set((typeRows ?? []).map((r) => r.script_type).filter(Boolean)));

  const totalPages = Math.max(1, Math.ceil((count ?? 0) / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Scripts</h1>
        <span className="text-sm text-muted-foreground">
          {(count ?? 0).toLocaleString("fr-FR")} résultats
        </span>
      </div>

      <form className="flex flex-wrap gap-2 items-center">
        <input
          name="q"
          defaultValue={q}
          placeholder="Rechercher par nom ou script_id…"
          className="border rounded px-3 py-2 text-sm flex-1 min-w-64"
        />
        <select name="type" defaultValue={type} className="border rounded px-3 py-2 text-sm">
          <option value="">Tous types</option>
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select name="status" defaultValue={status} className="border rounded px-3 py-2 text-sm">
          <option value="all">Tous statuts</option>
          <option value="active">Actifs uniquement</option>
          <option value="inactive">Inactifs uniquement</option>
        </select>
        <button className="bg-primary text-primary-foreground rounded px-4 py-2 text-sm">
          Filtrer
        </button>
      </form>

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Nom</th>
              <th className="px-3 py-2 font-medium">Script ID</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">API</th>
              <th className="px-3 py-2 font-medium">Statut</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((s) => (
              <tr key={s.ns_internal_id} className="border-t hover:bg-muted/40">
                <td className="px-3 py-2">
                  <Link
                    href={`/scripts/${encodeURIComponent(s.ns_internal_id)}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {s.name}
                  </Link>
                </td>
                <td className="px-3 py-2 code text-muted-foreground">{s.script_id}</td>
                <td className="px-3 py-2">{s.script_type}</td>
                <td className="px-3 py-2">{s.api_version}</td>
                <td className="px-3 py-2">
                  {s.is_inactive ? (
                    <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700">inactif</span>
                  ) : (
                    <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">actif</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} q={q} type={type} status={status} />
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  q,
  type,
  status,
}: {
  page: number;
  totalPages: number;
  q: string;
  type: string;
  status: string;
}) {
  if (totalPages <= 1) return null;
  const buildUrl = (p: number) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (type) params.set("type", type);
    if (status && status !== "all") params.set("status", status);
    params.set("page", String(p));
    return `?${params.toString()}`;
  };
  return (
    <div className="flex items-center justify-between text-sm">
      <Link
        href={buildUrl(Math.max(1, page - 1))}
        aria-disabled={page === 1}
        className={"border rounded px-3 py-1.5 " + (page === 1 ? "opacity-50 pointer-events-none" : "hover:bg-muted")}
      >
        ← Précédent
      </Link>
      <span className="text-muted-foreground">
        Page {page} / {totalPages}
      </span>
      <Link
        href={buildUrl(Math.min(totalPages, page + 1))}
        aria-disabled={page === totalPages}
        className={
          "border rounded px-3 py-1.5 " +
          (page === totalPages ? "opacity-50 pointer-events-none" : "hover:bg-muted")
        }
      >
        Suivant →
      </Link>
    </div>
  );
}
