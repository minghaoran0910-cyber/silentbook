import { marked } from 'marked'
import sanitizeHtml from 'sanitize-html'

/**
 * AI 分析 markdown 渲染：先自处理 `**加粗**` 再交 marked。
 * 原因：CommonMark 的 emphasis 左右邻接规则要求 opener 后不能是标点——
 * AI 常输出中文+`¥-`紧贴的 `8月净流出**¥9,672**`，`¥` 是标点且前面是汉字，
 * marked 按规范拒绝解析，原样吐出星号。用正则先转 <strong> 再走标准管线。
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  const withStrong = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  return sanitizeHtml(marked.parse(withStrong) as string, {
    allowedTags: sanitizeHtml.defaults.allowedTags.concat(['img']),
    allowedAttributes: {
      a: ['href', 'title', 'target', 'rel'],
      img: ['src', 'alt', 'title'],
    },
    allowedSchemes: ['http', 'https', 'mailto'],
  })
}
