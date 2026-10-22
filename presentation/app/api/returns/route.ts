import { proxyApi } from "../../../src/api-proxy";

export async function POST(request: Request) {
  return proxyApi("/returns", { method: "POST", body: await request.text() });
}
