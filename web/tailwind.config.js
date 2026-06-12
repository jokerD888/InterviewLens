/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Archival / editorial palette — warm paper, ink, oxidised-rust accent.
        // Token names kept stable (bg/panel/ink/...) so component classes don't churn.
        bg: "hsl(40 33% 95%)", // warm paper
        paper: "hsl(40 33% 95%)",
        panel: "hsl(38 30% 91%)", // raised card / sidebar wash
        sunk: "hsl(38 26% 87%)", // inset wells
        border: "hsl(34 20% 80%)", // hairline rules
        rule: "hsl(30 14% 70%)", // stronger editorial rule
        muted: "hsl(28 10% 44%)", // secondary ink
        ink: "hsl(26 22% 15%)", // primary ink
        accent: "hsl(12 66% 46%)", // oxidised rust
        "accent-ink": "hsl(12 60% 34%)", // rust pressed / text-on-paper
        good: "hsl(150 40% 35%)",
        warn: "hsl(34 72% 42%)",
        bad: "hsl(2 62% 47%)",
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
        card: "0 1px 0 hsl(34 20% 80%), 0 1px 2px hsl(30 30% 30% / 0.04)",
        lift: "0 8px 30px -12px hsl(26 40% 20% / 0.18)",
      },
      letterSpacing: {
        masthead: "-0.02em",
      },
    },
  },
  plugins: [],
};
