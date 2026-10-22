import { proxyApi } from "../../../src/api-proxy";

export async function GET() {
  return proxyApi("/demo/orders");
}
