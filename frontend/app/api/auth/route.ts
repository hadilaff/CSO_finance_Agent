import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const { password } = await req.json();

  // APP_PASSWORD is a server-only env var (no NEXT_PUBLIC_ prefix)
  // It never reaches the browser
  const correct = process.env.APP_PASSWORD ?? "";

  if (!correct) {
    return NextResponse.json(
      { error: "APP_PASSWORD not configured on server." },
      { status: 500 }
    );
  }

  if (password !== correct) {
    return NextResponse.json({ error: "Incorrect password." }, { status: 401 });
  }

  return NextResponse.json({ ok: true });
}
