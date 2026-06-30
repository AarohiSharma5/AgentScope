/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Dark, developer-tool palette (GitHub/Vercel-ish).
        ink: {
          900: "#0a0a0b",
          800: "#111114",
          700: "#18181c",
          600: "#202026",
          500: "#2a2a31",
        },
        accent: {
          DEFAULT: "#6366f1",
          hover: "#7c7ef5",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
