/**
 * Tailwind CSS Configuration
 * DockMon Design System v2
 *
 * ARCHITECTURE:
 * - Dark-first theme (Grafana/Portainer-inspired)
 * - Custom color tokens matching design system
 * - Inter (UI) + JetBrains Mono (code) fonts
 * - Responsive breakpoints for monitoring dashboards
 */

import type { Config } from 'tailwindcss'

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Custom color system - maps to CSS variables
        background: 'var(--bg)',
        surface: {
          1: 'var(--surface-1)',
          2: 'var(--surface-2)',
        },
        border: 'var(--border)',
        'border-color': 'var(--border-color)', // Alias for border utility
        input: 'var(--input)', // Input field background
        primary: 'var(--primary)', // Primary accent color
        text: {
          DEFAULT: 'var(--text)',
          muted: 'var(--text-muted)',
          tertiary: 'var(--text-tertiary)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          2: 'var(--accent-2)',
          3: 'var(--accent-3)',
        },
        semantic: {
          success: 'var(--success)',
          warning: 'var(--warning)',
          danger: 'var(--danger)',
          info: 'var(--info)',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'Noto Sans',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        // Explicit sizes from design system
        '2xl': ['1.75rem', { lineHeight: '2rem', fontWeight: '600' }], // Display
        'xl': ['1.25rem', { lineHeight: '1.75rem', fontWeight: '600' }], // Title
        'base': ['1rem', { lineHeight: '1.5rem' }], // Body
        'sm': ['0.875rem', { lineHeight: '1.25rem' }], // Body small
        'xs': ['0.75rem', { lineHeight: '1rem' }], // Caption
      },
      borderRadius: {
        '2xl': '1rem', // 16px - cards
        'xl': '0.75rem', // 12px - buttons
        'lg': '0.5rem', // 8px - inputs
      },
      spacing: {
        // Design system spacing scale (4px base)
        '18': '4.5rem', // 72px - collapsed sidebar
        '60': '15rem', // 240px - expanded sidebar
      },
      boxShadow: {
        'card': '0 6px 24px rgba(0, 0, 0, 0.35)',
      },
      animation: {
        'shimmer': 'shimmer 1.4s ease-in-out infinite',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
    screens: {
      // Responsive breakpoints from design system
      'sm': '640px',   // Mobile landscape
      'md': '768px',   // Tablet
      'lg': '1024px',  // Desktop
      'xl': '1280px',  // Large desktop
      '2xl': '1536px', // Ultra-wide
    },
  },
  plugins: [],
} satisfies Config
