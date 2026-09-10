import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.FORGET_LAH_API_PROXY ?? "http://127.0.0.1:8000";
const proxy = { "/api": target, "/health": target };
export default defineConfig({
  plugins: [react()],
  server: { strictPort: true, proxy },
  preview: { strictPort: true, proxy },
});
