import http from "node:http";
import https from "node:https";
import type { IncomingMessage } from "node:http";

interface PluginConfig {
  scraperUrl: string;
  username?: string;
  password?: string;
  defaultTimeout?: number;
  useInternalProxy?: boolean;
}

interface OpenClawPluginApi {
  pluginConfig: PluginConfig;
  registerTool(tool: unknown, opts?: unknown): void;
  registerService(desc: unknown): void;
  registerCli(fn: unknown, opts?: unknown): void;
  logger: {
    info(msg: string): void;
    warn(msg: string): void;
    error(msg: string): void;
  };
}

const PLUGIN_ID = "web-scraper";
const DEFAULT_TIMEOUT = 30;

function httpRequest(
  url: string,
  method: string,
  headers: Record<string, string>,
  body?: string,
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const mod = parsed.protocol === "https:" ? https : http;
    const req = mod.request(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname + parsed.search,
        method,
        headers,
        timeout: 60000,
      },
      (res: IncomingMessage) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => {
          resolve({
            status: res.statusCode || 0,
            body: Buffer.concat(chunks).toString("utf-8"),
          });
        });
      },
    );
    req.on("timeout", () => { req.destroy(new Error("Request timed out")); });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function makeAuthHeader(username?: string, password?: string): string {
  if (!username) return "";
  const creds = `${username}:${password || ""}`;
  return "Basic " + Buffer.from(creds).toString("base64");
}

async function scraperRequest(
  cfg: Partial<PluginConfig>,
  path: string,
  method: string,
  payload?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const base = (cfg.scraperUrl || "").replace(/\/+$/, "");
  const url = `${base}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const auth = makeAuthHeader(cfg.username, cfg.password);
  if (auth) headers["Authorization"] = auth;

  const body = payload ? JSON.stringify(payload) : undefined;
  const res = await httpRequest(url, method, headers, body);

  if (res.status === 401) {
    throw new Error(`Scraper auth failed (401). Check username/password in web-scraper plugin config.`);
  }
  if (res.status >= 400) {
    const detail = res.body.slice(0, 300);
    throw new Error(`Scraper returned HTTP ${res.status}: ${detail}`);
  }

  try {
    return JSON.parse(res.body) as Record<string, unknown>;
  } catch {
    return { _raw: res.body, _status: res.status };
  }
}

function directFetch(url: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve) => {
    const parsed = new URL(url);
    const mod = parsed.protocol === "https:" ? https : http;
    const req = mod.get(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname + parsed.search,
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
        timeout: timeoutMs,
      },
      (res: IncomingMessage) => {
        if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          directFetch(res.headers.location, timeoutMs).then(resolve).catch(() => resolve(""));
          return;
        }
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
        res.on("error", () => resolve(""));
      },
    );
    req.on("timeout", () => { req.destroy(); resolve(""); });
    req.on("error", () => resolve(""));
  });
}

function jsonResult(data: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    details: data,
  };
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

const plugin = {
  id: PLUGIN_ID,
  name: "Web Scraper",
  description:
    "Web scraping and search tools powered by pyUniBParcer (Botasaurus)",

  configSchema: {
    type: "object" as const,
    additionalProperties: false,
    properties: {
      scraperUrl: { type: "string" as const },
      username: { type: "string" as const },
      password: { type: "string" as const },
      defaultTimeout: { type: "number" as const },
      useInternalProxy: { type: "boolean" as const },
    },
    required: [] as const,
  },

  register(api: OpenClawPluginApi) {
    const cfg = (api.pluginConfig || {}) as Partial<PluginConfig>;
    const configured = Boolean(cfg.scraperUrl);
    const timeout = cfg.defaultTimeout || DEFAULT_TIMEOUT;

    if (!configured) {
      api.logger.warn(
        `[${PLUGIN_ID}] scraperUrl not configured — web_fetch/web_crawl_batch will return errors. web_search (ddgr) still works.`,
      );
    }

    // ── Tool: web_search (DuckDuckGo via ddgr) ──
    api.registerTool({
      name: "web_search",
      label: "Web Search",
      description:
        "Search the web using DuckDuckGo. Returns titles, URLs, and snippets for fast research.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Search query",
          },
          count: {
            type: "number",
            description: "Number of results (default 5, max 25)",
          },
        },
        required: ["query"],
      },
      async execute(_toolCallId: string, args: Record<string, unknown>) {
        const query = String(args.query || "");
        const n = Math.min(Number(args.count) || 5, 25);

        if (!query.trim()) {
          return jsonResult({ error: "empty_query", message: "Query is required." });
        }

        const { exec } = await import("node:child_process");
        const { promisify } = await import("node:util");
        const execAsync = promisify(exec);

        try {
          const escapedQuery = query.replace(/"/g, '\\"');
          const { stdout } = await execAsync(
            `ddgr --json -n ${n} "${escapedQuery}"`,
            { timeout: 20000, encoding: "utf-8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } },
          );
          const results = JSON.parse(stdout || "[]") as Array<{
            title: string;
            url: string;
            abstract: string;
          }>;
          return jsonResult({
            query,
            provider: "duckduckgo",
            count: results.length,
            results: results.map((r) => ({
              title: r.title,
              url: r.url,
              snippet: r.abstract,
            })),
          });
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          return jsonResult({
            query,
            provider: "duckduckgo",
            count: 0,
            results: [],
            error: msg,
          });
        }
      },
    });

    // ── Tool: web_fetch (via pyUniBParcer) ──
    api.registerTool({
      name: "web_fetch",
      label: "Web Fetch",
      description:
        "Fetch and extract readable content from a URL. Uses a remote scraper service with anti-bot protection, proxy rotation, and caching. Set waitFor to a CSS selector (e.g. 'body') to enable browser-based JS rendering for heavy sites like Yandex.",
      parameters: {
        type: "object",
        properties: {
          url: {
            type: "string",
            description: "URL to fetch",
          },
          extractMode: {
            type: "string",
            enum: ["text", "markdown"],
            description: "Extract mode: text (plain text) or markdown (default)",
          },
          maxChars: {
            type: "number",
            description: "Max characters to return (default 50000)",
          },
          waitFor: {
            type: "string",
            description:
              "CSS selector to wait for before extracting content. Enables browser (JS) rendering. Use 'body' for general JS sites. Without this, fast HTTP-only mode is used.",
          },
        },
        required: ["url"],
      },
      async execute(_toolCallId: string, args: Record<string, unknown>) {
        const url = String(args.url || "");
        const maxChars = Number(args.maxChars) || 50000;
        const waitFor = args.waitFor ? String(args.waitFor) : null;

        if (!url.trim()) {
          return jsonResult({ error: "missing_url", message: "URL is required." });
        }

        if (!configured) {
          return jsonResult({
            error: "not_configured",
            message: "Web scraper not configured. Set scraperUrl in web-scraper plugin config.",
          });
        }

        try {
          let content: Record<string, unknown> = {};
          let html = "";

          try {
            const res = await scraperRequest(cfg, "/crawl", "POST", {
              url,
              timeout: timeout,
              wait_for: waitFor,
              use_internal_proxy: cfg.useInternalProxy || false,
            });
            content = (res.content || {}) as Record<string, unknown>;
            html = String(content.content || "");
          } catch (scraperErr: unknown) {
            const scraperMsg = scraperErr instanceof Error ? scraperErr.message : String(scraperErr);
            const fallbackHtml = await directFetch(url, timeout * 1000);
            const fallbackText = fallbackHtml
              .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
              .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
              .replace(/<[^>]+>/g, " ")
              .replace(/\s+/g, " ")
              .trim()
              .slice(0, maxChars);

            if (fallbackText) {
              return jsonResult({
                url, finalUrl: url, status: "success", title: "",
                text: fallbackText, length: fallbackText.length,
                fetchedAt: new Date().toISOString(),
                note: "Fetched via direct HTTP (scraper error: " + scraperMsg.slice(0, 100) + ")",
              });
            }
            return jsonResult({ url, error: scraperMsg });
          }

          if (!html && !waitFor) {
            const directHtml = await directFetch(url, timeout * 1000);
            const directText = directHtml
              .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
              .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
              .replace(/<[^>]+>/g, " ")
              .replace(/\s+/g, " ")
              .trim()
              .slice(0, maxChars);

            if (directText) {
              return jsonResult({
                url,
                finalUrl: url,
                status: "success",
                title: "",
                text: directText,
                length: directText.length,
                fetchedAt: new Date().toISOString(),
                note: "Fetched via direct HTTP (scraper returned empty)",
              });
            }
          }

          const text = html
            .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
            .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, maxChars);

          return jsonResult({
            url,
            finalUrl: url,
            status: content.status || "success",
            title: content.title || "",
            text,
            length: text.length,
            fetchedAt: new Date().toISOString(),
          });
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          return jsonResult({ url, error: msg });
        }
      },
    });

    // ── Tool: web_crawl_batch ──
    api.registerTool({
      name: "web_crawl_batch",
      label: "Web Crawl Batch",
      description:
        "Fetch multiple URLs in parallel via the remote scraper service. Returns content for each URL.",
      parameters: {
        type: "object",
        properties: {
          urls: {
            type: "array",
            items: { type: "string" },
            description: "List of URLs to fetch",
          },
          timeout: {
            type: "number",
            description: "Timeout in seconds per URL (default 30)",
          },
        },
        required: ["urls"],
      },
      async execute(_toolCallId: string, args: Record<string, unknown>) {
        const urls = args.urls as string[];
        const reqTimeout = Number(args.timeout) || timeout;

        if (!configured) {
          return jsonResult({
            error: "not_configured",
            message: "Web scraper not configured. Set scraperUrl in web-scraper plugin config.",
          });
        }

        try {
          const res = await scraperRequest(cfg, "/crawl/batch", "POST", {
            urls,
            timeout: reqTimeout,
            use_internal_proxy: cfg.useInternalProxy || false,
          });
          return jsonResult(res);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          return jsonResult({ urls, error: msg });
        }
      },
    });

    // ── CLI: openclaw web-scraper status ──
    api.registerCli(
      ({ program }: { program: unknown }) => {
        const prog = program as {
          command(name: string): {
            description(desc: string): {
              command(name: string): {
                description(desc: string): {
                  action(fn: () => Promise<void>): void;
                };
              };
            };
          };
        };

        const cmd = prog
          .command("web-scraper")
          .description("Web Scraper utilities");

        cmd
          .command("status")
          .description("Check scraper service and DuckDuckGo health")
          .action(async () => {
            console.log(`Scraper: ${cfg.scraperUrl || "(not set)"}`);
            console.log(`Auth:    ${cfg.username ? "yes" : "no"}`);
            console.log(`Timeout: ${timeout}s`);
            console.log();

            try {
              const { exec } = await import("node:child_process");
              const { promisify } = await import("node:util");
              const execAsync = promisify(exec);
              await execAsync("ddgr --version", { timeout: 5000 });
              console.log("[ddgr]     OK (DuckDuckGo search available)");
            } catch {
              console.log("[ddgr]     MISSING (install: pip install ddgr)");
            }

            if (configured) {
              try {
                const res = await scraperRequest(cfg, "/health", "GET");
                const ok = res.status === "healthy";
                console.log(
                  `[scraper]  ${ok ? "OK" : "FAIL"} (${JSON.stringify(res)})`,
                );
              } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : String(e);
                console.log(`[scraper]  FAIL (${msg})`);
              }
            } else {
              console.log("[scraper]  NOT CONFIGURED");
            }
          });
      },
      { commands: ["web-scraper"] },
    );
  },
};

export default plugin;
