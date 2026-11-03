# AI SVG 曲线

入口位于“图像转曲线”之后。输入主题、可修改创作提示词，选择服务模型或填写模型 ID；默认不选择模型、不发起请求。支持 ChatAnywhere 与自定义 HTTP(S) 兼容聊天接口。

只有“读取模型列表”访问模型列表接口，只有“生成 SVG 曲线”提交一次生成请求。不自动重试、切换模型或付费修复；服务不支持当前聊天接口、地区限制或输出截断时明确提示。

参考图使用现有本地上传／素材库预览确认流程，随请求以内嵌 PNG 提交，不需要公开 URL。用户须明确确认当前模型支持参考图，不静默丢弃图片。图片不进入成果元数据。

API Key 独立保存在 `data/model_gateway/svg_credentials.json`，不进入素材或参数默认值。API 地址、模型 ID、提示词与画布等使用独立 svg 参数组；主题、参考图、识图确认和结果不作为默认值。

## SVG 支持范围

这是严格的单线子集，不能把任意网页 SVG 当作可绘制曲线：

- 单个完整 SVG，允许单个完整 Markdown 代码围栏；不拼补 XML、不从多个结果中挑选。
- svg/g、path、line、polyline、polygon、circle、ellipse、无圆角 rect。
- path 支持 M/L/H/V/C/Q/Z 的大小写形式；其他命令、transform、CSS、style、文字、填充、遮罩、裁剪、滤镜、图片、外部引用、实体和脚本均明确拒绝。
- 几何使用无填充黑色描边、宽度 2；可从 svg/g 继承。复杂主题或艺术风格不限，但必须以这种单线表示。
- viewBox 与设置画布一致；坐标为 SVG 坐标单位，不是毫米。保留点序、子路径方向，不自动接线或重排。
- 响应最多 1 MB、500 元素，另设采样预算，最终最多 100 曲线／10000 点。超限报错，不静默截断。

原图通过 SVG 图像方式预览，不以可执行 HTML 插入页面。有序曲线预览沿用 X 右、Y 下。连通检查基于采样线段交点和 1 SVG 单位内接触；显示连通组，不能证明严格一笔完成、无抬笔或实物适用。

分离部分须用户确认后才允许保存／规划。SVG 与曲线 JSON 先留在私有草稿，保存确认后整套入库；进入规划必须先保存并在目标页确认。无效输出只显示源码与诊断，不冒充成功曲线。

## 检查

`test_svg_generation.py` 使用文本模型替身验证响应、严格校验、连通性、接口错误和页面不自动调用；浏览器夹具 `tests/fixtures/svg_generation_app.py` 使用临时素材目录及请求替身。

```
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe -m streamlit run tests/fixtures/svg_generation_app.py --server.port 8536 --server.headless true
.venv/Scripts/python.exe tests/browser_svg_generation_check.py
```

未发起真实付费生成或机械臂执行；替身检查不证明真实模型的创作质量和接口可用性。

接口依据：[ChatAnywhere 模型文档](https://docs.chatanywhere.tech/doc-2694962)、[请求说明](https://docs.chatanywhere.tech/doc-2664688)。模型列表可能变化，不据旧价格表推算费用。
