# 小店候选画风

**第二轮修正**：当前界面使用独立线条组织分类：圆润轮廓、几何折线、舒展流线、对称纹样、稚拙造型、留白构景。极简是所有方向的共同要求；动物仅属于内容。`legacy_library_id` 等字段只保留旧批次来源，不能视为新分类的官方风格编号。当前生成不使用下述旧艺术家参考或拼贴图。第二轮同题模型比较见 `outputs/shop_model_comparison_v2/结论.md`。

风格索引和编号参考图来自 **yang0 / handraw-style**：https://github.com/yang0/handraw-style 。完整个人 Skill 安装在用户技能目录，本项目只携带本轮选用的六种参考资源。

这六种是待筛选候选：极简动物 FB-036、趣味涂鸦 FA-001、民俗花纹 FB-013、几何自然 FC-008、诗意单线 FC-015、植物线描 FB-062。界面使用中文分类名；完整名称、作者标签、原始特征和每种三个灵感主题见 `catalog.json`。

`line_density_reference.png` 是用户提供的森林样板图。`*_input.jpg` 将它与编号风格参考并排放置：A 约束线条简洁度，B 提供造型语言。组合图只是模型输入，不是生成结果或最终参考图。可运行 `tools/prepare_shop_references.py` 重建。

最终风格参考图需要用户筛选后另行确定。本轮18张生成结果与实际提交提示词位于 `outputs/shop_style_candidates`。
