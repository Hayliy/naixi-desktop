/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        sakura: {
          50: "#FFF0F5",
          100: "#FFE4EC",
          200: "#FFB7C5",
          300: "#FF8DA3",
          400: "#FF6B8A",
          500: "#FF4777",
          600: "#E8356B",
          700: "#CC2D5C",
          800: "#A62A4E",
          900: "#852644",
        },
        lavender: {
          50: "#F5F0FF",
          100: "#EDE0FF",
          200: "#D6B0FF",
          300: "#C080FF",
          400: "#A84FFF",
          500: "#8E24FF",
          600: "#7B1FA2",
          700: "#6A1B9A",
          800: "#5A158A",
          900: "#4A0E7A",
        },
      },
    },
  },
  plugins: [],
};
