import type { Config, Context } from "@netlify/functions";
import { store, json, isAdmin, adminThrottled, adminFail, validMachineId } from "../lib/lib.mts";

// Semua perintah admin: header x-admin-password
// GET  /api/admin            -> daftar PC
// POST /api/admin {machine_id, aksi: approve|revoke|hapus}
export default async (req: Request, ctx: Context) => {
  const ip = ctx.ip ?? "?";
  if (await adminThrottled(ip)) return json({ error: "terlalu banyak percobaan" }, 429);
  if (!isAdmin(req)) { await adminFail(ip); return json({ error: "tidak berwenang" }, 401); }
  const s = store();
  if (req.method === "GET") {
    const { blobs } = await s.list({ prefix: "pc/" });
    const out = [];
    for (const b of blobs) {
      const r = (await s.get(b.key, { type: "json" })) as any;
      out.push({ machine_id: b.key.slice(3), ...r });
    }
    out.sort((a, b) => (a.dibuat < b.dibuat ? 1 : -1));
    return json({ pcs: out });
  }
  if (req.method === "POST") {
    let b: any;
    try { b = await req.json(); } catch { return json({ error: "json" }, 400); }
    if (!validMachineId(b.machine_id)) return json({ error: "machine_id" }, 400);
    const key = "pc/" + b.machine_id;
    const rec = (await s.get(key, { type: "json" })) as any;
    if (!rec) return json({ error: "tidak ada" }, 404);
    if (b.aksi === "approve") { rec.status = "approved"; rec.disetujui = new Date().toISOString(); }
    else if (b.aksi === "revoke") { rec.status = "revoked"; rec.dicabut = new Date().toISOString(); }
    else if (b.aksi === "hapus") { await s.delete(key); return json({ ok: true }); }
    else return json({ error: "aksi" }, 400);
    await s.setJSON(key, rec);
    return json({ ok: true, status: rec.status });
  }
  return json({ error: "method" }, 405);
};
export const config: Config = { path: "/api/admin" };
