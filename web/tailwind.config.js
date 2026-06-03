/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "hsl(220 16% 8%)",
        panel: "hsl(220 14% 11%)",
        border: "hsl(220 12% 22%)",
        muted: "hsl(220 8% 60%)",
        ink: "hsl(220 12% 92%)",
        accent: "hsl(190 90% 55%)",
        good: "hsl(140 70% 55%)",
        warn: "hsl(35 90% 60%)",
        bad: "hsl(0 70% 60%)",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "PingFang SC", "Microsoft YaHei"],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Code", "monospace"],
      },
    },
  },
  plugins: [],
};
