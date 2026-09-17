import { describe, it, expect } from 'vitest'
import { escapeHtml, ansiToHtml } from './ansi'

describe('escapeHtml', () => {
  describe('XSS Prevention', () => {
    it('should escape < and > characters', () => {
      expect(escapeHtml('<script>alert("xss")</script>')).toBe(
        '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
      )
    })

    it('should escape ampersands', () => {
      expect(escapeHtml('foo & bar')).toBe('foo &amp; bar')
    })

    it('should escape quotes', () => {
      expect(escapeHtml('foo "bar" \'baz\'')).toBe('foo &quot;bar&quot; &#39;baz&#39;')
    })

    it('should escape all special characters together', () => {
      expect(escapeHtml('<div onclick="alert(\'xss\')">test & stuff</div>')).toBe(
        '&lt;div onclick=&quot;alert(&#39;xss&#39;)&quot;&gt;test &amp; stuff&lt;/div&gt;'
      )
    })

    it('should handle event handlers in attributes', () => {
      expect(escapeHtml('<img src="x" onerror="alert(1)">')).toBe(
        '&lt;img src=&quot;x&quot; onerror=&quot;alert(1)&quot;&gt;'
      )
    })
  })

  describe('Non-malicious content', () => {
    it('should pass through normal text unchanged', () => {
      expect(escapeHtml('Hello World')).toBe('Hello World')
    })

    it('should handle empty strings', () => {
      expect(escapeHtml('')).toBe('')
    })

    it('should preserve newlines and tabs', () => {
      expect(escapeHtml('line1\nline2\ttab')).toBe('line1\nline2\ttab')
    })
  })
})

describe('ansiToHtml', () => {
  describe('Empty/null input handling', () => {
    it('should handle empty string', () => {
      expect(ansiToHtml('')).toBe('')
    })

    it('should handle null-ish values', () => {
      expect(ansiToHtml(null as unknown as string)).toBe('')
      expect(ansiToHtml(undefined as unknown as string)).toBe('')
    })

    it('should pass through plain text without ANSI codes unchanged', () => {
      expect(ansiToHtml('Hello World')).toBe('Hello World')
    })
  })

  describe('XSS Prevention (Security Critical)', () => {
    it('should escape HTML in text before converting ANSI codes', () => {
      // Red script tag - should be escaped, not executable
      const malicious = '\x1b[31m<script>alert("xss")</script>\x1b[0m'
      const result = ansiToHtml(malicious)

      expect(result).toContain('&lt;script&gt;')
      expect(result).not.toContain('<script>')
    })

    it('should prevent XSS via img onerror', () => {
      const malicious = '\x1b[32m<img src=x onerror=alert(1)>\x1b[0m'
      const result = ansiToHtml(malicious)

      expect(result).toContain('&lt;img')
      expect(result).not.toContain('<img')
    })

    it('should escape quotes in colored text', () => {
      const malicious = '\x1b[33m" onclick="alert(1)\x1b[0m'
      const result = ansiToHtml(malicious)

      expect(result).toContain('&quot;')
      expect(result).not.toContain('" onclick')
    })

    it('should handle malicious content mixed with valid ANSI', () => {
      const malicious = '\x1b[1;31m<div onmouseover="alert(1)">hover me</div>\x1b[0m'
      const result = ansiToHtml(malicious)

      expect(result).toContain('&lt;div')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('ansi-fg-red')
    })
  })

  describe('Standard foreground colors (30-37)', () => {
    it('should render red text (31)', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-red">Red</span>')
    })

    it('should render green text (32)', () => {
      const result = ansiToHtml('\x1b[32mGreen\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-green">Green</span>')
    })

    it('should render yellow text (33)', () => {
      const result = ansiToHtml('\x1b[33mYellow\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-yellow">Yellow</span>')
    })

    it('should render blue text (34)', () => {
      const result = ansiToHtml('\x1b[34mBlue\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-blue">Blue</span>')
    })

    it('should render all standard colors', () => {
      const colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
      colors.forEach((color, i) => {
        const result = ansiToHtml(`\x1b[${30 + i}m${color}\x1b[0m`)
        expect(result).toContain(`ansi-fg-${color}`)
      })
    })
  })

  describe('Bright foreground colors (90-97)', () => {
    it('should render bright red text (91)', () => {
      const result = ansiToHtml('\x1b[91mBright Red\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-bright-red">Bright Red</span>')
    })

    it('should render bright green text (92)', () => {
      const result = ansiToHtml('\x1b[92mBright Green\x1b[0m')
      expect(result).toBe('<span class="ansi-fg-bright-green">Bright Green</span>')
    })

    it('should render all bright colors', () => {
      const colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
      colors.forEach((color, i) => {
        const result = ansiToHtml(`\x1b[${90 + i}m${color}\x1b[0m`)
        expect(result).toContain(`ansi-fg-bright-${color}`)
      })
    })
  })

  describe('Background colors (40-47, 100-107)', () => {
    it('should render red background (41)', () => {
      const result = ansiToHtml('\x1b[41mRed BG\x1b[0m')
      expect(result).toBe('<span class="ansi-bg-red">Red BG</span>')
    })

    it('should render bright blue background (104)', () => {
      const result = ansiToHtml('\x1b[104mBright Blue BG\x1b[0m')
      expect(result).toBe('<span class="ansi-bg-bright-blue">Bright Blue BG</span>')
    })

    it('should render foreground and background together', () => {
      const result = ansiToHtml('\x1b[31;44mRed on Blue\x1b[0m')
      expect(result).toContain('ansi-fg-red')
      expect(result).toContain('ansi-bg-blue')
    })
  })

  describe('Text styles', () => {
    it('should render bold text (1)', () => {
      const result = ansiToHtml('\x1b[1mBold\x1b[0m')
      expect(result).toBe('<span class="ansi-bold">Bold</span>')
    })

    it('should render dim text (2)', () => {
      const result = ansiToHtml('\x1b[2mDim\x1b[0m')
      expect(result).toBe('<span class="ansi-dim">Dim</span>')
    })

    it('should render italic text (3)', () => {
      const result = ansiToHtml('\x1b[3mItalic\x1b[0m')
      expect(result).toBe('<span class="ansi-italic">Italic</span>')
    })

    it('should render underlined text (4)', () => {
      const result = ansiToHtml('\x1b[4mUnderline\x1b[0m')
      expect(result).toBe('<span class="ansi-underline">Underline</span>')
    })

    it('should combine multiple styles', () => {
      const result = ansiToHtml('\x1b[1;3;4mBold Italic Underline\x1b[0m')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('ansi-italic')
      expect(result).toContain('ansi-underline')
    })

    it('should combine style with color', () => {
      const result = ansiToHtml('\x1b[1;31mBold Red\x1b[0m')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('ansi-fg-red')
    })
  })

  describe('Reset codes', () => {
    it('should handle reset (0) properly', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[0m Normal')
      expect(result).toBe('<span class="ansi-fg-red">Red</span> Normal')
    })

    it('should handle empty escape sequence as reset', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[m Normal')
      expect(result).toBe('<span class="ansi-fg-red">Red</span> Normal')
    })

    it('should handle reset mid-sequence (the bug fix)', () => {
      // This was the bug: \x1b[1;0;31m should reset at 0, then apply 31
      const result = ansiToHtml('\x1b[1;0;31mText\x1b[0m')
      // After reset at 0, only red should be applied (not bold)
      expect(result).toContain('ansi-fg-red')
      expect(result).not.toContain('ansi-bold')
    })

    it('should handle default foreground (39)', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[39m Default')
      // After 39, foreground should be reset but span should close
      expect(result).toContain('ansi-fg-red')
      expect(result).toContain('Red</span>')
    })

    it('should handle default background (49)', () => {
      const result = ansiToHtml('\x1b[41mRed BG\x1b[49m Default BG')
      expect(result).toContain('ansi-bg-red')
    })
  })

  describe('256-color mode (38;5;N and 48;5;N)', () => {
    it('should render 256-color foreground with inline style', () => {
      const result = ansiToHtml('\x1b[38;5;196mColor 196\x1b[0m')
      expect(result).toContain('style="color:')
    })

    it('should render 256-color background with inline style', () => {
      const result = ansiToHtml('\x1b[48;5;21mColor 21 BG\x1b[0m')
      expect(result).toContain('style="background-color:')
    })

    it('should map 256-color 0-7 to standard colors', () => {
      // Color 1 = red = #ef4444
      const result = ansiToHtml('\x1b[38;5;1mRed\x1b[0m')
      expect(result).toContain('#ef4444')
    })

    it('should map 256-color 8-15 to bright colors', () => {
      // Color 9 = bright red = #f87171
      const result = ansiToHtml('\x1b[38;5;9mBright Red\x1b[0m')
      expect(result).toContain('#f87171')
    })

    it('should handle RGB cube colors (16-231)', () => {
      // Color 196 = RGB(5,0,0) = bright red in the cube
      const result = ansiToHtml('\x1b[38;5;196mRGB Cube\x1b[0m')
      expect(result).toContain('style="color:#')
    })

    it('should handle grayscale colors (232-255)', () => {
      // Color 240 = gray
      const result = ansiToHtml('\x1b[38;5;240mGray\x1b[0m')
      expect(result).toContain('style="color:#')
    })

    it('should combine 256-color with standard styles', () => {
      const result = ansiToHtml('\x1b[1;38;5;196mBold Color 196\x1b[0m')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('style="color:')
    })
  })

  describe('Multiple colors in sequence', () => {
    it('should handle multiple colored segments', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[0m \x1b[32mGreen\x1b[0m \x1b[34mBlue\x1b[0m')
      expect(result).toBe(
        '<span class="ansi-fg-red">Red</span> <span class="ansi-fg-green">Green</span> <span class="ansi-fg-blue">Blue</span>'
      )
    })

    it('should handle color change without reset', () => {
      const result = ansiToHtml('\x1b[31mRed\x1b[32mGreen\x1b[0m')
      expect(result).toContain('ansi-fg-red')
      expect(result).toContain('ansi-fg-green')
    })
  })

  describe('Edge cases and malformed input', () => {
    it('should handle text without any ANSI codes', () => {
      expect(ansiToHtml('Plain text without colors')).toBe('Plain text without colors')
    })

    it('should handle ANSI codes at the very end without text', () => {
      const result = ansiToHtml('Text\x1b[31m')
      // Should have an unclosed span that gets closed at the end
      expect(result).toContain('Text')
      expect(result).toContain('<span')
      expect(result).toContain('</span>')
    })

    it('should handle ANSI codes at the very start without text after', () => {
      const result = ansiToHtml('\x1b[31m\x1b[0m')
      // Should produce empty result since no text between codes
      expect(result).toBe('<span class="ansi-fg-red"></span>')
    })

    it('should handle unknown/unsupported ANSI codes gracefully', () => {
      // Code 99 is not a standard color code
      const result = ansiToHtml('\x1b[99mUnknown\x1b[0m')
      expect(result).toContain('Unknown')
    })

    it('should strip non-printable control characters', () => {
      const result = ansiToHtml('Hello\x00\x01\x02World')
      expect(result).toBe('HelloWorld')
      expect(result).not.toContain('\x00')
    })

    it('should preserve tabs and newlines', () => {
      const result = ansiToHtml('Line1\n\tIndented')
      expect(result).toContain('\n')
      expect(result).toContain('\t')
    })

    it('should close all open spans at end of string', () => {
      // Unclosed span at end
      const result = ansiToHtml('\x1b[31mRed without reset')
      expect(result).toBe('<span class="ansi-fg-red">Red without reset</span>')
    })
  })

  describe('Real-world log examples', () => {
    it('should handle npm log output style', () => {
      const npmLog = '\x1b[32mnpm\x1b[0m \x1b[90minfo\x1b[0m lifecycle'
      const result = ansiToHtml(npmLog)
      expect(result).toContain('ansi-fg-green')
      expect(result).toContain('ansi-fg-bright-black')
    })

    it('should handle error log style', () => {
      const errorLog = '\x1b[1;31mERROR:\x1b[0m Something went wrong'
      const result = ansiToHtml(errorLog)
      expect(result).toContain('ansi-bold')
      expect(result).toContain('ansi-fg-red')
    })

    it('should handle Python logging colors', () => {
      // Python colorlog style
      const pythonLog = '\x1b[32mINFO\x1b[0m - \x1b[33mWARNING\x1b[0m - \x1b[31mERROR\x1b[0m'
      const result = ansiToHtml(pythonLog)
      expect(result).toContain('ansi-fg-green')
      expect(result).toContain('ansi-fg-yellow')
      expect(result).toContain('ansi-fg-red')
    })

    it('should handle docker compose style output', () => {
      const composeLog = '\x1b[36mweb_1\x1b[0m | Server started on port 3000'
      const result = ansiToHtml(composeLog)
      expect(result).toContain('ansi-fg-cyan')
    })
  })

  describe('Style reset codes (22, 23, 24)', () => {
    it('should remove bold with code 22', () => {
      const result = ansiToHtml('\x1b[1mBold\x1b[22m Normal\x1b[0m')
      // First span should have bold, after 22 it should not
      expect(result).toContain('ansi-bold')
      expect(result).toContain('Bold</span>')
    })

    it('should remove dim with code 22', () => {
      const result = ansiToHtml('\x1b[2mDim\x1b[22m Normal\x1b[0m')
      expect(result).toContain('ansi-dim')
      expect(result).toContain('Dim</span>')
    })

    it('should remove italic with code 23', () => {
      const result = ansiToHtml('\x1b[3mItalic\x1b[23m Normal\x1b[0m')
      expect(result).toContain('ansi-italic')
      expect(result).toContain('Italic</span>')
    })

    it('should remove underline with code 24', () => {
      const result = ansiToHtml('\x1b[4mUnderline\x1b[24m Normal\x1b[0m')
      expect(result).toContain('ansi-underline')
      expect(result).toContain('Underline</span>')
    })

    it('should handle combined style removal', () => {
      // Bold + Italic, then remove bold, keep italic
      const result = ansiToHtml('\x1b[1;3mBoth\x1b[22mJust Italic\x1b[0m')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('ansi-italic')
    })
  })

  describe('256-color edge cases and boundaries', () => {
    it('should handle color index 0 (black)', () => {
      const result = ansiToHtml('\x1b[38;5;0mBlack\x1b[0m')
      expect(result).toContain('#18181b') // Our theme black
    })

    it('should handle color index 7 (white - last standard)', () => {
      const result = ansiToHtml('\x1b[38;5;7mWhite\x1b[0m')
      expect(result).toContain('#e4e4e7') // Our theme white
    })

    it('should handle color index 8 (bright black - first bright)', () => {
      const result = ansiToHtml('\x1b[38;5;8mBright Black\x1b[0m')
      expect(result).toContain('#71717a') // Our theme bright black
    })

    it('should handle color index 15 (bright white - last bright)', () => {
      const result = ansiToHtml('\x1b[38;5;15mBright White\x1b[0m')
      expect(result).toContain('#fafafa') // Our theme bright white
    })

    it('should handle color index 16 (first RGB cube color)', () => {
      const result = ansiToHtml('\x1b[38;5;16mRGB 0,0,0\x1b[0m')
      expect(result).toContain('style="color:#000000"')
    })

    it('should handle color index 231 (last RGB cube color)', () => {
      const result = ansiToHtml('\x1b[38;5;231mRGB 5,5,5\x1b[0m')
      expect(result).toContain('style="color:#ffffff"')
    })

    it('should handle color index 232 (first grayscale)', () => {
      const result = ansiToHtml('\x1b[38;5;232mDark Gray\x1b[0m')
      expect(result).toContain('style="color:#080808"')
    })

    it('should handle color index 255 (last grayscale)', () => {
      const result = ansiToHtml('\x1b[38;5;255mLight Gray\x1b[0m')
      expect(result).toContain('style="color:#eeeeee"')
    })

    it('should handle malformed 256-color sequence (missing color index)', () => {
      const result = ansiToHtml('\x1b[38;5mMissing Index\x1b[0m')
      expect(result).toContain('Missing Index')
    })

    it('should handle 256-color background at boundaries', () => {
      const result = ansiToHtml('\x1b[48;5;196mRed BG\x1b[0m')
      expect(result).toContain('style="background-color:#')
    })
  })

  describe('24-bit true color mode (38;2;R;G;B and 48;2;R;G;B)', () => {
    it('should render 24-bit foreground color', () => {
      const result = ansiToHtml('\x1b[38;2;255;128;64mOrange\x1b[0m')
      expect(result).toContain('style="color:#ff8040"')
    })

    it('should render 24-bit background color', () => {
      const result = ansiToHtml('\x1b[48;2;0;128;255mBlue BG\x1b[0m')
      expect(result).toContain('style="background-color:#0080ff"')
    })

    it('should handle pure red (255,0,0)', () => {
      const result = ansiToHtml('\x1b[38;2;255;0;0mRed\x1b[0m')
      expect(result).toContain('style="color:#ff0000"')
    })

    it('should handle pure green (0,255,0)', () => {
      const result = ansiToHtml('\x1b[38;2;0;255;0mGreen\x1b[0m')
      expect(result).toContain('style="color:#00ff00"')
    })

    it('should handle pure blue (0,0,255)', () => {
      const result = ansiToHtml('\x1b[38;2;0;0;255mBlue\x1b[0m')
      expect(result).toContain('style="color:#0000ff"')
    })

    it('should handle black (0,0,0)', () => {
      const result = ansiToHtml('\x1b[38;2;0;0;0mBlack\x1b[0m')
      expect(result).toContain('style="color:#000000"')
    })

    it('should handle white (255,255,255)', () => {
      const result = ansiToHtml('\x1b[38;2;255;255;255mWhite\x1b[0m')
      expect(result).toContain('style="color:#ffffff"')
    })

    it('should clamp out-of-range values', () => {
      // Values > 255 should be clamped to 255
      const result = ansiToHtml('\x1b[38;2;300;400;500mClamped\x1b[0m')
      expect(result).toContain('style="color:#ffffff"')
    })

    it('should handle invalid ANSI sequences with negative values gracefully', () => {
      // Negative values are not valid ANSI - the regex won't match them
      // The sequence will be left unprocessed (not crash)
      const result = ansiToHtml('\x1b[38;2;-10;-20;-30mClamped\x1b[0m')
      expect(result).toContain('Clamped')
    })

    it('should combine 24-bit color with styles', () => {
      const result = ansiToHtml('\x1b[1;38;2;128;64;196mBold Purple\x1b[0m')
      expect(result).toContain('ansi-bold')
      expect(result).toContain('style="color:#8040c4"')
    })

    it('should handle both foreground and background 24-bit colors', () => {
      const result = ansiToHtml('\x1b[38;2;255;0;0;48;2;0;0;255mRed on Blue\x1b[0m')
      expect(result).toContain('color:#ff0000')
      expect(result).toContain('background-color:#0000ff')
    })

    it('should handle malformed 24-bit sequence (missing values)', () => {
      const result = ansiToHtml('\x1b[38;2;255;128mMissing Blue\x1b[0m')
      expect(result).toContain('Missing Blue')
    })
  })

  describe('Parameter limit protection', () => {
    it('should handle sequences with many parameters without crashing', () => {
      // Generate a sequence with 50 codes (more than MAX_ANSI_CODES=20)
      const manyCodes = Array(50).fill('1').join(';')
      const result = ansiToHtml(`\x1b[${manyCodes}mText\x1b[0m`)
      expect(result).toContain('Text')
    })
  })

  describe('Mixed CSS classes and inline styles', () => {
    it('should combine CSS class color with 256-color style', () => {
      // Standard color (CSS class) then 256-color (inline style)
      const result = ansiToHtml('\x1b[1;38;5;196mBold 256-color\x1b[0m')
      expect(result).toContain('class="ansi-bold"')
      expect(result).toContain('style="color:#')
    })

    it('should combine CSS class color with 24-bit style', () => {
      const result = ansiToHtml('\x1b[4;38;2;128;64;32mUnderline True Color\x1b[0m')
      expect(result).toContain('class="ansi-underline"')
      expect(result).toContain('style="color:#804020"')
    })
  })
})
