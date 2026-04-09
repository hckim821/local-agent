<template>
  <div ref="containerRef" class="markdown-body" v-html="html" />
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
  streaming?: boolean
}>()

const containerRef = ref<HTMLDivElement | null>(null)

const html = computed(() => renderMarkdown(props.content))

function attachCopyButtons() {
  if (!containerRef.value) return
  containerRef.value.querySelectorAll('pre').forEach((pre) => {
    if (pre.querySelector('.md-copy-btn')) return

    const btn = document.createElement('button')
    btn.className = 'md-copy-btn'
    btn.textContent = 'Copy'

    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code')?.innerText ?? ''
      try {
        await navigator.clipboard.writeText(code)
        btn.textContent = 'Copied!'
        btn.classList.add('copied')
        setTimeout(() => {
          btn.textContent = 'Copy'
          btn.classList.remove('copied')
        }, 2000)
      } catch {
        btn.textContent = 'Failed'
        setTimeout(() => { btn.textContent = 'Copy' }, 2000)
      }
    })

    pre.appendChild(btn)
  })
}

// Re-attach buttons whenever html updates (streaming chunks)
watch(html, () => nextTick(attachCopyButtons))
onMounted(() => nextTick(attachCopyButtons))
</script>

<style scoped>
/* ── Base ─────────────────────────────────────────────────────────────── */
.markdown-body {
  color: #e5e7eb;
  font-size: 0.875rem;
  line-height: 1.75;
  word-break: break-word;
}

/* ── Headings ─────────────────────────────────────────────────────────── */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  color: #f9fafb;
  font-weight: 700;
  line-height: 1.3;
  margin: 1.1em 0 0.4em;
}
.markdown-body :deep(h1) { font-size: 1.4em; border-bottom: 1px solid #2d3148; padding-bottom: 0.3em; }
.markdown-body :deep(h2) { font-size: 1.2em; border-bottom: 1px solid #1e2130; padding-bottom: 0.2em; }
.markdown-body :deep(h3) { font-size: 1.05em; }
.markdown-body :deep(h4) { font-size: 0.95em; }

/* ── Paragraph / list ─────────────────────────────────────────────────── */
.markdown-body :deep(p) { margin: 0.5em 0; }

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.6em;
  margin: 0.4em 0;
}
.markdown-body :deep(li) { margin: 0.2em 0; }
.markdown-body :deep(li > p) { margin: 0; }

/* ── Inline code ──────────────────────────────────────────────────────── */
.markdown-body :deep(code:not(pre code)) {
  background: #232638;
  color: #c084fc;
  padding: 0.15em 0.45em;
  border-radius: 5px;
  font-size: 0.85em;
  font-family: 'Consolas', 'Fira Code', 'Monaco', monospace;
  border: 1px solid #2d3148;
}

/* ── Code block ───────────────────────────────────────────────────────── */
.markdown-body :deep(pre) {
  background: #0d1117 !important;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 1em 1.1em 1em 1.1em;
  overflow-x: auto;
  position: relative;
  margin: 0.75em 0;
}
.markdown-body :deep(pre code) {
  background: none !important;
  padding: 0 !important;
  font-size: 0.82em;
  font-family: 'Consolas', 'Fira Code', 'Monaco', monospace;
  line-height: 1.6;
  border: none !important;
  color: #e6edf3;
}

/* ── Copy button ──────────────────────────────────────────────────────── */
.markdown-body :deep(.md-copy-btn) {
  position: absolute;
  top: 8px;
  right: 8px;
  background: #21262d;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 0.72rem;
  font-family: system-ui, sans-serif;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  user-select: none;
  line-height: 1.5;
}
.markdown-body :deep(.md-copy-btn:hover) {
  background: #30363d;
  color: #e6edf3;
  border-color: #58a6ff;
}
.markdown-body :deep(.md-copy-btn.copied) {
  background: #0f2f1a;
  color: #56d364;
  border-color: #238636;
}

/* ── Blockquote ───────────────────────────────────────────────────────── */
.markdown-body :deep(blockquote) {
  border-left: 3px solid #3b82f6;
  margin: 0.6em 0;
  padding: 0.3em 1em;
  color: #9ca3af;
  background: #141926;
  border-radius: 0 6px 6px 0;
}
.markdown-body :deep(blockquote p) { margin: 0; }

/* ── Table ────────────────────────────────────────────────────────────── */
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.75em 0;
  font-size: 0.84em;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #2d3148;
  padding: 0.45em 0.75em;
  text-align: left;
}
.markdown-body :deep(th) {
  background: #1a1d2b;
  color: #f3f4f6;
  font-weight: 600;
}
.markdown-body :deep(td) { background: #0f1117; }
.markdown-body :deep(tr:hover td) { background: #141622; }

/* ── Link ─────────────────────────────────────────────────────────────── */
.markdown-body :deep(a) {
  color: #58a6ff;
  text-decoration: none;
}
.markdown-body :deep(a:hover) { text-decoration: underline; }

/* ── HR ───────────────────────────────────────────────────────────────── */
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #2d3148;
  margin: 1em 0;
}

/* ── Strong / Em ──────────────────────────────────────────────────────── */
.markdown-body :deep(strong) { color: #f9fafb; font-weight: 700; }
.markdown-body :deep(em) { color: #d1d5db; }
</style>
