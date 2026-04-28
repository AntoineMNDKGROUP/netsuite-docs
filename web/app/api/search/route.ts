// Search globale avec expansion de query + synthèse IA
// POST /api/search { query: string, withSynthesis: boolean }
import { NextRequest, NextResponse } from "next/server";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 60;

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6";

async function callClaude(system: string, user: string, max_tokens = 1024) {
  if (!ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY missing");
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens,
      system,
      messages: [{ role: "user", content: user }],
    }),
  });
  if (!r.ok) throw new Error(`Anthropic ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const data = await r.json();
  return data.content?.[0]?.text ?? "";
}

const EXPAND_SYSTEM = `Tu es un assistant qui aide à interroger une base de scripts NetSuite.
On te donne une question utilisateur (souvent en français, parfois en anglais).
Tu réponds en JSON strict avec une liste de mots-clés et synonymes pertinents pour cette recherche.
Format :
{ "keywords": ["mot1", "mot2", "synonyme1", "term technique", "préfixe_custbody"] }

Inclus :
- Les mots-clés directs de la question
- Leurs traductions FR↔EN (ex: TVA→VAT, facture→invoice)
- Termes techniques NetSuite associés (custbody_, custcol_, customrecord_, types de records)
- Variantes de casse / abréviations courantes

10-15 mots-clés max. Pas de phrase, juste des termes courts. JSON uniquement, pas de markdown.`;

const SYNTH_SYSTEM = `Tu es un assistant qui aide à naviguer dans une base de scripts NetSuite documentés.
On te donne :
- La question d'un utilisateur
- Une liste de scripts/champs/extraits de code remontés par notre recherche

Tu réponds en français, en markdown, en :
1. Identifiant 3 à 6 résultats les PLUS pertinents pour la question (cite leur titre)
2. Expliquant en 1-2 phrases POURQUOI chacun est pertinent
3. Suggérant une piste pour résoudre le problème de l'utilisateur si c'est possible
4. Citant les ID des scripts au format [#NS_ID] pour qu'on puisse linker

Sois concret et factuel. Ne dépasse pas 200 mots. Pas de blabla.`;

export async function POST(req: NextRequest) {
  const body = await req.json();
  const query: string = (body.query ?? "").trim();
  const withSynthesis: boolean = body.withSynthesis !== false;
  const useExpansion: boolean = body.useExpansion !== false;

  if (!query) {
    return NextResponse.json({ error: "query required" }, { status: 400 });
  }

  const supabase = getServerClient();
  const t0 = Date.now();

  // 1. Query expansion via Claude (optionnel mais activé par défaut)
  let expandedTerms: string[] = [query];
  let expandError: string | null = null;
  if (useExpansion && ANTHROPIC_API_KEY) {
    try {
      const text = await callClaude(EXPAND_SYSTEM, `Question : ${query}`, 300);
      const m = text.match(/\{[\s\S]*\}/);
      const parsed = JSON.parse(m ? m[0] : text);
      if (Array.isArray(parsed.keywords)) {
        expandedTerms = [query, ...parsed.keywords];
      }
    } catch (e: any) {
      expandError = String(e.message || e);
    }
  }

  // 2. Search Postgres avec la version expansée
  // IMPORTANT : websearch_to_tsquery traite les espaces comme AND. Pour vraiment "ouvrir le filet"
  // avec les synonymes IA, il faut un OR explicite (mot-clé reconnu par websearch_to_tsquery → `|`).
  // On garde la question originale entre guillemets (phrase boost) et on rajoute chaque synonyme en OR.
  const cleanedOriginal = query.replace(/"/g, "").trim();
  const synonyms = expandedTerms
    .slice(1) // skip la query originale qu'on remet en phrase ci-dessous
    .map((t) => t.replace(/"/g, "").trim())
    .filter((t) => t.length > 1);
  const fullQuery = synonyms.length
    ? [`"${cleanedOriginal}"`, ...synonyms].join(" OR ")
    : cleanedOriginal;

  const { data: results, error: rpcError } = await supabase.rpc("search_global", {
    q_text: fullQuery,
    result_limit: 30,
  });

  if (rpcError) {
    return NextResponse.json({ error: rpcError.message }, { status: 500 });
  }

  // 3. Dédoublonnage : garder les meilleurs scores par script_ns_id
  const bestByScript = new Map<string, any>();
  for (const r of results ?? []) {
    if (!r.script_ns_id) continue;
    const existing = bestByScript.get(r.script_ns_id);
    if (!existing || r.rank > existing.rank) {
      bestByScript.set(r.script_ns_id, r);
    }
  }
  const dedupedScripts = Array.from(bestByScript.values()).sort((a, b) => b.rank - a.rank);
  const fieldResults = (results ?? []).filter((r: any) => r.source_table === "field").slice(0, 8);

  // 4. Synthèse via Claude (optionnel)
  let synthesis: string | null = null;
  let synthError: string | null = null;
  const topForSynth = dedupedScripts.slice(0, 12);

  if (withSynthesis && ANTHROPIC_API_KEY && topForSynth.length > 0) {
    const context = topForSynth
      .map(
        (r, i) =>
          `${i + 1}. [#${r.script_ns_id}] ${r.title}\n   type: ${r.source_table}, rank: ${r.rank.toFixed(3)}\n   extrait: ${(r.snippet || "").slice(0, 200)}`
      )
      .join("\n\n");

    try {
      synthesis = await callClaude(
        SYNTH_SYSTEM,
        `Question : ${query}\n\nMots-clés expansés : ${expandedTerms.join(", ")}\n\nRésultats de la recherche :\n${context}`,
        800
      );
    } catch (e: any) {
      synthError = String(e.message || e);
    }
  }

  return NextResponse.json({
    query,
    expandedTerms,
    expandError,
    results: dedupedScripts.slice(0, 20),
    fieldResults,
    synthesis,
    synthError,
    duration_ms: Date.now() - t0,
  });
}
