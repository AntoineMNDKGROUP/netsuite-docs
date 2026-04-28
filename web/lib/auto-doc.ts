// Auto-extraction d'une doc préliminaire à partir du code source du script.
// Utilisée comme valeur de départ quand on ouvre l'éditeur sur un script sans doc.

interface SourceFile {
  file_name: string | null;
  content: string | null;
  jsdoc: Record<string, any> | null;
}

interface Script {
  name: string;
  script_id: string | null;
  script_type: string | null;
}

const SCRIPT_TYPE_TAGS: Record<string, string[]> = {
  USEREVENT: ["User Event"],
  CLIENT: ["Client Script"],
  SCRIPTLET: ["Suitelet"],
  SCHEDULED: ["Scheduled"],
  MAPREDUCE: ["Map/Reduce", "Batch"],
  RESTLET: ["RESTlet", "API"],
  ACTION: ["Workflow Action"],
  MASSUPDATE: ["Mass Update"],
  PORTLET: ["Portlet"],
  BUNDLEINSTALLATION: ["Bundle Install"],
  EMAILCAPTURE: ["Email Capture"],
};

// Mots-clés métier qu'on cherche dans les noms / scriptid
const BUSINESS_KEYWORDS: Record<string, string> = {
  invoice: "Facturation",
  billing: "Facturation",
  payment: "Paiement",
  vendor: "Vendor",
  customer: "Client",
  order: "Commande",
  so_: "Sales Order",
  po_: "Purchase Order",
  edi: "EDI",
  ack: "Acknowledgement",
  digitec: "Digitec",
  dsv: "DSV",
  france: "France",
  fr_: "France",
  warehouse: "Warehouse",
  void: "Annulation",
  credit: "Crédit",
  hold: "Hold",
  sftp: "SFTP",
  shopify: "Shopify",
  abbyy: "OCR Abbyy",
  celigo: "Celigo",
  dad_: "Doc cabinet",
};


function inferTags(script: Script, src?: SourceFile): string[] {
  const tags = new Set<string>();
  // Type de script
  const fromType = SCRIPT_TYPE_TAGS[script.script_type ?? ""] ?? [];
  fromType.forEach((t) => tags.add(t));
  // JSDoc @NScriptType
  const ns = src?.jsdoc?.NScriptType;
  if (ns) tags.add(String(ns));
  // Business keywords du nom et scriptid
  const haystack = `${script.name ?? ""} ${script.script_id ?? ""} ${src?.file_name ?? ""}`.toLowerCase();
  for (const [kw, tag] of Object.entries(BUSINESS_KEYWORDS)) {
    if (haystack.includes(kw)) tags.add(tag);
  }
  return Array.from(tags);
}

function extractTechnicalSummary(src?: SourceFile): string {
  if (!src?.content) return "";
  // Premier bloc /** ... */ comme summary
  const m = src.content.match(/\/\*\*([\s\S]*?)\*\//);
  if (!m) return "";
  const block = m[1]
    .split("\n")
    .map((l) => l.replace(/^\s*\*\s?/, "").trim())
    .filter((l) => l && !l.startsWith("@"))
    .slice(0, 5)
    .join(" ");
  return block;
}

export function autoDocFromSource(script: Script, src?: SourceFile): {
  business_purpose: string;
  technical_summary: string;
  usage_notes: string;
  tags: string[];
  content_md: string;
} {
  const tags = inferTags(script, src);
  const techSummary = extractTechnicalSummary(src);
  const ns = src?.jsdoc ?? {};
  return {
    business_purpose: "",  // À compléter par l'utilisateur
    technical_summary: techSummary,
    usage_notes: "",
    tags,
    content_md: [
      `## ${script.name}`,
      "",
      `- **Script type** : \`${script.script_type ?? "—"}\``,
      `- **Script ID** : \`${script.script_id ?? "—"}\``,
      ns.NApiVersion ? `- **NetSuite API Version** : \`${ns.NApiVersion}\`` : null,
      ns.NScriptType ? `- **NetSuite Script Type** : \`${ns.NScriptType}\`` : null,
      ns.NModuleScope ? `- **Module Scope** : \`${ns.NModuleScope}\`` : null,
      "",
      "### Description technique extraite du code",
      "",
      techSummary || "_Aucun bloc JSDoc trouvé en tête du fichier._",
    ]
      .filter(Boolean)
      .join("\n"),
  };
}
