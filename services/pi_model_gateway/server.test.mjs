import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, before, test } from "node:test";

import { createGatewayServer, requestOpenRouterImages } from "./server.mjs";


let server;
let baseUrl;
let token;

before(async () => {
  server = await createGatewayServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  baseUrl = `http://127.0.0.1:${address.port}`;
  token = (await readFile("data/model_gateway/gateway_token.txt", "utf8")).trim();
});

after(async () => {
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
});

async function get(path, authenticated = true) {
  return fetch(`${baseUrl}${path}`, {
    headers: authenticated ? { "X-Gateway-Token": token } : {},
  });
}

test("health requires the local gateway token", async () => {
  assert.equal((await get("/health", false)).status, 401);
  const response = await get("/health");
  assert.equal(response.status, 200);
  const health = await response.json();
  assert.equal(health.service, "pi-model-gateway");
  assert.equal(health.imageTransport, "openrouter-images-v1");
});

test("pi exposes image models and reference-image capability", async () => {
  const response = await get("/models");
  assert.equal(response.status, 200);
  const { models } = await response.json();
  assert.ok(models.length > 0);
  assert.ok(models.every((model) => model.providerId === "openrouter"));
  assert.ok(models.some((model) => model.supportsReferenceImage));
});

test("OpenRouter generation uses the dedicated images endpoint", async () => {
  let capturedUrl;
  let capturedRequest;
  const result = await requestOpenRouterImages(
    {
      model: {
        id: "openai/gpt-image-2.5-flare",
        provider: "openrouter",
      },
      prompt: "clean sugar painting horse",
      apiKey: "test-key",
      baseUrl: "https://openrouter.ai/api/v1",
    },
    async (url, request) => {
      capturedUrl = url;
      capturedRequest = request;
      return new Response(JSON.stringify({
        id: "image-request-1",
        data: [{ b64_json: "aW1hZ2U=", media_type: "image/png" }],
        usage: { cost: 0.01 },
      }), { status: 200 });
    },
  );
  assert.equal(capturedUrl, "https://openrouter.ai/api/v1/images");
  assert.equal(capturedRequest.method, "POST");
  const payload = JSON.parse(capturedRequest.body);
  assert.equal(payload.model, "openai/gpt-image-2.5-flare");
  assert.equal(payload.prompt, "clean sugar painting horse");
  assert.equal(payload.input_references, undefined);
  assert.equal(result.images[0].data, "aW1hZ2U=");
  assert.equal(result.usage.cost, 0.01);
});

test("OpenRouter reference images use input_references data URLs", async () => {
  let payload;
  await requestOpenRouterImages(
    {
      model: {
        id: "openai/gpt-image-2.5-flare",
        provider: "openrouter",
      },
      prompt: "convert to black line art",
      images: [{ mimeType: "image/jpeg", data: "cmVmZXJlbmNl" }],
      apiKey: "test-key",
      baseUrl: "https://openrouter.ai/api/v1/",
    },
    async (_url, request) => {
      payload = JSON.parse(request.body);
      return new Response(JSON.stringify({
        data: [{ b64_json: "b3V0cHV0", media_type: "image/webp" }],
      }), { status: 200 });
    },
  );
  assert.deepEqual(payload.input_references, [{
    type: "image_url",
    image_url: { url: "data:image/jpeg;base64,cmVmZXJlbmNl" },
  }]);
});

test("OpenRouter preserves upstream region errors", async () => {
  await assert.rejects(
    requestOpenRouterImages(
      {
        model: { id: "openai/gpt-image-2.5-flare", provider: "openrouter" },
        prompt: "horse",
        apiKey: "test-key",
        baseUrl: "https://openrouter.ai/api/v1",
      },
      async () => new Response(JSON.stringify({
        error: { message: "This model is not available in your region." },
      }), { status: 403 }),
    ),
    (error) => error.status === 403 && /not available in your region/i.test(error.message),
  );
});
