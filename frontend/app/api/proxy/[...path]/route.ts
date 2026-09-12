import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_URL ?? "http://localhost:8000";

async function handler(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const url      = `${BACKEND}/api/${path.join("/")}`;
  const headers  = new Headers(req.headers);
  headers.delete("host");

  try {
    const res = await fetch(url, {
      method:  req.method,
      headers,
      body:    req.method !== "GET" && req.method !== "HEAD" ? req.body : undefined,
      // @ts-ignore
      duplex:  "half",
    });

    const body = await res.arrayBuffer();
    return new NextResponse(body, {
      status:  res.status,
      headers: res.headers,
    });
  } catch (e: any) {
    return NextResponse.json(
      { error: `Backend unreachable: ${e.message}` },
      { status: 502 }
    );
  }
}

export const GET    = handler;
export const POST   = handler;
export const DELETE = handler;
export const PUT    = handler;
export const PATCH  = handler;
