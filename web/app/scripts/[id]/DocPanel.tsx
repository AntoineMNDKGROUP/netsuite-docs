"use client";

import { useState } from "react";
import { renderMarkdown } from "@/lib/markdown";
import { autoDocFromSource } from "@/lib/auto-doc";

interface ScriptDoc {
  business_purpose?: string | null;
  technical_summary?: string | null;
  usage_notes?: string | null;
  tags?: string[] | null;
  related_scripts?: string[] | null;
  content_md?: string | null;
  status?: string | null;
  ai_generated?: boolean | null;
  ai_model?: string | null;
  updated_at?: string | null;
  authored_by?: string | null;
}

interface Props {
  scriptId: string;
  script: { name: string; script_id: string | null; script_type: string | null };
  sourceFile?: { file_name: string | null; content: string | null; jsdoc: any } | null;
  initialDoc: ScriptDoc | null;
}

export default function DocPanel({ scriptId, script, sourceFile, initialDoc }: Props) {
  const [doc, setDoc] = useState<ScriptDoc>(initialDoc ?? {});
  const [editing, setEditing] = useState(!initialDoc);
  const [saving, setSaving] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function update<K extends keyof ScriptDoc>(k: K, v: ScriptDoc[K]) {
    setDoc((d) => ({ ...d, [k]: v }));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/doc`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(doc),
      });
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.error ?? "Save failed");
      }
      const saved = await res.json();
      setDoc(saved);
      setEditing(false);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function loadAutoFill() {
    const auto = autoDocFromSource(script, sourceFile ?? undefined);
    setDoc({
      ...doc,
      business_purpose: doc.business_purpose || auto.business_purpose,
      technical_summary: doc.technical_summary || auto.technical_summary,
      usage_notes: doc.usage_notes || auto.usage_notes,
      tags: doc.tags?.length ? doc.tags : auto.tags,
      content_md: doc.content_md || auto.content_md,
    });
    setEditing(true);
  }

  async function loadAiSuggest() {
    setAiBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/scripts/${encodeURIComponent(scriptId)}/ai-suggest`, {
        method: "POST",
      });
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.error ?? "AI failed");
      }
      const ai = await res.json();
      setDoc({
        ...doc,
        business_purpose: ai.business_purpose ?? doc.business_purpose,
        technical_summary: ai.technical_summary ?? doc.technical_summary,
        usage_notes: ai.usage_notes ?? doc.usage_notes,
        tags: (ai.tags && ai.tags.length ? ai.tags : doc.tags) ?? [],
        ai_generated: true,
        ai_model: ai.ai_model,
      });
      setEditing(true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setAiBusy(false);
    }
  }

  if (!editing) {
    // Mode lecture
    return (
      <section className="border rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="font-semibold">📝 Documentation</h2>
          <span
            className={
              "text-xs px-2 py-0.5 rounded " +
              (doc.status === "published"
                ? "bg-green-100 text-green-700"
                : doc.status === "obsolete"
                ? "bg-red-100 text-red-700"
                : "bg-yellow-100 text-yellow-700")
            }
          >
            {doc.status ?? "draft"}
          </span>
          {doc.ai_generated && (
            <span className="text-xs px-2 py-0.5 rounded bg-violet-100 text-violet-700">
              ✨ AI {doc.ai_model && `(${doc.ai_model})`}
            </span>
          )}
          <span className="text-xs text-muted-foreground ml-auto">
            {doc.updated_at && `Mis à jour le ${new Date(doc.updated_at).toLocaleString("fr-FR")}`}
          </span>
          <button
            onClick={() => setEditing(true)}
            className="border rounded px-3 py-1 text-sm hover:bg-muted"
          >
            ✏️ Éditer
          </button>
        </div>

        {doc.business_purpose && (
          <Field label="Pourquoi ?" value={doc.business_purpose} />
        )}
        {doc.technical_summary && (
          <Field label="Comment ça marche" value={doc.technical_summary} />
        )}
        {doc.usage_notes && <Field label="Quand / qui" value={doc.usage_notes} />}

        {doc.tags && doc.tags.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Tags</div>
            <div className="flex gap-1 flex-wrap">
              {doc.tags.map((t) => (
                <span key={t} className="text-xs bg-muted rounded px-2 py-0.5">
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {doc.content_md && (
          <div className="prose prose-sm max-w-none border-t pt-4">
            <div dangerouslySetInnerHTML={{ __html: renderMarkdown(doc.content_md) }} />
          </div>
        )}
      </section>
    );
  }

  // Mode édition
  return (
    <section className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="font-semibold">📝 Édition de la documentation</h2>
        <button
          onClick={loadAutoFill}
          className="text-xs border rounded px-2 py-1 hover:bg-muted ml-auto"
        >
          🪄 Auto-extraire du code
        </button>
        <button
          onClick={loadAiSuggest}
          disabled={aiBusy || !sourceFile}
          className="text-xs border rounded px-2 py-1 bg-violet-50 hover:bg-violet-100 disabled:opacity-50"
          title={sourceFile ? "Génère une suggestion via Claude" : "Code source pas encore extrait"}
        >
          {aiBusy ? "⏳ Claude réfléchit..." : "✨ Suggérer via Claude"}
        </button>
      </div>

      {err && <div className="border border-red-300 bg-red-50 text-red-700 text-sm rounded p-2">{err}</div>}

      <Input
        label="Business purpose (pourquoi ?)"
        value={doc.business_purpose ?? ""}
        onChange={(v) => update("business_purpose", v)}
        placeholder="Ex: Annule automatiquement les sales orders > 90 jours dans une subsidiary donnée"
        rows={2}
      />
      <Input
        label="Technical summary (comment ça marche)"
        value={doc.technical_summary ?? ""}
        onChange={(v) => update("technical_summary", v)}
        placeholder="Ex: Map/Reduce qui itère sur les SO via une saved search, puis applique recordTransform.void"
        rows={3}
      />
      <Input
        label="Usage notes (quand / qui)"
        value={doc.usage_notes ?? ""}
        onChange={(v) => update("usage_notes", v)}
        placeholder="Ex: Tourne tous les lundis à 03h. À surveiller : volume > 5000 → revoir le scheduling"
        rows={2}
      />

      <div>
        <label className="text-xs uppercase tracking-wide text-muted-foreground">Tags (séparés par virgule)</label>
        <input
          value={(doc.tags ?? []).join(", ")}
          onChange={(e) => update("tags", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          className="border rounded w-full px-2 py-1 text-sm mt-1"
          placeholder="Comptabilité, EDI, France"
        />
      </div>

      <Input
        label="Notes complémentaires (Markdown)"
        value={doc.content_md ?? ""}
        onChange={(v) => update("content_md", v)}
        placeholder="Tout détail supplémentaire en markdown…"
        rows={6}
      />

      <div className="flex items-center gap-2">
        <label className="text-sm">Statut :</label>
        <select
          value={doc.status ?? "draft"}
          onChange={(e) => update("status", e.target.value as any)}
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="draft">Draft</option>
          <option value="published">Published</option>
          <option value="obsolete">Obsolete</option>
        </select>

        <button
          onClick={save}
          disabled={saving}
          className="ml-auto bg-primary text-primary-foreground rounded px-4 py-1.5 text-sm disabled:opacity-50"
        >
          {saving ? "Enregistrement..." : "💾 Enregistrer"}
        </button>
        {initialDoc && (
          <button
            onClick={() => {
              setDoc(initialDoc);
              setEditing(false);
            }}
            className="border rounded px-3 py-1.5 text-sm hover:bg-muted"
          >
            Annuler
          </button>
        )}
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">{label}</div>
      <div className="text-sm whitespace-pre-wrap">{value}</div>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <div>
      <label className="text-xs uppercase tracking-wide text-muted-foreground">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="border rounded w-full px-2 py-1 text-sm mt-1 font-sans"
      />
    </div>
  );
}
