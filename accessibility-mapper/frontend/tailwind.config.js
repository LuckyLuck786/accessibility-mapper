/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Barrier category palette (mirrors app/core/constants.py on the API)
        hazard: {
          critical: '#dc2626',
          high: '#ea580c',
          medium: '#f59e0b',
          low: '#eab308',
          info: '#64748b',
        },
        campus: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          500: '#0284c7',
          600: '#0369a1',
          700: '#075985',
          900: '#0c2340',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        panel: '0 10px 40px -12px rgba(12, 35, 64, 0.25)',
      },
    },
  },
  plugins: [],
}
