/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#2563eb', hover: '#1d4ed8' },
        success: '#16a34a',
        warning: '#d97706',
        danger: '#dc2626',
      }
    }
  },
  plugins: [],
}
