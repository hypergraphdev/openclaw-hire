/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sand: "#f3ecdf",
        ink: "#112135",
        ember: "#d95f39",
        sea: "#1d6f7a",
        moss: "#647857",
      },
      boxShadow: {
        panel: "0 24px 60px rgba(17, 33, 53, 0.12)",
      },
      fontFamily: {
        display: ["Avenir Next", "Trebuchet MS", "sans-serif"],
        body: ["Helvetica Neue", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
};
