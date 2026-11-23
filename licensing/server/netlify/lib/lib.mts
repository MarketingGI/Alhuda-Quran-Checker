import { getStore } from "@netlify/blobs";
import { createPrivateKey, sign, timingSafeEqual, createHash } from "node:crypto";

export const TOKEN_DAYS = 14;

export const store = () => getStore({ name: "lisensi", consistency: "strong" });

export const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

export const validMachineId = (s: unknown): s is string =>
  typeof s === "string" && /^[a-f0-9]{64}$/.test(s);

const clip = (s: unknown, n: number) =>
  typeof s === "string" ? s.replace(/[\u0000-\u001f<>]/g, "").slice(0, n) : "";
export { clip };

export function isAdmin(req: Request): boolean {
  const pw = Netlify.env.get("ADMIN_PASSWORD") ?? "";
  const got = req.headers.get("x-admin-password") ?? "";
  if (!pw || !got) return false;
  const a = createHash("sha256").update(pw).digest();
  const b = createHash("sha256").update(got).digest();
  return timingSafeEqual(a, b);
}

// Pembatas percobaan salah password admin (per IP, 10 kali / 15 menit)
export async function adminThrottled(ip: string): Promise<boolean> {
  const s = store();
  const key = "rl/" + createHash("sha256").update(ip).digest("hex").slice(0, 32);
  const rec = (await s.get(key, { type: "json" })) as { n: number; t: number } | null;
  const now = Date.now();
  return !!rec && now - rec.t < 15 * 60_000 && rec.n >= 10;
}
export async function adminFail(ip: string) {
  const s = store();
  const key = "rl/" + createHash("sha256").update(ip).digest("hex").slice(0, 32);
  const rec = (await s.get(key, { type: "json" })) as { n: number; t: number } | null;
  const now = Date.now();
  const n = rec && now - rec.t < 15 * 60_000 ? rec.n + 1 : 1;
  await s.setJSON(key, { n, t: rec && now - rec.t < 15 * 60_000 ? rec.t : now });
}

export function makeToken(machineId: string): { token: string; exp: number } {
  const keyB64 = Netlify.env.get("LICENSE_PRIVATE_KEY") ?? "";
  const key = createPrivateKey({ key: Buffer.from(keyB64, "base64"), format: "der", type: "pkcs8" });
  const now = Math.floor(Date.now() / 1000);
  const exp = now + TOKEN_DAYS * 86400;
  const payload = Buffer.from(JSON.stringify({ m: machineId, iat: now, exp })).toString("base64url");
  const sig = sign(null, Buffer.from(payload), key).toString("base64url");
  return { token: `${payload}.${sig}`, exp };
}
