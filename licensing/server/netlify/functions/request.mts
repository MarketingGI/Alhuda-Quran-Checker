import type { Config } from "@netlify/functions";
import { store, json, validMachineId, clip } from "../lib/lib.mts";

// POST /api/request  { machine_id, nama_pc, pengguna }
export default async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method" }, 405);
  let b: any;
  try { b = await req.json(); } catch { return json({ error: "json" }, 400); }
  if (!validMachineId(b.machine_id)) return json({ error: "machine_id" }, 400);
  const s = store();
  const key = "pc/" + b.machine_id;
  const rec = (await s.get(key, { type: "json" })) as any;
  if (rec) return json({ status: rec.status });
  await s.setJSON(key, {
    status: "pending",
    nama_pc: clip(b.nama_pc, 60),
    pengguna: clip(b.pengguna, 60),
    dibuat: new Date().toISOString(),
    terakhir: null,
  });
  return json({ status: "pending" });
};
export const config: Config = { path: "/api/request" };
