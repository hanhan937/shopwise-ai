/**
 * Static demo build (e.g. Cloudflare Pages): `VITE_DEMO_MODE=true npm run build`.
 * The app then never calls the backend or AWS: the catalog is bundled, and AI chat / AI comparison
 * return clearly labelled preset or rule-based examples. Real Bedrock runs only in the local Docker setup.
 */
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";
