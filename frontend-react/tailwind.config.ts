/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        // Agent Builder custom palette
        'ab-purple': '#7C3AED',
        'ab-blue': '#2563EB',
        'ab-cyan': '#06B6D4',
        'ab-green': '#10B981',
        'ab-red': '#EF4444',
        'ab-yellow': '#F59E0B',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      keyframes: {
        'float-1': {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '50%': { transform: 'translate(-80px, 80px)' },
        },
        'float-2': {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '50%': { transform: 'translate(60px, -60px)' },
        },
        'float-3': {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '33%': { transform: 'translate(-40px, 50px)' },
          '66%': { transform: 'translate(40px, -30px)' },
        },
        shimmer: {
          '0%': { opacity: '0' },
          '50%': { opacity: '1' },
          '100%': { opacity: '0' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'float-1': 'float-1 20s ease-in-out infinite',
        'float-2': 'float-2 25s ease-in-out infinite',
        'float-3': 'float-3 30s ease-in-out infinite',
        shimmer: 'shimmer 1.5s infinite',
        'pulse-glow': 'pulse-glow 2s infinite',
        'slide-up': 'slide-up 0.3s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
