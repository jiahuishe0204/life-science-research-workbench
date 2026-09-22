import { getStore } from "@edgeone/pages-blob";

const STORE_NAME = "life-science-workbench";

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff"
    }
  });
}

export async function onRequestGet(context) {
  // Use direct property access so the Makers bundler can detect every secret.
  // Only booleans are returned; secret values never leave the function.
  const configured = {
    DEEPSEEK_API_KEY: Boolean(context.env?.DEEPSEEK_API_KEY || process.env.DEEPSEEK_API_KEY),
    ADMIN_PASSWORD_HASH: Boolean(context.env?.ADMIN_PASSWORD_HASH || process.env.ADMIN_PASSWORD_HASH),
    ADMIN_SESSION_SECRET: Boolean(context.env?.ADMIN_SESSION_SECRET || process.env.ADMIN_SESSION_SECRET),
    ADMIN_TOTP_SECRET: Boolean(context.env?.ADMIN_TOTP_SECRET || process.env.ADMIN_TOTP_SECRET),
    TASK_ACCESS_TOKEN_SECRET: Boolean(context.env?.TASK_ACCESS_TOKEN_SECRET || process.env.TASK_ACCESS_TOKEN_SECRET)
  };

  try {
    const store = getStore({ name: STORE_NAME, consistency: "strong" });
    const checkedAt = new Date().toISOString();
    await store.setJSON("system/health.json", { checkedAt, schemaVersion: 1 });
    const saved = await store.get("system/health.json", {
      type: "json",
      consistency: "strong"
    });
    return json({
      ok: true,
      runtime: "edgeone-cloud-functions-node",
      storage: saved?.checkedAt === checkedAt ? "read_write" : "read_after_write_mismatch",
      configured,
      checked_at: checkedAt
    });
  } catch (error) {
    return json({
      ok: false,
      runtime: "edgeone-cloud-functions-node",
      storage: "unavailable",
      configured,
      error: error instanceof Error ? error.name : "StorageError"
    }, 503);
  }
}
