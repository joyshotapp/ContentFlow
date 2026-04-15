module.exports = {
  content: [
    "./src/contentflow/site/templates/**/*.html",
    "./src/contentflow/admin/templates/**/*.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "Noto Sans TC", "system-ui", "sans-serif"],
        serif: ["Noto Serif TC", "Georgia", "serif"],
      },
      colors: {
        brand: {
          50: "#EEF2FF",
          100: "#E0E7FF",
          200: "#C7D2FE",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
          800: "#3730A3",
          900: "#312E81",
        },
      },
      fontSize: {
        display: ["3.5rem", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "900" }],
      },
    },
  },
};