import { createHmac } from "node:crypto";
import { auth } from "../../../../../auth";

export const runtime = "nodejs";

async function forward(request: Request, context: { params: { path: string[] } }) {
  const session = await auth();
  const email = session?.user?.email?.trim().toLowerCase();
  if (!email) return Response.json({ detail: "Sign in to manage saved searches" }, { status: 401 });

  const secret = process.env.PORTAL_IDENTITY_SECRET;
  if (!secret) return Response.json({ detail: "Saved search service is not configured" }, { status: 503 });

  const path = context.params.path.join("/");
  if (!/^saved-searches(?:\/\d+)?$/.test(path)) return Response.json({ detail: "Not found" }, { status: 404 });
  if (!["GET", "POST", "PATCH", "DELETE"].includes(request.method)) return new Response(null, { status: 405 });

  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = createHmac("sha256", secret).update(`${timestamp}.${email}`).digest("hex");
  const api = process.env.API_INTERNAL_URL || "http://localhost:8000";
  const target = `${api}/api/portal/${path}${new URL(request.url).search}`;
  const headers = new Headers({
    "X-Portal-Email": email,
    "X-Portal-Timestamp": timestamp,
    "X-Portal-Signature": signature,
  });
  if (request.headers.get("content-type")) headers.set("Content-Type", request.headers.get("content-type")!);

  const response = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "DELETE" ? undefined : await request.text(),
    cache: "no-store",
  });
  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
