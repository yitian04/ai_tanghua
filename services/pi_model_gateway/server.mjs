import { createServer } from "node:http";
import { mkdir, readFile, rename, writeFile, chmod } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import { builtinModels } from "@earendil-works/pi-ai/providers/all";


const SERVICE_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = resolve(SERVICE_DIR, "..", "..");
const DATA_DIR = resolve(ROOT_DIR, "data", "model_gateway");
const CREDENTIAL_PATH = resolve(DATA_DIR, "credentials.json");
const HOST_ID_PATH = resolve(DATA_DIR, "host_id.txt");
const TOKEN_PATH = resolve(DATA_DIR, "gateway_token.txt");
const PORT = Number(process.env.TANGHUA_MODEL_GATEWAY_PORT || 8766);
const HOST = "127.0.0.1";


class JsonCredentialStore {
  constructor(path) {
    this.path = path;
    this.locks = new Map();
  }

  async read(providerId) {
    const values = await this.#readAll();
    return values[providerId];
  }

  async list() {
    const values = await this.#readAll();
    return Object.entries(values).map(([providerId, credential]) => ({
      providerId,
      type: credential.type,
    }));
  }

  async modify(providerId, fn) {
    return this.#serialized(providerId, async () => {
      const values = await this.#readAll();
      const next = await fn(values[providerId]);
      if (next !== undefined) {
        values[providerId] = next;
        await this.#writeAll(values);
      }
      return next ?? values[providerId];
    });
  }

  async delete(providerId) {
    await this.#serialized(providerId, async () => {
      const values = await this.#readAll();
      delete values[providerId];
      await this.#writeAll(values);
    });
  }

  async #serialized(providerId, operation) {
    const previous = this.locks.get(providerId) ?? Promise.resolve();
    const queued = (async () => {
      await previous.catch(() => {});
      return operation();
    })();
    const tail = queued.catch(() => {});
    this.locks.set(providerId, tail);
    void tail.then(() => {
      if (this.locks.get(providerId) === tail) this.locks.delete(providerId);
    });
    return queued;
  }

  async #readAll() {
    try {
      const raw = await readFile(this.path, "utf8");
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
      if (error?.code === "ENOENT") return {};
      throw error;
    }
  }

  async #writeAll(values) {
    await mkdir(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(values, null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, this.path);
    try {
      await chmod(this.path, 0o600);
    } catch {
      // Windows does not implement POSIX file modes; the file remains under the user's profile/workspace.
    }
  }
}


const credentials = new JsonCredentialStore(CREDENTIAL_PATH);
const models = builtinModels({
  credentials,
  identity: {
    userAgent: "detailed",
    version: "0.1.0",
    attribution: {
      name: "Tanghua Robot",
      url: "https://github.com/earendil-works/pi",
      categories: ["creative-tool"],
    },
  },
});
const oauthSessions = new Map();


async function stableHostId() {
  await mkdir(DATA_DIR, { recursive: true });
  try {
    return (await readFile(HOST_ID_PATH, "utf8")).trim();
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    const value = `urn:uuid:${randomUUID()}`;
    await writeFile(HOST_ID_PATH, `${value}\n`, { mode: 0o600 });
    return value;
  }
}


async function gatewayToken() {
  const fromEnv = String(process.env.TANGHUA_MODEL_GATEWAY_TOKEN || "").trim();
  if (fromEnv) return fromEnv;
  await mkdir(DATA_DIR, { recursive: true });
  try {
    return (await readFile(TOKEN_PATH, "utf8")).trim();
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    const value = randomUUID().replaceAll("-", "") + randomUUID().replaceAll("-", "");
    await writeFile(TOKEN_PATH, `${value}\n`, { mode: 0o600 });
    return value;
  }
}


async function providerRows() {
  const rows = [];
  for (const provider of models.getProviders()) {
    const configured = await models.checkAuth(provider.id).catch(() => undefined);
    const imageModels = models.getModelsOfType("image", provider.id);
    rows.push({
      id: provider.id,
      name: provider.name,
      configured: Boolean(configured),
      authSource: configured?.source ?? "",
      authType: configured?.type ?? "",
      apiKey: Boolean(provider.auth.apiKey),
      oauth: Boolean(provider.auth.oauth),
      oauthLabel: provider.auth.oauth?.loginLabel ?? provider.auth.oauth?.name ?? "",
      subscription: Boolean(provider.auth.oauth?.isSubscription),
      imageModelCount: imageModels.length,
    });
  }
  return rows;
}


function imageModelRows(providerId = "") {
  return models
    .getModelsOfType("image", providerId || undefined)
    .map((model) => ({
      providerId: model.provider,
      id: model.id,
      name: model.name,
      api: model.api,
      baseUrl: model.baseUrl,
      input: model.input,
      output: model.output,
      supportsReferenceImage: model.input.includes("image"),
      cost: model.cost,
    }));
}


export async function requestOpenRouterImages(
  { model, prompt, images = [], apiKey, baseUrl, headers = {} },
  fetchImpl = globalThis.fetch,
) {
  if (!apiKey) throw new Error("OpenRouter 尚未登录或 API Key 无效。 ");
  const endpoint = `${String(baseUrl || "https://openrouter.ai/api/v1").replace(/\/+$/, "")}/images`;
  const payload = {
    model: model.id,
    prompt,
  };
  if (images.length) {
    payload.input_references = images.map((item) => ({
      type: "image_url",
      image_url: {
        url: `data:${requiredString(item.mimeType, "images[].mimeType")};base64,${requiredString(item.data, "images[].data")}`,
      },
    }));
  }

  const response = await fetchImpl(endpoint, {
    method: "POST",
    headers: {
      ...headers,
      Authorization: `Bearer ${apiKey}`,
      Accept: "application/json",
      "Content-Type": "application/json",
      "HTTP-Referer": "https://github.com/earendil-works/pi",
      "X-OpenRouter-Title": "Tanghua Robot",
    },
    body: JSON.stringify(payload),
  });
  const raw = await response.text();
  let result;
  try {
    result = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(`OpenRouter 图片接口返回了无效数据（HTTP ${response.status}）。`);
  }
  if (!response.ok) {
    const detail = result?.error?.message || result?.message || raw || response.statusText;
    throw new HttpError(response.status, `OpenRouter 图片生成失败：${detail}`);
  }
  const output = (Array.isArray(result.data) ? result.data : [])
    .filter((item) => item && typeof item.b64_json === "string" && item.b64_json.length > 0)
    .map((item) => ({
      type: "image",
      data: item.b64_json,
      mimeType: typeof item.media_type === "string" ? item.media_type : "image/png",
    }));
  if (!output.length) throw new Error("OpenRouter 图片接口没有返回图像数据。 ");
  return {
    providerId: model.provider,
    modelId: model.id,
    responseId: typeof result.id === "string" ? result.id : "",
    usage: result.usage && typeof result.usage === "object" ? result.usage : {},
    images: output,
    text: "",
  };
}


async function beginOAuth(providerId) {
  const provider = models.getProvider(providerId);
  if (!provider?.auth.oauth) throw new Error("该服务商不支持 OAuth/订阅登录。 ");
  const id = randomUUID();
  const hostId = await stableHostId();
  const controller = new AbortController();
  const session = {
    id,
    providerId,
    status: "starting",
    events: [],
    prompt: null,
    promptResolve: null,
    error: "",
    controller,
    hostId,
    createdAt: Date.now(),
  };
  oauthSessions.set(id, session);

  const interaction = {
    signal: controller.signal,
    notify(event) {
      session.events.push({ ...event, at: Date.now() });
      if (session.events.length > 30) session.events.shift();
      session.status = "waiting";
    },
    prompt(prompt) {
      session.status = "needs_input";
      session.prompt = {
        type: prompt.type,
        message: prompt.message,
        placeholder: prompt.placeholder ?? "",
        options: prompt.options ?? [],
      };
      return new Promise((resolvePrompt, rejectPrompt) => {
        session.promptResolve = resolvePrompt;
        const signal = prompt.signal;
        if (signal) {
          signal.addEventListener("abort", () => rejectPrompt(new Error("输入已取消")), { once: true });
        }
      });
    },
  };

  models
    .login(providerId, "oauth", interaction, {
      getDeviceId: () => session.hostId,
      agentName: "Tanghua Robot",
    })
    .then(() => {
      session.status = "complete";
      session.prompt = null;
      session.promptResolve = null;
    })
    .catch((error) => {
      session.status = controller.signal.aborted ? "cancelled" : "error";
      session.error = error instanceof Error ? error.message : String(error);
      session.prompt = null;
      session.promptResolve = null;
    });

  return sessionView(session);
}


function sessionView(session) {
  return {
    id: session.id,
    providerId: session.providerId,
    status: session.status,
    events: session.events,
    prompt: session.prompt,
    error: session.error,
    createdAt: session.createdAt,
  };
}


async function route(method, path, query, body) {
  if (method === "GET" && path === "/health") {
    return {
      ok: true,
      service: "pi-model-gateway",
      piVersion: "1.4.0",
      imageTransport: "openrouter-images-v1",
    };
  }
  if (method === "GET" && path === "/providers") {
    return { providers: await providerRows() };
  }
  if (method === "GET" && path === "/models") {
    return { models: imageModelRows(query.get("provider") ?? "") };
  }
  if (method === "POST" && path === "/auth/api-key") {
    const providerId = requiredString(body.providerId, "providerId");
    const key = requiredString(body.apiKey, "apiKey");
    const provider = models.getProvider(providerId);
    if (!provider) throw new Error("未知模型服务商。 ");
    if (!provider.auth.apiKey) throw new Error("该服务商不支持 API Key 登录。 ");
    await credentials.modify(providerId, async () => ({ type: "api_key", key }));
    return { ok: true, providerId };
  }
  if (method === "POST" && path === "/auth/logout") {
    const providerId = requiredString(body.providerId, "providerId");
    await models.logout(providerId);
    return { ok: true, providerId };
  }
  if (method === "POST" && path === "/auth/oauth/start") {
    return await beginOAuth(requiredString(body.providerId, "providerId"));
  }
  const oauthMatch = path.match(/^\/auth\/oauth\/([^/]+)$/);
  if (oauthMatch && method === "GET") {
    const session = oauthSessions.get(oauthMatch[1]);
    if (!session) throw new HttpError(404, "登录会话不存在或已过期。 ");
    return sessionView(session);
  }
  if (oauthMatch && method === "POST") {
    const session = oauthSessions.get(oauthMatch[1]);
    if (!session) throw new HttpError(404, "登录会话不存在或已过期。 ");
    if (!session.promptResolve) throw new Error("当前登录流程不需要输入。 ");
    const resolvePrompt = session.promptResolve;
    session.promptResolve = null;
    session.prompt = null;
    session.status = "waiting";
    resolvePrompt(requiredString(body.value, "value"));
    return sessionView(session);
  }
  if (method === "POST" && path === "/images/generate") {
    const providerId = requiredString(body.providerId, "providerId");
    const modelId = requiredString(body.modelId, "modelId");
    const prompt = requiredString(body.prompt, "prompt");
    const model = models.getModelOfType("image", providerId, modelId);
    if (!model) throw new Error("没有找到所选生图模型。 ");
    const requestImages = Array.isArray(body.images) ? body.images : [];
    const input = [{ type: "text", text: prompt }];
    for (const item of requestImages) {
      input.push({
        type: "image",
        data: requiredString(item.data, "images[].data"),
        mimeType: requiredString(item.mimeType, "images[].mimeType"),
      });
    }
    if (input.some((item) => item.type === "image") && !model.input.includes("image")) {
      throw new Error("所选模型不支持参考图输入，不能用于第二阶段线稿编辑。 ");
    }
    if (providerId === "openrouter") {
      const auth = await models.getAuth(model);
      if (!auth?.auth?.apiKey) throw new Error("OpenRouter 尚未登录，请先完成 OAuth 或保存 API Key。 ");
      return await requestOpenRouterImages({
        model,
        prompt,
        images: requestImages,
        apiKey: auth.auth.apiKey,
        baseUrl: auth.auth.baseUrl || model.baseUrl,
        headers: auth.auth.headers || {},
      });
    }
    const result = await models.generateImages(model, { input });
    if (result.stopReason !== "stop") {
      throw new Error(result.errorMessage || `模型生成失败：${result.stopReason}`);
    }
    const images = result.output.filter((item) => item.type === "image");
    if (!images.length) throw new Error("模型没有返回图像。 ");
    return {
      providerId: result.provider,
      modelId: result.model,
      responseId: result.responseId ?? "",
      usage: result.usage ?? {},
      images,
      text: result.output.filter((item) => item.type === "text").map((item) => item.text).join("\n"),
    };
  }
  throw new HttpError(404, "接口不存在。 ");
}


class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}


function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`缺少参数：${field}`);
  return value.trim();
}


async function readJsonRequest(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 60 * 1024 * 1024) throw new HttpError(413, "请求内容过大。 ");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "请求 JSON 无效。 ");
  }
}


function sendJson(response, status, value) {
  const payload = Buffer.from(JSON.stringify(value));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": payload.length,
    "Cache-Control": "no-store",
  });
  response.end(payload);
}


export async function createGatewayServer() {
  const token = await gatewayToken();
  return createServer(async (request, response) => {
    try {
      if (request.socket.remoteAddress && !["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(request.socket.remoteAddress)) {
        throw new HttpError(403, "只允许本机访问。 ");
      }
      if (request.headers["x-gateway-token"] !== token) {
        throw new HttpError(401, "模型网关令牌无效。 ");
      }
      const url = new URL(request.url ?? "/", `http://${HOST}:${PORT}`);
      const body = request.method === "POST" ? await readJsonRequest(request) : {};
      const result = await route(request.method ?? "GET", url.pathname, url.searchParams, body);
      sendJson(response, 200, result);
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 400;
      sendJson(response, status, {
        error: error instanceof Error ? error.message.trim() : String(error),
      });
    }
  });
}


async function main() {
  const server = await createGatewayServer();
  server.listen(PORT, HOST, () => {
    console.log(`pi model gateway listening on http://${HOST}:${PORT}`);
  });
}


if (resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
