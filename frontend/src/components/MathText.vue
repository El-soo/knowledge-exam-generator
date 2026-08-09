<template>
  <span class="math-text" v-html="rendered" />
</template>

<script setup>
import { computed } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  text: { type: [String, Number], default: '' }
})

const escapeHtml = value => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;')

const repairLatex = value => String(value ?? '')
  .replaceAll('\u000crac', '\\frac')
  .replaceAll('\u0008egin', '\\begin')
  .replaceAll('\u0008eta', '\\beta')
  .replaceAll('\t' + 'an', '\\tan')
  .replaceAll('\t' + 'ext', '\\text')
  .replaceAll('\t' + 'imes', '\\times')
  .replaceAll('\t' + 'heta', '\\theta')
  .replaceAll('\n' + 'eq', '\\neq')
  .replaceAll('\r' + 'ight', '\\right')

const renderMath = (source, displayMode) => {
  try {
    return katex.renderToString(source.trim(), {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
      output: 'htmlAndMathml'
    })
  } catch {
    return escapeHtml(source)
  }
}

const renderMathText = value => {
  const text = repairLatex(value)
  const delimiter = /(\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\\\([\s\S]*?\\\)|\$(?!\$)[^$\n]+?\$)/g
  let html = ''
  let cursor = 0
  for (const match of text.matchAll(delimiter)) {
    html += escapeHtml(text.slice(cursor, match.index)).replaceAll('\n', '<br>')
    const token = match[0]
    const displayMode = token.startsWith('$$') || token.startsWith('\\[')
    const expression = token.startsWith('$$') || token.startsWith('\\(') || token.startsWith('\\[')
      ? token.slice(2, -2)
      : token.slice(1, -1)
    html += renderMath(expression, displayMode)
    cursor = match.index + token.length
  }
  html += escapeHtml(text.slice(cursor)).replaceAll('\n', '<br>')
  return html
}

const rendered = computed(() => renderMathText(props.text))
</script>

<style scoped>
.math-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.math-text :deep(.katex-display) { margin: .45em 0; overflow-x: auto; overflow-y: hidden; }
</style>
