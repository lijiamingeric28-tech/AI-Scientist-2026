/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'SF Pro Display', '-apple-system', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      colors: {
        sidebar: {
          bg: '#0f1011',
          hover: '#191a1b',
          active: '#232426',
          border: '#28282c',
        },
        surface: {
          DEFAULT: '#ffffff',
          secondary: '#f5f6f8',
          tertiary: '#f0f1f3',
          elevated: '#ffffff',
        },
        content: {
          DEFAULT: '#1a1d23',
          secondary: '#5f6572',
          tertiary: '#8b8f9a',
          placeholder: '#b0b4be',
        },
        accent: {
          DEFAULT: '#5e6ad2',
          hover: '#7170ff',
          light: '#ecedfa',
          text: '#4f5bc4',
        },
        status: {
          success: '#27a644',
          'success-bg': '#edf9f0',
          progress: '#3b82f6',
          'progress-bg': '#eff6ff',
          error: '#ef4444',
          'error-bg': '#fef2f2',
          waiting: '#9ca3af',
          'waiting-bg': '#f3f4f6',
        },
        border: {
          DEFAULT: '#e5e7eb',
          subtle: '#f0f1f3',
          strong: '#d1d5db',
        },
      },
      fontSize: {
        'display': ['2rem', { lineHeight: '1.1', letterSpacing: '-0.025em', fontWeight: '510' }],
        'h1': ['1.5rem', { lineHeight: '1.2', letterSpacing: '-0.02em', fontWeight: '510' }],
        'h2': ['1.25rem', { lineHeight: '1.3', letterSpacing: '-0.015em', fontWeight: '510' }],
        'h3': ['1.0625rem', { lineHeight: '1.4', letterSpacing: '-0.01em', fontWeight: '590' }],
        'body': ['0.9375rem', { lineHeight: '1.5', fontWeight: '400' }],
        'body-emphasis': ['0.9375rem', { lineHeight: '1.5', fontWeight: '510' }],
        'small': ['0.8125rem', { lineHeight: '1.5', letterSpacing: '0.01em', fontWeight: '400' }],
        'small-emphasis': ['0.8125rem', { lineHeight: '1.5', letterSpacing: '0.01em', fontWeight: '510' }],
        'caption': ['0.75rem', { lineHeight: '1.4', letterSpacing: '0.02em', fontWeight: '400' }],
        'caption-emphasis': ['0.75rem', { lineHeight: '1.4', letterSpacing: '0.02em', fontWeight: '510' }],
      },
      borderRadius: {
        'sm': '4px',
        'DEFAULT': '6px',
        'md': '8px',
        'lg': '12px',
        'xl': '16px',
      },
      boxShadow: {
        'sm': '0 1px 2px rgba(0,0,0,0.04)',
        'DEFAULT': '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        'md': '0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.04)',
        'lg': '0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -4px rgba(0,0,0,0.04)',
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        'cursor-blink': 'cursor-blink 1s step-end infinite',
        'slide-in-right': 'slide-in-right 0.2s ease-out',
        'fade-in': 'fade-in 0.15s ease-out',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'slide-in-right': {
          '0%': { transform: 'translateX(16px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
