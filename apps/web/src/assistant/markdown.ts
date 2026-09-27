import MarkdownIt from 'markdown-it'

const parser = new MarkdownIt({
  html: false,
  linkify: false,
  typographer: false,
})

const defaultValidateLink = parser.validateLink.bind(parser)
parser.validateLink = (url: string) => {
  const trimmed = url.trim()
  if (!trimmed || trimmed.startsWith('//')) return false
  if (trimmed.startsWith('#') || trimmed.startsWith('/') || trimmed.startsWith('./') || trimmed.startsWith('../')) {
    return defaultValidateLink(trimmed)
  }
  try {
    const protocol = new URL(trimmed).protocol
    return ['http:', 'https:', 'mailto:'].includes(protocol) && defaultValidateLink(trimmed)
  } catch {
    return false
  }
}

const defaultLinkOpen = parser.renderer.rules.link_open
parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  const token = tokens[index]
  const href = token.attrGet('href') ?? ''
  if (/^https?:\/\//i.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options)
}

// Remote images are intentionally not fetched from assistant-authored Markdown.
parser.renderer.rules.image = (tokens, index) => {
  const alt = parser.utils.escapeHtml(tokens[index].content)
  return alt ? `<span class="markdown-image-alt">[图片：${alt}]</span>` : ''
}

/** Render untrusted assistant text with raw HTML disabled and safe link protocols only. */
export function renderAssistantMarkdown(content: string): string {
  return parser.render(content)
}
