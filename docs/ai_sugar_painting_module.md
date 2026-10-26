# AI 糖画样图与线稿模块

## 1. 当前流程

原“AI 生成曲线”页面已替换为真实模型调用的两阶段流程：

1. 用户输入一个主体，模型生成糖画样图。
2. 用户确认样图。
3. 同一模型以已确认样图为图像输入，提取黑白线稿。
4. 程序执行确定性线稿质量检查。
5. 用户确认合格线稿，线稿自动成为现有“图像转曲线”页面的输入。

页面不再要求把提示词复制到 GPT，也不把手工上传模型结果当成“模型接入”。`CurveList`、矢量化、轨迹规划和机器人执行结构均未修改。

## 2. Pi 模型中心

项目按照 [`@earendil-works/pi-ai`](https://github.com/earendil-works/pi/blob/main/packages/ai/README.md) 的 `Models`、`CredentialStore`、OAuth 和 `generateImages()` 接口增加了本地模型网关：

- 页面内选择服务商和生图模型；
- 页面内发起 OAuth/订阅登录；
- 页面内保存或退出 API Key；
- 模型列表和是否支持参考图由 Pi 模型目录提供；
- 一套服务商凭据同时供该服务商的相关操作使用；
- 凭据只保存在本机 `data/model_gateway/credentials.json`，`data/` 已被 Git 忽略；
- 本地网关只监听 `127.0.0.1`，请求还必须携带随机本机令牌。

当前 Pi 1.4.0 的内置图片生成只通过 OpenRouter 提供。因此推荐入口是：

1. 打开“模型配置 → 订阅与凭据”；
2. 选择 OpenRouter；
3. 使用 OAuth 登录，或保存 OpenRouter API Key；
4. 回到“生图模型”，选择同时支持文字和图片输入的模型；
5. 依次生成样图和线稿。

项目网关使用 OpenRouter 官方 `POST /api/v1/images` 生图接口；参考图通过 `input_references` 发送。Pi 1.4.0 自带的旧 `chat/completions` 图片实现不用于本项目，以兼容只支持新版图片接口的 GPT Image 等模型。

模型目录目前包含 GPT Image、Gemini Image、FLUX、Seedream、Qwen、Recraft 等 OpenRouter 生图模型。项目不会把模型名称写死为某一家，后续 Pi 增加生图服务商时，页面会按模型目录继续列出。

模型可用性还受 OpenRouter 账户地区和供应端限制。若接口返回 `This model is not available in your region`，页面会记住并隐藏该模型；默认优先选择支持参考图的 `qwen/qwen-image-2.1-turbo`，也可以尝试 Seedream。页面不会在报错后自动换模型并再次付费调用。

## 3. ChatGPT 订阅的限制

Pi 能发起 OpenAI 的“使用 ChatGPT 登录”，但 OpenAI 当前的订阅共享预览明确不支持 image generation。因此：

- 可以在账户页配置 OpenAI/ChatGPT OAuth；
- 不能把当前 ChatGPT 订阅额度当成这个项目的生图额度；
- 糖画生图应使用 OpenRouter OAuth/API Key，或下文的兼容图片 API。

这是上游能力限制，不是页面遗漏。参考：

- [OpenAI Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## 4. 其他生图 AI

页面保留“自定义兼容 API”入口，可接入同时实现以下接口的服务：

```text
POST /images/generations
POST /images/edits
```

第二阶段必须读取第一阶段已确认的图片，因此只有文生图、没有图片编辑能力的接口不能完成整个流程。兼容 API Key 默认只存在于当前页面会话或环境变量中：

```text
OPENAI_API_KEY
AI_IMAGE_API_KEY
AI_SUGAR_MODEL
AI_SUGAR_BASE_URL
```

## 5. 安装与启动

Pi 1.4.0 要求 Node.js 22.19 或更高版本。首次使用时在项目目录执行：

```powershell
npm install
```

正常打开 Streamlit 页面时，Python 客户端会自动启动本地 Pi 网关。也可以单独启动：

```powershell
npm run model-gateway
```

## 6. 任务与数据关联

每次新建任务后，数据保存在：

```text
data/ai_generation/tasks/<taskId>/
  task.json
  sample_a1.png
  sample_a2.png
  lineart_a1.png
  lineart_a2.png
```

`task.json` 保存任务、实际提示词、两阶段图片、确认状态、每次尝试的服务商、模型、请求编号、用量、质量检查结果和样本库选择。第二阶段记录 `sourceImage`，用于证明线稿来源于已确认样图。

## 7. 质量门槛、重试与样本库

线稿继续使用项目已有的 `evaluate_traceable_line_image()` 检查黑色像素占比、连通区域、碎小噪声、大型填充块、边缘密度和笔画宽度。未通过检查的线稿不能确认。开启自动修复时，一次操作最多额外调用模型一次，避免无上限消耗额度。

所有结果会保存为任务记录，但不会自动成为参考样本。只有确认线稿时主动勾选“同时加入已批准样本库”，任务才会进入 `data/ai_generation/approved_samples/`。后续任务默认不参考样本，必须由用户在该次生成中主动开启。

## 8. 建议测试顺序

先分别对马、兔、龙等单主体进行测试。每个主体至少生成 5 次，记录模型、提示词版本、调用次数、耗时、线稿检查结果、曲线数量和实机绘制结果。只有单主体稳定通过后，再扩展到“主体＋文字＋中国纹样”。

## 9. 代码位置

- 页面：`apps/gui/views/direct_curve_page.py`
- Pi 本地网关：`services/pi_model_gateway/server.mjs`
- Python 网关客户端：`src/pipeline/image_generation/pi_gateway.py`
- 两阶段任务服务：`src/pipeline/image_generation/sugar_painting.py`
- 兼容图片 API：`src/pipeline/image_generation/providers.py`
- 质量检查：`src/pipeline/image_generation/quality.py`
- 单元测试：`tests/test_sugar_painting.py`

验证命令：

```powershell
npm run test:model-gateway
.\.venv\Scripts\python.exe -m unittest tests.test_sugar_painting -v
```
