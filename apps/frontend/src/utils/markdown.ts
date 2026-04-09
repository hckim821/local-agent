import { marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'

// Configure once (ES module singleton)
marked.use(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    },
  })
)

marked.use({
  breaks: true,  // single newline → <br>
  gfm: true,     // GitHub Flavored Markdown
})

export function renderMarkdown(content: string): string {
  const result = marked.parse(content)
  return typeof result === 'string' ? result : ''
}
