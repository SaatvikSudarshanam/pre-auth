/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#0E9594",
          hover: "#0B7A79",
          soft: "#E6F4F4",
        },
        navy: "#0F2B46",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 43, 70, 0.04)",
        hover: "0 4px 16px rgba(15, 43, 70, 0.08)",
      },
    },
  },
  plugins: [],
};
