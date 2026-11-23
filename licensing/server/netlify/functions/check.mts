import type { Config } from "@netlify/functions";
import { store, json, validMachineId, makeToken } from "../lib/lib.mts";

// POST /api/check { machine_id }  -> { status, token?, exp? }
export default async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method" }, 405);
  let b: any;
  try { b = await req.json(); } catch { return json({ error: "json" }, 400); }
  if (!validMachineId(b.machine_id)) return json({ error: "machine_id" }, 400);
  const s = store();
  const key = "pc/" + b.machine_id;
  const rec = (await s.get(key, { type: "json" })) as any;
  if (!rec) return json({ status: "unknown" });
  rec.terakhir = new Date().toISOString();
  await s.setJSON(key, rec);
  if (rec.status !== "approved") return json({ status: rec.status });
  const { token, exp } = makeToken(b.machine_id);
  return json({ status: "approved", token, exp });
};
export const config: Config = { path: "/api/check" };
