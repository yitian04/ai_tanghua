# 本地糖画与线稿生成

在侧栏打开「AI糖画线稿」，选择「两阶段」或「直接线稿」，在对应模型配置中选「本地 ComfyUI」。两阶段分别配置来源，可组合使用本地和云端。点击「启动本地服务」，稍等后点击「检查连接与模型」。如果自己的 ComfyUI 已在本机 8188 端口运行，可以直接检查连接。

本机实测后已将 FLUX.2 Klein 4B FP8 设为本地默认。也可切换到 D:\ai\ComfyUI-aki-v1.5 中已有的 SDXL 文生图和 Flux Kontext FP8 图像编辑。软件按顺序向 ComfyUI 提交任务，启动时使用低显存模式。横幅实际输出 768×432，方形实际输出 768×768。图像编辑会等比缩放参考图，剩余区域补白。SDXL 的主体与提示词建议先使用英文。

如需修改安装目录、超时或模型组合，展开「本机高级设置」并保存。本机参数保存在数据目录的 comfyui.local.json，服务日志位于 data/ai_generation/comfyui/server.log。点击「保存本地来源」会记住对应流程的模型来源。小店会优先使用「第一阶段」当前选择或保存的来源，因此设置好后可直接打开小店的「描述生成」。本地服务连接失败时，小店显示错误。

预置了 FLUX.2 Klein 4B FP8 工作流。将其模型、编码器和 VAE 放在工作区 data/ai_generation/comfyui/models 对应子目录后，通过本项目启动入口加载。已运行的服务需要重新启动后才能识别新配置。模型约需 12.5 GB 磁盘。可以用项目环境运行：

```powershell
.venv/Scripts/python.exe -m tools.install_local_klein
```

完成后在「本机高级设置」中选择 Klein，保存并点击「检查连接与模型」。模型文件和对应工作流可参考 [ComfyUI 官方教程](https://docs.comfy.org/tutorials/flux/flux-2-klein)。

用项目里的六个小店题材复测并记录原图、提示词、耗时和自动检查结果：

```powershell
.venv/Scripts/python.exe -m tools.benchmark_local_comfy
.venv/Scripts/python.exe -m tools.benchmark_local_comfy --concise-direct
.venv/Scripts/python.exe -m tools.benchmark_local_comfy --profile klein
```

出图后请对照参考图检查主体、构图和线条。自动检查只能筛查线条分布与可追踪性。对照图中同一根糖丝出现两条平行线，或有错题、断线、大片填黑时，应重新生成或换模型，再送往曲线模块。


