const override = { wrapper: "cloudflare-node", converter: "edge", proxyExternalRequest: "fetch", incrementalCache: "dummy", tagCache: "dummy", queue: "dummy" };
const config = { default: { override }, edgeExternals: ["node:crypto"], middleware: { external: true, override: { ...override, wrapper: "cloudflare-edge" } } };
export default config;
