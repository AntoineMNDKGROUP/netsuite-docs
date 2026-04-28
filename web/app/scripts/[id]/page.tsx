import { getServerClient } from "@/lib/supabase";
import Link from "next/link";
import { notFound } from "next/navigation";
import DocPanel from "./DocPanel";

export const dynamic = "force-dynamic";

interface PageProps {
  params: { id: string };
}

export default async function ScriptDetailPage({ params }: PageProps) {
  const supabase = getServerClient();
  const id = decodeURIComponent(params.id);

  const [{ data: script }, { data: deployments }, { data: changes }, { data: srcFile }, { data: doc }] =
    await Promise.all([
      supabase.from("scripts").select("*").eq("ns_internal_id", id).maybeSingle(),
      supabase.from("script_deployments").select("*").eq("script_ns_id", id),
      supabase
        .from("changes")
        .select("kind,changed_at,diff,changed_by,entity_type")
        .or(`and(entity_type.eq.script,ns_internal_id.eq.${id}),and(entity_type.eq.script_source_file,ns_internal_id.eq.${id})`)
        .order("changed_at", { ascending: false })
        .limit(20),
      supabase
        .from("script_source_files")
        .select("file_name,content,jsdoc,file_size,file_type,content_sha256,ns_last_modified")
        .eq("script_ns_id", id)
        .maybeSingle(),
      supabase.from("script_docs").select("*").eq("script_ns_id", id).maybeSingle(),
    ]);

  if (!script) notFound();

  return (
    <div className="space-y-8">
      <div>
        <Link href="/scripts" className="text-sm text-muted-foreground hover:text-foreground">
          ← Retour
        </Link>
        <h1 className="text-2xl font-bold mt-2">{script.name}</h1>
        <p className="code text-muted-foreground">{script.script_id}</p>
      </div>

      {/* DOC PANEL — édition, AI, auto-extraction */}
      <DocPanel
        scriptId={id}
        script={script}
        sourceFile={srcFile}
        initialDoc={doc}
      />

      {/* MÉTADONNÉES NETSUITE */}
      <section className="border rounded-lg p-4">
        <h2 className="font-semibold mb-3">Métadonnées NetSuite</h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-y-2 text-sm">
          <Field label="Type" value={script.script_type} />
          <Field label="Version API" value={script.api_version} />
          <Field label="Statut" value={script.is_inactive ? "Inactif" : "Actif"} />
          <Field label="Owner" value={script.owner} />
          <Field label="Créé" value={fmtDate(script.date_created)} />
          <Field label="Modifié" value={fmtDate(script.last_modified)} />
          <Field label="Description" value={script.description} className="col-span-full" />
        </dl>
      </section>

      {/* CODE SOURCE */}
      {srcFile && (
        <section className="border rounded-lg p-4">
          <h2 className="font-semibold mb-3 flex items-center gap-2 flex-wrap">
            📂 Code source
            <span className="text-xs text-muted-foreground">{srcFile.file_name}</span>
            <span className="text-xs bg-muted px-2 py-0.5 rounded">{srcFile.file_size} octets</span>
            {srcFile.content_sha256 && (
              <span className="text-xs code text-muted-foreground" title={srcFile.content_sha256}>
                SHA256: {String(srcFile.content_sha256).slice(0, 12)}…
              </span>
            )}
            {srcFile.jsdoc && Object.keys(srcFile.jsdoc).length > 0 && (
              <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded ml-auto">
                JSDoc: {Object.keys(srcFile.jsdoc).join(", ")}
              </span>
            )}
          </h2>
          <details>
            <summary className="cursor-pointer text-sm text-primary">
              Afficher le code ({srcFile.content?.length ?? 0} caractères)
            </summary>
            <pre className="code bg-muted p-3 rounded mt-2 overflow-x-auto max-h-[600px] text-xs">
              {srcFile.content}
            </pre>
          </details>
        </section>
      )}

      {/* DEPLOYMENTS */}
      <section className="border rounded-lg p-4">
        <h2 className="font-semibold mb-3">Déploiements ({deployments?.length ?? 0})</h2>
        {deployments && deployments.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-2 py-1">Title</th>
                <th className="px-2 py-1">ID</th>
                <th className="px-2 py-1">Status</th>
                <th className="px-2 py-1">Log</th>
                <th className="px-2 py-1">Run as</th>
              </tr>
            </thead>
            <tbody>
              {deployments.map((d) => (
                <tr key={d.ns_internal_id} className="border-t">
                  <td className="px-2 py-1">{d.title}</td>
                  <td className="px-2 py-1 code text-muted-foreground">{d.deployment_id}</td>
                  <td className="px-2 py-1">{d.status}</td>
                  <td className="px-2 py-1">{d.log_level}</td>
                  <td className="px-2 py-1">{d.execute_as_role ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted-foreground">Aucun déploiement enregistré.</p>
        )}
      </section>

      {/* CHANGES TIMELINE */}
      <section className="border rounded-lg p-4">
        <h2 className="font-semibold mb-3">Historique des changements ({changes?.length ?? 0})</h2>
        {changes && changes.length > 0 ? (
          <ul className="space-y-3">
            {changes.map((c, i) => (
              <li key={i} className="text-sm">
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
                  <span className="text-xs text-muted-foreground">{c.entity_type}</span>
                  <span className="text-muted-foreground">{fmtDate(c.changed_at)}</span>
                  {c.changed_by && <span className="text-muted-foreground">par {c.changed_by}</span>}
                </div>
                {c.diff && (
                  <pre className="code bg-muted p-2 rounded mt-1 overflow-x-auto text-xs">
                    {JSON.stringify(c.diff, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Aucun changement détecté pour ce script.</p>
        )}
      </section>
    </div>
  );
}

function Field({ label, value, className = "" }: { label: string; value: any; className?: string }) {
  return (
    <>
      <dt className={"text-muted-foreground text-xs uppercase tracking-wide " + className}>{label}</dt>
      <dd className={"text-sm " + className}>{value ?? "—"}</dd>
    </>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR");
  } catch {
    return iso;
  }
}
