/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Archival / editorial palette — warm paper, ink, oxidised-rust accent.
        // Values are stored as HSL *channels* in CSS variables (see globals.css)
        // so Tailwind alpha modifiers (bg-ink/80) and the `dark` class both work.
        bg: "hsl(var(--c-bg) / <alpha-value>)",
        paper: "hsl(var(--c-paper) / <alpha-value>)",
        panel: "hsl(var(--c-panel) / <alpha-value>)",
        sunk: "hsl(var(--c-sunk) / <alpha-value>)",
        border: "hsl(var(--c-border) / <alpha-value>)",
        rule: "hsl(var(--c-rule) / <alpha-value>)",
        muted: "hsl(var(--c-muted) / <alpha-value>)",
        ink: "hsl(var(--c-ink) / <alpha-value>)",
        accent: "hsl(var(--c-accent) / <alpha-value>)",
        "accent-ink": "hsl(var(--c-accent-ink) / <alpha-value>)",
        good: "hsl(var(--c-good) / <alpha-value>)",
        warn: "hsl(var(--c-warn) / <alpha-value>)",
        bad: "hsl(var(--c-bad) / <alpha-value>)",
      },
      fontFamily: {
        // display = characterful serif for mastheads & headings (Fraunces).
        // serif   = editorial body (Newsreader + Noto Serif SC for CJK).
        // mono    = catalog numerals, labels, taxonomy chrome (IBM Plex Mono).
        display: ['"Fraunces"', '"Noto Serif SC"', "Georgia", "serif"],
        serif: ['"Newsreader"', '"Noto Serif SC"', "Georgia", "serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ['"Newsreader"', '"Noto Serif SC"', "Georgia", "serif"],
      },
      boxShadow: {
        card: "0 1px 0 hsl(var(--c-border)), 0 1px 2px hsl(30 30% 30% / 0.04)",
        lift: "0 8px 30px -12px hsl(26 40% 20% / 0.18)",
      },
      letterSpacing: {
        masthead: "-0.02em",
      },
    },
  },
  plugins: [],
};
