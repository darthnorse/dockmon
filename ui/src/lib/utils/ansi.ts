/**
 * ANSI Escape Code to HTML Conversion Utility
 *
 * Converts ANSI escape codes in text to styled HTML spans for rendering
 * colored terminal output in the LogViewer component.
 *
 * Colors match the terminal theme from ContainerShellTab.tsx for consistency.
 *
 * Supports:
 * - Standard foreground colors (30-37)
 * - Bright foreground colors (90-97)
 * - Standard background colors (40-47)
 * - Bright background colors (100-107)
 * - Full 256-color mode (38;5;N and 48;5;N) - uses inline styles
 * - 24-bit true color mode (38;2;R;G;B and 48;2;R;G;B) - uses inline styles
 * - Text styles: bold (1), dim (2), italic (3), underline (4)
 * - Reset (0)
 */

// Maximum number of ANSI codes to process in a single escape sequence
// Prevents memory issues from maliciously crafted input with thousands of codes
const MAX_ANSI_CODES = 20

// Color names for standard ANSI colors (used for CSS class generation)
const COLOR_NAMES = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'] as const

// Standard colors (0-7) - matches ContainerShellTab.tsx theme
const STANDARD_COLORS = [
  '#18181b', // black
  '#ef4444', // red
  '#22c55e', // green
  '#eab308', // yellow
  '#3b82f6', // blue
  '#a855f7', // magenta
  '#06b6d4', // cyan
  '#e4e4e7', // white
] as const

// Bright colors (8-15) - matches ContainerShellTab.tsx theme
const BRIGHT_COLORS = [
  '#71717a', // bright black
  '#f87171', // bright red
  '#4ade80', // bright green
  '#facc15', // bright yellow
  '#60a5fa', // bright blue
  '#c084fc', // bright magenta
  '#22d3ee', // bright cyan
  '#fafafa', // bright white
] as const

/**
 * Convert a 256-color index to a hex color string
 *
 * 256-color palette:
 * - 0-7: Standard colors
 * - 8-15: Bright colors
 * - 16-231: 6x6x6 RGB cube
 * - 232-255: Grayscale (24 shades)
 */
function color256ToHex(index: number): string {
  // Standard colors (0-7)
  if (index >= 0 && index < 8) {
    return STANDARD_COLORS[index] as string
  }

  // Bright colors (8-15)
  if (index < 16) {
    return BRIGHT_COLORS[index - 8] as string
  }

  // 6x6x6 RGB cube (16-231)
  if (index < 232) {
    const cubeIndex = index - 16
    const r = Math.floor(cubeIndex / 36)
    const g = Math.floor((cubeIndex % 36) / 6)
    const b = cubeIndex % 6

    // Convert 0-5 to 0-255 (0, 95, 135, 175, 215, 255)
    const toRgb = (v: number) => (v === 0 ? 0 : 55 + v * 40)

    const rHex = toRgb(r).toString(16).padStart(2, '0')
    const gHex = toRgb(g).toString(16).padStart(2, '0')
    const bHex = toRgb(b).toString(16).padStart(2, '0')

    return `#${rHex}${gHex}${bHex}`
  }

  // Grayscale (232-255)
  // 24 shades from #080808 to #eeeeee
  const gray = 8 + (index - 232) * 10
  const grayHex = gray.toString(16).padStart(2, '0')
  return `#${grayHex}${grayHex}${grayHex}`
}

/**
 * Convert RGB values (0-255 each) to a hex color string
 *
 * Used for 24-bit true color ANSI sequences (38;2;R;G;B)
 */
function rgbToHex(r: number, g: number, b: number): string {
  // Clamp values to 0-255 range
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.floor(v)))
  const rHex = clamp(r).toString(16).padStart(2, '0')
  const gHex = clamp(g).toString(16).padStart(2, '0')
  const bHex = clamp(b).toString(16).padStart(2, '0')
  return `#${rHex}${gHex}${bHex}`
}

/**
 * Escape HTML entities to prevent XSS attacks
 *
 * MUST be called BEFORE converting ANSI codes to ensure user content
 * cannot become executable HTML.
 *
 * @param text - Raw text that may contain HTML special characters
 * @returns Text with HTML entities escaped
 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Represents the current text style state */
interface StyleState {
  fg: string | null // Foreground color (CSS class or inline style value)
  bg: string | null // Background color (CSS class or inline style value)
  fgInline: boolean // Whether fg is an inline style (vs CSS class)
  bgInline: boolean // Whether bg is an inline style (vs CSS class)
  bold: boolean
  dim: boolean
  italic: boolean
  underline: boolean
}

/** Create a fresh/reset style state */
function createEmptyStyle(): StyleState {
  return {
    fg: null,
    bg: null,
    fgInline: false,
    bgInline: false,
    bold: false,
    dim: false,
    italic: false,
    underline: false,
  }
}

/** Check if style state has any active styles */
function hasActiveStyles(style: StyleState): boolean {
  return !!(style.fg || style.bg || style.bold || style.dim || style.italic || style.underline)
}

/**
 * Generate opening span tag for current style state
 *
 * SECURITY NOTE: The style.fg and style.bg values used in inline styles are ONLY
 * set from controlled sources:
 *   1. Hardcoded CSS class names (e.g., 'ansi-fg-red') - not used in inline styles
 *   2. color256ToHex() output - produces validated hex colors from 0-255 indices
 *   3. rgbToHex() output - produces validated hex colors from clamped 0-255 RGB values
 * These values MUST NEVER be set directly from untrusted user input to prevent
 * CSS injection attacks via the style attribute.
 */
function styleToSpan(style: StyleState): string {
  const classes: string[] = []
  const inlineStyles: string[] = []

  // Foreground color
  if (style.fg) {
    if (style.fgInline) {
      inlineStyles.push(`color:${style.fg}`)
    } else {
      classes.push(style.fg)
    }
  }

  // Background color
  if (style.bg) {
    if (style.bgInline) {
      inlineStyles.push(`background-color:${style.bg}`)
    } else {
      classes.push(style.bg)
    }
  }

  // Text styles
  if (style.bold) classes.push('ansi-bold')
  if (style.dim) classes.push('ansi-dim')
  if (style.italic) classes.push('ansi-italic')
  if (style.underline) classes.push('ansi-underline')

  const classAttr = classes.length > 0 ? ` class="${classes.join(' ')}"` : ''
  const styleAttr = inlineStyles.length > 0 ? ` style="${inlineStyles.join(';')}"` : ''

  return `<span${classAttr}${styleAttr}>`
}

/**
 * Convert ANSI escape codes to HTML with styled spans
 *
 * @param text - Text containing ANSI escape codes
 * @returns HTML string with styled spans
 */
export function ansiToHtml(text: string): string {
  if (!text) return ''

  // Strip non-printable control characters (except ANSI escape sequences)
  // Keep: \x1b (ESC for ANSI), \t (tab), \n (newline)
  // Remove: other control chars like \x00-\x08, \x0b, \x0c, \x0e-\x1a, \x1c-\x1f
  const cleaned = text.replace(/[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]/g, '')

  // Escape HTML FIRST (security: prevent XSS)
  const escaped = escapeHtml(cleaned)

  // Track current style state
  let currentStyle = createEmptyStyle()
  let spanOpen = false

  // ANSI escape sequence pattern: ESC [ <params> m
  const ansiRegex = /\x1b\[([0-9;]*)m/g

  const result = escaped.replace(ansiRegex, (_match, params: string) => {
    // Empty params or just "0" means reset
    if (!params || params === '0') {
      currentStyle = createEmptyStyle()
      if (spanOpen) {
        spanOpen = false
        return '</span>'
      }
      return ''
    }

    // Limit number of codes to prevent memory issues with malicious input
    const codes = params.split(';').slice(0, MAX_ANSI_CODES).map(Number)
    let output = ''
    let i = 0

    // Process all codes in the sequence
    while (i < codes.length) {
      const code = codes[i]

      // Skip undefined/NaN codes
      if (code === undefined || isNaN(code)) {
        i++
        continue
      }

      // Reset (0) - close current span and reset style
      if (code === 0) {
        if (spanOpen) {
          output += '</span>'
          spanOpen = false
        }
        currentStyle = createEmptyStyle()
      }
      // Bold (1)
      else if (code === 1) {
        currentStyle.bold = true
      }
      // Dim (2)
      else if (code === 2) {
        currentStyle.dim = true
      }
      // Italic (3)
      else if (code === 3) {
        currentStyle.italic = true
      }
      // Underline (4)
      else if (code === 4) {
        currentStyle.underline = true
      }
      // Normal intensity (22) - removes bold and dim
      else if (code === 22) {
        currentStyle.bold = false
        currentStyle.dim = false
      }
      // Not italic (23)
      else if (code === 23) {
        currentStyle.italic = false
      }
      // Not underlined (24)
      else if (code === 24) {
        currentStyle.underline = false
      }
      // Standard foreground colors (30-37)
      else if (code >= 30 && code <= 37) {
        currentStyle.fg = `ansi-fg-${COLOR_NAMES[code - 30]}`
        currentStyle.fgInline = false
      }
      // Default foreground (39)
      else if (code === 39) {
        currentStyle.fg = null
        currentStyle.fgInline = false
      }
      // Standard background colors (40-47)
      else if (code >= 40 && code <= 47) {
        currentStyle.bg = `ansi-bg-${COLOR_NAMES[code - 40]}`
        currentStyle.bgInline = false
      }
      // Default background (49)
      else if (code === 49) {
        currentStyle.bg = null
        currentStyle.bgInline = false
      }
      // Bright foreground colors (90-97)
      else if (code >= 90 && code <= 97) {
        currentStyle.fg = `ansi-fg-bright-${COLOR_NAMES[code - 90]}`
        currentStyle.fgInline = false
      }
      // Bright background colors (100-107)
      else if (code >= 100 && code <= 107) {
        currentStyle.bg = `ansi-bg-bright-${COLOR_NAMES[code - 100]}`
        currentStyle.bgInline = false
      }
      // 256-color foreground (38;5;N)
      else if (code === 38 && codes[i + 1] === 5) {
        const colorIndex = codes[i + 2]
        if (colorIndex !== undefined && colorIndex >= 0 && colorIndex <= 255) {
          currentStyle.fg = color256ToHex(colorIndex)
          currentStyle.fgInline = true
        }
        i += 2 // Skip the "5" and color index
      }
      // 256-color background (48;5;N)
      else if (code === 48 && codes[i + 1] === 5) {
        const colorIndex = codes[i + 2]
        if (colorIndex !== undefined && colorIndex >= 0 && colorIndex <= 255) {
          currentStyle.bg = color256ToHex(colorIndex)
          currentStyle.bgInline = true
        }
        i += 2 // Skip the "5" and color index
      }
      // 24-bit true color foreground (38;2;R;G;B)
      else if (code === 38 && codes[i + 1] === 2) {
        const r = codes[i + 2]
        const g = codes[i + 3]
        const b = codes[i + 4]
        if (r !== undefined && g !== undefined && b !== undefined) {
          currentStyle.fg = rgbToHex(r, g, b)
          currentStyle.fgInline = true
        }
        i += 4 // Skip the "2", R, G, and B values
      }
      // 24-bit true color background (48;2;R;G;B)
      else if (code === 48 && codes[i + 1] === 2) {
        const r = codes[i + 2]
        const g = codes[i + 3]
        const b = codes[i + 4]
        if (r !== undefined && g !== undefined && b !== undefined) {
          currentStyle.bg = rgbToHex(r, g, b)
          currentStyle.bgInline = true
        }
        i += 4 // Skip the "2", R, G, and B values
      }

      i++
    }

    // After processing all codes, update the span
    // Close existing span if open
    if (spanOpen) {
      output += '</span>'
      spanOpen = false
    }

    // Open new span if we have active styles
    if (hasActiveStyles(currentStyle)) {
      output += styleToSpan(currentStyle)
      spanOpen = true
    }

    return output
  })

  // Close any remaining open span at the end
  if (spanOpen) {
    return result + '</span>'
  }

  return result
}
