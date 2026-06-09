/** Minimal markdown → HTML for agent output (no external deps). */
export function useMarkdown() {
  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  function render(src: string): string {
    if (!src) return ''
    let html = escapeHtml(src)

    // Headers
    html = html.replace(/^#### (.+)$/gm, '<h5>$1</h5>')
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>')
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>')

    // Bold / italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

    // Blockquote lines
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')

    // Horizontal rule
    html = html.replace(/^---$/gm, '<hr>')

    // Unordered lists (simple)
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)

    // Paragraphs
    html = html.split(/\n\n+/).map(block => {
      if (/^<(h[345]|ul|blockquote|hr)/.test(block.trim())) return block
      return `<p>${block.replace(/\n/g, '<br>')}</p>`
    }).join('\n')

    return html
  }

  return { render }
}
