// Génère une suggestion de doc via Claude API à partir du code source du script.
// POST /api/scripts/[id]/ai-suggest

import { NextRequest, NextResponse } from "next/server";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 60;

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6";

const SYSTEM_PROMPT = `Tu es un expert NetSuite SuiteScript chargé de documenter le code d'un compte client.
On te donne le code source d'un script SuiteScript et son contexte (type, déploiements, custom fields référencés).
Tu réponds en français, en JSON strict avec ces clés exactement :
{
  "business_purpose": "1-2 phrases : à quoi sert ce script du point de vue métier (français)",
  "technical_summary": "3-6 lignes : comment il fonctionne techniquement (modules N/ utilisés, logique principale)",
  "usage_notes": "1-3 phrases : quand il tourne, qui doit s'en occuper, points d'attention",
  "tags": ["tag1", "tag2"]
}
Sois concret et factuel. Si tu n'es pas sûr, marque "(à confirmer)" plutôt que d'inventer.
Pas de commentaires en dehors du JSON.`;

export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  if (!ANTHROPIC_API_KEY) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEY manquante côté serveur (à ajouter dans .env.local)" },
      { status: 500 }
    );
  }

  const id = decodeURIComponent(params.id);
  const supabase = getServerClient();

  const [{ data: script }, { data: src }] = await Promise.all([
    supabase.from("scripts").select("*").eq("ns_internal_id", id).maybeSingle(),
    supabase
      .from("script_source_files")
      .select("file_name,content,jsdoc")
      .eq("script_ns_id", id)
      .maybeSingle(),
  ]);

  if (!script) return NextResponse.json({ error: "Script not found" }, { status: 404 });

  const code = src?.content ?? "";
  if (!code) {
    return NextResponse.json(
      { error: "Aucun code source disponible pour ce script (script_files pas extrait ?)" },
      { status: 400 }
    );
  }

  // Limite la taille du code envoyé (claude max ~200k tokens, mais coût)
  const MAX_CODE_CHARS = 30000;
  const codeForPrompt = code.length > MAX_CODE_CHARS ? code.slice(0, MAX_CODE_CHARS) + "\n... (tronqué)" : code;

  const userMessage = `Voici le contexte d'un script NetSuite et son code source.

# Métadonnées
- Nom : ${script.name}
- Script ID : ${script.script_id}
- Type : ${script.script_type}
- API Version : ${script.api_version ?? "—"}
- Fichier : ${src?.file_name ?? "—"}
- JSDoc tags extraits : ${JSON.stringify(src?.jsdoc ?? {})}

# Code source
\`\`\`javascript
${codeForPrompt}
\`\`\`

Génère la doc demandée au format JSON.`;

  try {
    const apiResp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 1024,
        system: SYSTEM_PROMPT,
        messages: [{ role: "user", content: userMessage }],
      }),
    });

    if (!apiResp.ok) {
      const text = await apiResp.text();
      return NextResponse.json(
        { error: `Anthropic API ${apiResp.status}: ${text.slice(0, 300)}` },
        { status: 500 }
      );
    }

    const data = await apiResp.json();
    const text = data.content?.[0]?.text ?? "";

    // Parse le JSON renvoyé par Claude
    let parsed: any;
    try {
      // Cherche un bloc JSON même s'il y a du texte autour
      const m = text.match(/\{[\s\S]*\}/);
      parsed = JSON.parse(m ? m[0] : text);
    } catch (e) {
      return NextResponse.json(
        { error: "Réponse Claude non-parsable", raw: text.slice(0, 500) },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ...parsed,
      ai_generated: true,
      ai_model: MODEL,
      raw_excerpt: text.slice(0, 800),
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e.message ?? e) }, { status: 500 });
  }
}
