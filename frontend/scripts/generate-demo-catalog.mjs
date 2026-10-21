// Regenerates src/demo/catalog.json from the backend seed CSV (the same 41 synthetic laptops).
// Run from frontend/: node scripts/generate-demo-catalog.mjs
// Ids follow CSV order, matching the ids the backend assigns on a fresh import.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const csvPath = join(here, "../../backend/data/laptops.csv");
const outPath = join(here, "../src/demo/catalog.json");

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

const [header, ...lines] = parseCsv(readFileSync(csvPath, "utf8"));
const products = lines.map((values, i) => {
  const r = Object.fromEntries(header.map((h, j) => [h, (values[j] ?? "").trim()]));
  return {
    id: i + 1,
    sku: r.sku,
    name: r.name,
    brand: r.brand,
    price: Number(r.price),
    cpu: r.cpu,
    gpu: r.gpu,
    ram_gb: Number(r.ram_gb),
    storage_gb: Number(r.storage_gb),
    storage_type: r.storage_type || "SSD",
    display_size_in: Number(r.display_size_in),
    display_resolution: r.display_resolution,
    weight_kg: Number(r.weight_kg),
    battery_hours: r.battery_hours === "" ? null : Number(r.battery_hours),
    os: r.os,
    best_for: r.best_for.split(";").map((t) => t.trim()).filter(Boolean),
    description: r.description,
    source_name: r.source_name,
    source_url: r.source_url || null,
    is_mock: r.is_mock.toLowerCase() === "true",
  };
});
writeFileSync(outPath, JSON.stringify(products, null, 1) + "\n");
console.log(`Wrote ${products.length} products to ${outPath}`);
