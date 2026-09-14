/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Care-Eat 브랜드 (네이비 · 블루)
        navy: {
          50: '#eef3fb', 100: '#d7e3f6', 200: '#b0c6ec', 300: '#7fa1de',
          400: '#4f79cc', 500: '#2979d4', 600: '#1151b8', 700: '#0d3f91',
          800: '#0a2e6e', 900: '#07204d', 950: '#04132e',
        },
        sky: {
          50: '#f0f7ff', 100: '#dcedff', 200: '#bcdcff', 300: '#8ec4ff',
          400: '#5aa5fb', 500: '#3585ef', 600: '#2069d2',
        },
        primary: { DEFAULT: '#1151b8', hover: '#0d3f91' },
        success: '#0f9d76',
        warning: '#d97706',
        danger: '#dc2626',
        ink: '#0f172a',
        muted: '#64748b',
      },
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(10,46,110,0.04), 0 8px 24px -12px rgba(10,46,110,0.18)',
        lift: '0 12px 32px -16px rgba(10,46,110,0.35)',
      },
      borderRadius: { xl2: '1.25rem' },
      backgroundImage: {
        'navy-grad': 'linear-gradient(135deg, #07204d 0%, #0a2e6e 45%, #1151b8 100%)',
        'blue-grad': 'linear-gradient(135deg, #1151b8 0%, #2979d4 100%)',
      },
    },
  },
  plugins: [],
}
