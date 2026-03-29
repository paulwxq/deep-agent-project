---
name: tech-doc-writing
description: 技术设计文档初稿撰写指南。适用于任务首次启动、需要从零构建设计草稿的场景。定义了标准文档结构及外部信息（Context7/Web Search）的整合规范。
---

# 技术设计文档撰写指南

## 标准文档结构

一份合格的技术设计文档应包含以下章节：

### 1. 概述
- 项目背景与目标、核心功能列表
- 术语定义与缩写说明

### 2. 技术方案
- **整体架构设计**：必须使用 Mermaid 语法绘制图表并附带文字说明。
- **技术选型**：列出核心库（如 LangChain, Deep Agents SDK），引用 Context7 检索到的准确 API 签名。
- **关键算法/逻辑**：使用伪代码或步骤化列表描述核心逻辑（如 SAS 代码血缘解析算法）。

### 3. 模块设计
- **职责划分**：各模块的边界与核心职责。
- **关键类/函数**：定义核心类名、主要方法签名及功能。

### 4. 数据与接口设计
- **数据模型**：字段、类型、约束、示例数据。
- **接口定义**：入参、出参、异常响应、示例调用。

### 5. 非功能性与部署
- 异常处理策略、日志规范、性能考量、配置项列表（包含环境变量）。

## 写作原则

1. **面向 Coder**：文档应能直接指导编码，不留选择题。
2. **整合外部信息**：
   - **Context7**：若查询了库文档，应在设计中引用最新官方 API 签名。
   - **Web Search**：若参考了最佳实践，应简要说明并融入设计。
3. **图表表达**：优先使用 Mermaid 语法，便于在 Markdown 中直接渲染。

## 核心约束

- **初稿专用**：本技能仅服务于初稿阶段，修订流程统一由 `tech-doc-revision` 承载。
- **需求澄清**：在开始撰写前，必须判断是否存在基线冲突或边界模糊，若存在则调用 `ask_user` 后写入 `/drafts/qa-supplement.md`。
- **单文件规则**：唯一正式草稿为 `/drafts/design.md`，禁止创建 `v2/v3` 等变体文件。
- **目录访问边界**：禁止浏览 `/drafts/_backups` 或 `/output`。

## 通用文档模式（演进预留）

当任务上下文中明确提供“文档类型”和“项目类型”时，必须按本节规则选择共享的 spec/template。此规则用于后续通用软件工程文档生成模式。

### 1. 查找原则

- 先读取任务上下文中的：
  - 文档类型
  - 项目类型
- 然后严格按照下方映射表选择唯一的 spec 文件和 template 文件。
- 禁止自行猜测。
- 禁止模糊匹配。
- 禁止在映射表中不存在的情况下选择“最接近”的组合。

### 2. 显式映射表

支持的组合如下：

1. 需求规格说明书 + 通用软件
- spec: `skills/specs/general_software_requirements_specification.yaml`
- template: `skills/templates/standard_requirements_specification.md`

2. 系统概要设计说明书 + 通用软件
- spec: `skills/specs/general_software_system_overview_design.yaml`
- template: `skills/templates/standard_system_overview_design.md`

3. 系统详细设计说明书 + 通用软件
- spec: `skills/specs/general_software_system_detailed_design.yaml`
- template: `skills/templates/standard_system_detailed_design.md`

4. 系统详细设计说明书 + 数据仓库/ETL
- spec: `skills/specs/data_warehouse_system_detailed_design.yaml`
- template: `skills/templates/data_warehouse_system_detailed_design.md`

### 3. 失败策略

- 如果映射表中不存在对应组合：
  - 立即停止继续写作
  - 明确报告“当前文档类型 + 项目类型组合尚未支持”
  - 不得擅自降级到其他文档类型或项目类型

### 4. 读取顺序

选定映射后，必须按以下顺序读取：

1. spec 文件
2. template 文件
3. 当前输入材料
4. `/drafts/design.md`（若为修订前检查需要）
5. 当前 Reviewer 原始反馈（若本轮为修订场景）

不得跳过 spec 直接按 template 写作。
