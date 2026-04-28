// API routes pour CRUD sur la doc d'un script.
// GET    /api/scripts/[id]/doc  → renvoie la doc actuelle (ou 404)
// PUT    /api/scripts/[id]/doc  → sauvegarde / crée
// DELETE /api/scripts/[id]/doc  → supprime
import { NextRequest, NextResponse } from "next/server";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const id = decodeURIComponent(params.id);
  const supabase = getServerClient();
  const { data, error } = await supabase
    .from("script_docs")
    .select("*")
    .eq("script_ns_id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? null);
}

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const id = decodeURIComponent(params.id);
  const body = await req.json();
  const supabase = getServerClient();

  const payload = {
    script_ns_id: id,
    business_purpose: body.business_purpose ?? null,
    technical_summary: body.technical_summary ?? null,
    usage_notes: body.usage_notes ?? null,
    tags: body.tags ?? [],
    related_scripts: body.related_scripts ?? [],
    content_md: body.content_md ?? null,
    status: body.status ?? "draft",
    ai_generated: body.ai_generated ?? false,
    ai_model: body.ai_model ?? null,
    authored_by: body.authored_by ?? null,
  };

  const { data, error } = await supabase
    .from("script_docs")
    .upsert(payload, { onConflict: "script_ns_id" })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  const id = decodeURIComponent(params.id);
  const supabase = getServerClient();
  const { error } = await supabase.from("script_docs").delete().eq("script_ns_id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
