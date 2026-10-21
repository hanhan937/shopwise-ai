/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#14212B",
        paper: "#F2F5F6",
        line: "#D3DCE1",
        petrol: { DEFAULT: "#0B6B73", dark: "#084F55", tint: "#E2F0F1" },
        amber: { ink: "#7A4E00", tint: "#FBEFD0" },
        danger: { DEFAULT: "#A12A2A", tint: "#FBE9E9" },
      },
      fontFamily: {
        sans: ['"Schibsted Grotesk"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      borderRadius: { card: "10px", sheet: "16px" },
    },
  },
  plugins: [],
};
