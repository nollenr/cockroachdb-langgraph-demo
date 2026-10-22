import { NextResponse } from "next/server";

import { proxyApi } from "../../../../src/api-proxy";

type RouteContext = { params: Promise<{ path: string[] }> };

function invalidPath(): NextResponse {
  return NextResponse.json({ detail: "ReturnFlow API route was not found" }, { status: 404 });
}

export async function GET(_request: Request, context: RouteContext) {
  const { path } = await context.params;
  if (path.length === 1) return proxyApi(`/returns/${encodeURIComponent(path[0])}`);
  if (path.length === 2 && path[1] === "inspection-sql") {
    return proxyApi(`/returns/${encodeURIComponent(path[0])}/inspection-sql`);
  }
  return invalidPath();
}

export async function DELETE(_request: Request, context: RouteContext) {
  const { path } = await context.params;
  if (path.length !== 1) return invalidPath();
  return proxyApi(`/returns/${encodeURIComponent(path[0])}`, { method: "DELETE" });
}

export async function POST(request: Request, context: RouteContext) {
  const { path } = await context.params;
  if (path.length !== 2) return invalidPath();
  if (path[1] === "manager-decision") {
    return proxyApi(`/returns/${encodeURIComponent(path[0])}/manager-decision`, {
      method: "POST",
      body: await request.text(),
    });
  }
  if (path[1] === "resume") {
    return proxyApi(`/returns/${encodeURIComponent(path[0])}/resume`, {
      method: "POST",
      body: await request.text(),
    });
  }
  return invalidPath();
}
