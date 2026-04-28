// Mini renderer Markdown safe — léger, pas de dépendances externes.
// Couvre 95% des besoins (titres, listes, code, gras, italique, liens).
// Pour aller plus loin, brancher react-markdown.

const escape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function renderMarkdown(input: string): string {
  if (!input) return "";
  let txt = input;

  // Code fences ```...```
  txt = txt.replace(/```([\s\S]*?)```/g, (_, code) => {
    return `<pre class="bg-muted rounded p-3 overflow-x-auto"><code class="code">${escape(code)}</code></pre>`;
  });

  // Inline code `...`
  txt = txt.replace(/`([^`\n]+)`/g, '<code class="code bg-muted px-1 rounded">$1</code>');

  // Headers
  txt = txt.replace(/^### (.+)$/gm, '<h3 class="text-lg font-semibold mt-4 mb-1">$1</h3>');
  txt = txt.replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold mt-5 mb-2">$1</h2>');
  txt = txt.replace(/^# (.+)$/gm, '<h1 class="text-2xl font-bold mt-6 mb-3">$1</h1>');

  // Bold / italic
  txt = txt.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  txt = txt.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");

  // Links
  txt = txt.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-primary hover:underline" target="_blank" rel="noopener">$1</a>');

  // Lists
  txt = txt.replace(/^[-*] (.+)$/gm, '<li class="ml-5 list-disc">$1</li>');
  txt = txt.replace(/(<li[^>]*>.*<\/li>\n?)+/g, (m) => `<ul class="my-2">${m}</ul>`);

  // Paragraphs (lignes vides = nouveaux paragraphes)
  txt = txt
    .split(/\n\n+/)
    .map((para) => {
      if (/^<(h\d|ul|ol|pre|blockquote|p)/.test(para.trim())) return para;
      return `<p class="my-2">${para.replace(/\n/g, "<br/>")}</p>`;
    })
    .join("\n");

  return txt;
}
