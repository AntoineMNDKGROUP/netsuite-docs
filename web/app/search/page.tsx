"use client";

import { useState } from "react";
import Link from "next/link";
import { renderMarkdown } from "@/lib/markdown";

interface SearchResult {
  source_table: string;
  id: string;
  script_ns_id: string | null;
  title: string;
  snippet: string;
  rank: number;
  meta: any;
}

interface SearchResponse {
  query: string;
  expandedTerms: string[];
  expandError: string | null;
  results: SearchResult[];
  fieldResults: SearchResult[];
  synthesis: string | null;
  synthError: string | null;
  duration_ms: number;
}

const EXAMPLES = [
  "j'ai un problème de code TVA",
  "qui gère les factures EDI ?",
  "scripts qui tournent sur les sales orders",
  "credit hold",
  "intégration Shopify",
  "Mass Update sur les invoices",
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [withSynthesis, setWithSynthesis] = useState(true);
  const [useExpansion, setUseExpansion] = useState(true);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function search(q: string) {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: q, withSynthesis, useExpansion }),
      });
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.error ?? "Search failed");
      }
      setResponse(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">🔍 Recherche globale</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Pose une question en langage naturel — l'IA expansera ta question, fouillera dans les
          scripts, la documentation et le code source, puis te dira ce qui est pertinent.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          search(query);
        }}
        className="space-y-3"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ex: j'ai un problème de code TVA, qui gère les factures EDI..."
          className="border rounded-lg w-full px-4 py-3 text-lg"
          autoFocus
        />
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={useExpansion}
              onChange={(e) => setUseExpansion(e.target.checked)}
            />
            Expansion IA des termes
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={withSynthesis}
              onChange={(e) => setWithSynthesis(e.target.checked)}
            />
            Synthèse IA
          </label>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="ml-auto bg-primary text-primary-foreground rounded-lg px-6 py-2 disabled:opacity-50"
          >
            {loading ? "Recherche..." : "Rechercher"}
          </button>
        </div>
      </form>

      {!response && !loading && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">Exemples :</p>
          <div className="flex gap-2 flex-wrap">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuery(ex);
                  search(ex);
                }}
                className="text-sm border rounded-full px-3 py-1 hover:bg-muted"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="border border-red-300 bg-red-50 text-red-700 rounded p-3">{error}</div>
      )}

      {loading && (
        <div className="text-muted-foreground">
          ⏳ Expansion des mots-clés, recherche en base, synthèse IA...
        </div>
      )}

      {response && (
        <div className="space-y-6">
          {response.expandedTerms && response.expandedTerms.length > 1 && (
            <div className="text-sm">
              <span className="text-muted-foreground">🪄 Termes recherchés :</span>{" "}
              {response.expandedTerms.slice(0, 12).map((t, i) => (
                <span key={i} className="inline-block bg-muted rounded px-2 py-0.5 ml-1 mb-1">
                  {t}
                </span>
              ))}
            </div>
          )}

          {response.synthesis && (
            <section className="border border-violet-300 bg-violet-50/50 rounded-lg p-4">
              <h2 className="font-semibold mb-2 flex items-center gap-2">
                ✨ Réponse de Claude
              </h2>
              <div
                className="text-sm prose prose-sm max-w-none"
                dangerouslySetInnerHTML={{ __html: linkScripts(renderMarkdown(response.synthesis)) }}
              />
            </section>
          )}

          {response.synthError && (
            <div className="text-xs text-amber-700 border border-amber-300 bg-amber-50 rounded p-2">
              ⚠️ Synthèse IA échouée : {response.synthError}
            </div>
          )}

          <section>
            <h2 className="font-semibold mb-3">
              📋 Résultats ({response.results.length}) — {response.duration_ms}ms
            </h2>
            <ul className="space-y-2">
              {response.results.map((r, i) => (
                <li
                  key={i}
                  className="border rounded p-3 hover:bg-muted/30 transition"
                >
                  <div className="flex items-baseline gap-2 flex-wrap">
                    {r.script_ns_id ? (
                      <Link
                        href={`/scripts/${encodeURIComponent(r.script_ns_id)}`}
                        className="font-medium text-primary hover:underline"
                      >
                        {r.title}
                      </Link>
                    ) : (
                      <span className="font-medium">{r.title}</span>
                    )}
                    <Badge type={r.source_table} />
                    {r.meta?.script_type && (
                      <span className="text-xs bg-muted rounded px-2 py-0.5">
                        {r.meta.script_type}
                      </span>
                    )}
                    {r.meta?.tags?.length > 0 &&
                      r.meta.tags.slice(0, 3).map((t: string) => (
                        <span
                          key={t}
                          className="text-xs bg-blue-100 text-blue-700 rounded px-2 py-0.5"
                        >
                          {t}
                        </span>
                      ))}
                    <span className="text-xs text-muted-foreground ml-auto">
                      score {r.rank.toFixed(3)}
                    </span>
                  </div>
                  {r.snippet && (
                    <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{r.snippet}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {response.fieldResults.length > 0 && (
            <section>
              <h2 className="font-semibold mb-3">
                🏷️ Custom fields associés ({response.fieldResults.length})
              </h2>
              <ul className="space-y-1 text-sm">
                {response.fieldResults.map((r, i) => (
                  <li key={i} className="border rounded p-2">
                    <span className="font-medium">{r.title}</span>{" "}
                    <span className="code text-muted-foreground">{r.meta?.field_id}</span>{" "}
                    <span className="text-xs bg-muted rounded px-2 py-0.5">{r.meta?.category}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function Badge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    script: "bg-green-100 text-green-700",
    doc: "bg-violet-100 text-violet-700",
    code: "bg-amber-100 text-amber-700",
    field: "bg-blue-100 text-blue-700",
  };
  const labels: Record<string, string> = {
    script: "script",
    doc: "📝 doc",
    code: "</> code",
    field: "🏷 field",
  };
  return (
    <span className={`text-xs rounded px-2 py-0.5 ${styles[type] ?? "bg-muted"}`}>
      {labels[type] ?? type}
    </span>
  );
}

// Transforme les [#NS_ID] dans la synthèse en liens cliquables vers la page script
function linkScripts(html: string): string {
  return html.replace(/\[#(\d+)\]/g, (_, id) => {
    return `<a href="/scripts/${id}" class="text-primary hover:underline">[#${id}]</a>`;
  });
}
