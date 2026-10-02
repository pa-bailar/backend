// Tiny DOM helpers.

export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing element #${id}`);
  return element as T;
}

const HTML_ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escape text before putting it inside an HTML template string. */
export function escapeHtml(text: string | null | undefined): string {
  return (text ?? "").replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}
