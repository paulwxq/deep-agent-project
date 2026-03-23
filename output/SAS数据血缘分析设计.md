# SAS 数据血缘分析模块 - 技术设计文档

**文档版本**: v1.1  
**编写日期**: 2024年  
**技术栈**: Python 3.12 | LangChain | 可配置 LLM Provider

---

## 1. 项目概述

### 1.1 业务背景

业务团队使用 SAS 代码进行数据处理，代码涉及多种数据源（Mainframe SAS 数据集、CSV 文件、Excel 文件）以及多步骤的中间处理流程。为满足数据治理和合规审计需求，需要自动分析 SAS 代码，生成数据血缘对照表，明确源表/源字段到目标表/目标字段的映射关系。

### 1.2 核心目标

本模块的核心目标是从输出表出发，反向追溯每个输出字段的数据来源，生成如下格式的血缘对照表：

| 字段 | 说明 |
|------|------|
| `output_table` | 输出表/文件名称 |
| `output_column` | 输出字段名称 |
| `original_table` | 源表名称（多个用分号分隔） |
| `original_column` | 源字段名称（多个用分号分隔） |
| `formula` | 转换公式或操作类型（passthrough/rename/表达式） |
| `script_file` | 所属 SAS 脚本文件路径 |

### 1.3 数据源类型

| 类型 | 后缀 | 说明 |
|------|------|------|
| 输入数据 | CSV, Excel | 外部导入的原始数据 |
| Mainframe 数据 | .sas7bdat 或定义文件 | 定义到 mainframe 的 SAS 数据集 |
| 中间数据 | .sas7bdat | SAS 脚本之间的中间结果 |
| 输出数据 | CSV | 最终输出到业务系统的文件 |

---

## 2. 系统架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     SAS Data Lineage Analyzer                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Config      │  │  File        │  │  LLM                 │  │
│  │  Manager     │  │  Scanner     │  │  Provider            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  SAS         │  │  Lineage     │  │  Output              │  │
│  │  Parser      │  │  Resolver    │  │  Exporter            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 |
|------|------|
| `ConfigManager` | 加载和管理系统配置，包括 LLM Provider 配置、数据源路径配置 |
| `FileScanner` | 扫描指定目录，识别 SAS 代码文件、CSV 输出文件、中间 SAS 数据集 |
| `SASParser` | 解析 SAS 代码，提取 DATA Step、PROC IMPORT/EXPORT 语句，识别变量映射关系 |
| `LLMProvider` | 封装 LLM 调用，提供基于 LangChain 的 Prompt 模板和响应解析 |
| `LineageResolver` | 从输出表反向解析数据血缘，构建完整的字段级映射关系 |
| `OutputExporter` | 将血缘分析结果导出为 CSV 或 JSON 格式 |

### 2.3 目录结构

```
sas_lineage_analyzer/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── settings.py          # 配置管理
├── core/
│   ├── __init__.py
│   ├── file_scanner.py      # 文件扫描
│   ├── sas_parser.py        # SAS 代码解析
│   └── lineage_resolver.py  # 血缘解析
├── llm/
│   ├── __init__.py
│   ├── base.py              # LLM Provider 基类
│   ├── langchain_provider.py # LangChain 实现
│   └── prompts.py           # Prompt 模板
├── models/
│   ├── __init__.py
│   └── lineage.py           # 数据模型定义
├── output/
│   ├── __init__.py
│   └── exporter.py          # 结果导出
├── main.py                  # 入口脚本
├── requirements.txt
└── config.yaml              # 配置文件
```

---

## 3. 数据模型设计

### 3.1 核心数据类

```python
# models/lineage.py

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class TransformType(Enum):
    """转换类型枚举"""
    PASSTHROUGH = "passthrough"          # 直接传递
    RENAME = "rename"                    # 字段重命名
    DERIVED = "derived"                  # 派生字段（表达式计算）
    AGGREGATE = "aggregate"              # 聚合操作
    MERGE = "merge"                      # 表关联
    CONDITIONAL = "conditional"          # 条件赋值


@dataclass
class ColumnMapping:
    """单个字段映射关系"""
    output_column: str
    original_column: str
    transform_type: TransformType
    formula: Optional[str] = None
    source_table: Optional[str] = None
    source_column: Optional[str] = None


@dataclass
class LineageRecord:
    """数据血缘记录"""
    output_table: str
    output_column: str
    original_table: str          # 多源用分号分隔
    original_column: str         # 多字段用分号分隔
    formula: str                 # passthrough / rename xxx -> yyy / 表达式
    script_file: str
    transform_type: TransformType = TransformType.PASSTHROUGH


@dataclass
class SASTransformStep:
    """SAS 转换步骤"""
    step_type: str               # DATA, PROC IMPORT, PROC EXPORT, PROC SORT, PROC MERGE
    input_tables: list[str] = field(default_factory=list)
    output_table: Optional[str] = None
    column_mappings: list[ColumnMapping] = field(default_factory=list)
    raw_statement: str = ""


@dataclass
class SASScript:
    """单个 SAS 脚本的解析结果"""
    file_path: str
    steps: list[SASTransformStep] = field(default_factory=list)
    macro_variables: dict[str, str] = field(default_factory=dict)
    libname_assignments: dict[str, str] = field(default_factory=dict)
```

### 3.2 血缘图结构

```python
@dataclass
class LineageGraph:
    """数据血缘图"""
    nodes: dict[str, DataNode] = field(default_factory=dict)  # key: table_name
    edges: list[LineageEdge] = field(default_factory=list)


@dataclass
class DataNode:
    """血缘图中的数据节点"""
    name: str
    node_type: str  # "input", "intermediate", "output"
    file_path: Optional[str] = None
    columns: list[str] = field(default_factory=list)


@dataclass
class LineageEdge:
    """血缘图中的边（表示数据流向）"""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    transform_type: TransformType
    formula: Optional[str] = None
    script_file: str
```

---

## 4. 核心模块设计

### 4.1 配置管理 (ConfigManager)

**配置项**：

```yaml
# config.yaml

llm:
  provider: "openai"              # 支持: openai, anthropic, azure_openai, local
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"   # 支持环境变量引用
  base_url: null                 # 自定义端点（用于代理或本地模型）
  temperature: 0
  max_tokens: 4096
  timeout: 120

paths:
  sas_code_dir: "/path/to/sas/code"
  csv_output_dir: "/path/to/csv/output"
  sas_data_dir: "/path/to/sas/data"
  cache_dir: "./cache"

analysis:
  batch_size: 5                 # 每批处理的 SAS 文件数量
  max_retries: 3
  use_cache: true
  output_format: "csv"          # 支持: csv, json

lineage:
  resolve_intermediate: true    # 是否解析中间表
  include_derived_formulas: true
```

**ConfigManager 实现要点**：

1. 支持 YAML 配置文件加载
2. 支持环境变量插值（`${ENV_VAR}` 语法）
3. 提供配置验证和默认值
4. 支持运行时配置覆盖

### 4.2 文件扫描器 (FileScanner)

**职责**：扫描指定目录，识别并分类项目中的数据文件。

**文件分类策略**：

| 类型 | 识别规则 |
|------|----------|
| SAS 脚本 | `.sas` 后缀，排除 `def_*.sas` 定义文件 |
| CSV 输出 | 目录中所有 `.csv` 文件 |
| 中间 SAS 数据 | `.sas7bdat` 后缀，或通过 `def_*.sas` 定义文件关联 |
| 定义文件 | `def_*.sas` 后缀，包含 `data &lib.. xxx` 语句 |

**关键方法**：

```python
class FileScanner:
    def scan_directory(self, root_path: str) -> ScanResult:
        """
        扫描目录并返回扫描结果
        Returns:
            ScanResult: 包含 sas_scripts, csv_outputs, definition_files
        """

    def identify_output_tables(self, csv_files: list[str]) -> list[str]:
        """
        从 CSV 文件名推断输出表名（去除路径和后缀）
        """
```

### 4.3 SAS 代码解析器 (SASParser)

**解析范围**：

| SAS 语句 | 解析目标 |
|----------|----------|
| `PROC IMPORT` | 输入文件路径、输出数据集名 |
| `PROC EXPORT` | 输出文件路径、输入数据集名 |
| `DATA xxx; SET yyy` | 输入输出表映射、变量列表 |
| `RENAME=(a=b ...)` | 字段重命名映射 |
| `KEEP xxx ...` | 保留字段列表 |
| `DROP xxx ...` | 丢弃字段列表 |
| `MERGE a b` | 多表关联 |
| `BY xxx` | 关联键 |
| `PROC SORT` | 排序操作（标记中间步骤） |
| `%LET xxx = yyy` | 宏变量定义 |
| `LIBNAME xxx ...` | 库名定义 |

**解析策略**：

1. **正则表达式 + 语法分析混合**：使用正则匹配语句边界，用状态机解析嵌套结构
2. **宏变量展开**：收集 `%LET` 定义，尝试展开后续引用
3. **注释处理**：保留注释中的说明信息（如 "Source: xxx"）

**关键方法**：

```python
class SASParser:
    def parse_script(self, file_path: str) -> SASScript:
        """解析单个 SAS 脚本"""

    def extract_data_step(self, data_block: str) -> SASTransformStep:
        """提取 DATA 步骤的详细信息"""

    def extract_import_export(self, block: str) -> SASTransformStep:
        """提取 PROC IMPORT/EXPORT 信息"""

    def resolve_renames(self, rename_clause: str) -> dict[str, str]:
        """解析 RENAME 子句"""

    def extract_formula(self, assignment: str) -> str:
        """提取派生字段的计算公式"""
```

### 4.4 LLM Provider (LLMProvider)

**设计模式**：策略模式，支持多种 LLM 后端。

**接口定义**：

```python
from abc import ABC, abstractmethod

class BaseLLMProvider(ABC):
    @abstractmethod
    def analyze_lineage(self, prompt: str) -> LineageAnalysisResult:
        """调用 LLM 分析血缘"""
        pass

    @abstractmethod
    def extract_mappings(self, sas_code: str) -> list[ColumnMapping]:
        """从 SAS 代码片段提取字段映射"""
        pass


class LineageAnalysisResult:
    """LLM 返回结果的结构化封装"""
    success: bool
    mappings: list[ColumnMapping]
    confidence: float
    reasoning: str
    error: Optional[str]
```

**LangChain 集成实现**：

```python
class LangChainProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig):
        self.llm = self._create_llm(config)
        self.prompt_template = LineagePromptTemplate()

    def _create_llm(self, config: LLMConfig):
        """根据配置创建 LangChain LLM 实例"""
        if config.provider == "openai":
            return ChatOpenAI(
                model=config.model,
                api_key=config.api_key,
                temperature=config.temperature,
                max_tokens=config.max_tokens
            )
        elif config.provider == "anthropic":
            return ChatAnthropic(
                model=config.model,
                api_key=config.api_key,
                max_tokens=config.max_tokens
            )
        # 支持更多 provider...
```

**Prompt 模板设计**：

```
## System Prompt
You are a SAS data lineage expert. Given SAS code, you need to identify the mapping 
between output columns and source columns.

## Task
Analyze the following SAS code and extract column-level data lineage.

## Output Format
Return a JSON array where each element represents one column mapping:
{
  "output_column": "column_name",
  "original_table": "source_table",
  "original_column": "source_column",
  "formula": "passthrough|rename original -> output|expression",
  "transform_type": "PASSTHROUGH|RENAME|DERIVED"
}

## Rules
1. For columns that pass through unchanged, use "passthrough"
2. For renamed columns, use "rename SourceColumn -> TargetColumn"
3. For derived columns with expressions, extract the formula
4. Handle multi-table sources with semicolon-separated values
5. Merge/sort operations are intermediate; trace through them

## SAS Code
{sas_code}
```

### 4.5 血缘解析器 (LineageResolver)

**核心算法**：从输出表反向追溯。

```
1. 从 CSV 输出文件反查对应的 SAS EXPORT 语句
2. 找到该 EXPORT 语句的输入数据集
3. 追踪该数据集的 DATA Step 来源
4. 递归解析中间步骤直到抵达原始数据源
5. 合并所有映射关系，生成最终血缘表
```

**关键方法**：

```python
class LineageResolver:
    def resolve_from_output(self, output_table: str, script: SASScript) -> list[LineageRecord]:
        """
        从输出表解析完整血缘链
        """

    def trace_back(self, table: str, column: str, visited: set[str]) -> list[LineageRecord]:
        """
        递归回溯字段来源
        """

    def merge_lineage(self, records: list[LineageRecord]) -> list[LineageRecord]:
        """
        合并同一目标字段的多条血缘路径
        """
```

**循环依赖处理**：

- 维护访问集合 `visited` 防止无限循环
- 检测到循环时记录并报告警告
- 优先保留直接来源路径

### 4.6 结果导出器 (OutputExporter)

**输出格式**：

```python
class OutputExporter:
    def export_csv(self, records: list[LineageRecord], output_path: str):
        """导出为 CSV 格式"""

    def export_json(self, records: list[LineageRecord], output_path: str):
        """导出为 JSON 格式，包含完整血缘图结构"""

    def generate_report(self, records: list[LineageRecord]) -> str:
        """生成可读的血缘报告"""
```

**CSV 输出示例**：

```csv
output_table,output_column,original_table,original_column,formula,script_file
churn_out,credit_scr,churn_raw,CreditScore,rename CreditScore -> credit_scr,01_churn_transform.sas
churn_out,bal_per_prod,churn_raw,Balance; NumOfProducts,Balance / num_prod,01_churn_transform.sas
merged_out,risk_score,churn_raw; loan_raw,CreditScore; Debit_to_Income,credit_scr - (dti * 10),03_merge_transform.sas
```

---

## 5. 批处理策略

### 5.1 分批处理机制

由于 SAS 代码总量可能超出单次 LLM 调用的上下文限制，采用分批处理策略：

```
┌─────────────────────────────────────────────────────────┐
│  Batch 1: 文件 1-5                                      │
│  ├─ 文件 1: 01_churn_transform.sas                      │
│  ├─ 文件 2: 02_loan_transform.sas                      │
│  ├─ 文件 3: 03_merge_transform.sas                      │
│  ├─ 文件 4: def_Churn.sas                              │
│  └─ 文件 5: def_train.sas                              │
├─────────────────────────────────────────────────────────┤
│  Batch 2: 文件 6-10                                     │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

**配置参数**：

```yaml
analysis:
  batch_size: 5              # 每批文件数（可根据 LLM 上下文大小调整）
  parallel_batches: false    # 是否并行处理批次
```

### 5.2 中间表解析策略

为减少跨文件依赖复杂性，采用**从输出到输入的反向解析**：

1. **定位输出**：扫描 CSV 文件，确定输出表
2. **查找 EXPORT 语句**：在 SAS 代码中定位 `PROC EXPORT` 语句
3. **反向追踪**：
   - EXPORT 的 `DATA=` 参数 → 对应 DATA Step 的输出表
   - DATA Step 的 `SET` 参数 → 追溯到输入表
   - 递归处理中间 DATA Step
4. **合并结果**：汇总所有字段映射关系

---

## 6. LLM 调用优化

### 6.1 上下文优化

| 策略 | 说明 |
|------|------|
| 代码精简 | 预处理时去除注释和空行，保留核心逻辑 |
| 结构化输入 | 仅传递当前分析所需的代码片段 |
| 增量分析 | 缓存已解析的中间表结果，避免重复分析 |

### 6.2 缓存机制

```python
class LineageCache:
    def get(self, script_path: str) -> Optional[SASScript]:
        """从缓存获取解析结果"""

    def set(self, script_path: str, result: SASScript):
        """存入缓存"""

    def get_hash(self, content: str) -> str:
        """计算内容哈希用于缓存校验"""
```

**缓存策略**：
- 使用文件内容哈希作为缓存键
- 支持 Redis 或本地文件系统存储
- 可配置缓存失效时间

### 6.3 错误处理与重试

```python
class RetryableError(Exception):
    """可重试的错误（如 API 超时）"""
    pass

def analyze_with_retry(provider: BaseLLMProvider, prompt: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return provider.analyze_lineage(prompt)
        except RetryableError as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # 指数退避
```

---

## 7. 接口设计

### 7.1 命令行接口 (CLI)

```bash
# 基本用法
python main.py analyze --sas-dir /path/to/sas --csv-dir /path/to/csv --output lineage.csv

# 完整参数
python main.py analyze \
    --sas-dir /path/to/sas \
    --csv-dir /path/to/csv \
    --output lineage.csv \
    --format csv \
    --batch-size 5 \
    --config config.yaml

# 查看帮助
python main.py --help
```

### 7.2 Python API

```python
from sas_lineage_analyzer import SASLineageAnalyzer, AnalyzerConfig

# 方式 1：使用默认配置
analyzer = SASLineageAnalyzer()
results = analyzer.analyze(
    sas_dir="/path/to/sas",
    csv_dir="/path/to/csv"
)
analyzer.export(results, "lineage.csv")

# 方式 2：自定义配置
config = AnalyzerConfig(
    llm_provider="openai",
    llm_model="gpt-4o",
    batch_size=3,
    use_cache=True
)
analyzer = SASLineageAnalyzer(config)
results = analyzer.analyze(
    sas_dir="/path/to/sas",
    csv_dir="/path/to/csv",
    output_table="churn_out"  # 可指定单个输出表
)
```

### 7.3 配置接口

```python
# config.yaml
llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"

paths:
  sas_code_dir: "./sas"
  csv_output_dir: "./output"

analysis:
  batch_size: 5
  max_retries: 3
```

---

## 8. 错误处理

### 8.1 错误分类

| 错误类型 | 处理策略 |
|----------|----------|
| `FileNotFoundError` | 记录警告，跳过该文件继续处理 |
| `ParseError` | 记录错误位置，标记该步骤解析失败 |
| `LLMError` | 重试 N 次，失败后使用启发式规则兜底 |
| `CircularDependencyError` | 检测循环依赖，记录并中断 |
| `MissingSourceError` | 无法追溯源表，记录为 "UNKNOWN" |

### 8.2 日志记录

```python
import logging

logger = logging.getLogger("sas_lineage_analyzer")
logger.setLevel(logging.INFO)

# 日志格式
# 2024-01-15 10:30:45 [INFO] Parsing: 01_churn_transform.sas
# 2024-01-15 10:30:46 [WARNING] Cannot resolve macro variable: &data_path
# 2024-01-15 10:30:50 [ERROR] LLM request failed after 3 retries
```

---

## 9. 测试策略

### 9.1 单元测试

| 测试用例 | 验证内容 |
|----------|----------|
| `test_sas_parser_rename` | RENAME 子句解析正确性 |
| `test_sas_parser_keep_drop` | KEEP/DROP 子句解析正确性 |
| `test_sas_parser_merge` | MERGE 语句解析正确性 |
| `test_lineage_resolver_simple` | 简单 DATA Step 的血缘追溯 |
| `test_lineage_resolver_chain` | 多步骤串联的完整血缘链 |
| `test_lineage_resolver_merge` | 跨表关联的字段溯源 |
| `test_llm_provider_mock` | Mock LLM 响应解析 |

### 9.2 集成测试

使用示例文件 `sas/*.sas` 进行端到端测试：

```python
def test_end_to_end_with_sample_files():
    analyzer = SASLineageAnalyzer()
    results = analyzer.analyze(
        sas_dir="./input/sas",
        csv_dir="./input/sas"
    )

    # 验证 churn_out 的血缘
    churn_records = [r for r in results if r.output_table == "churn_out"]
    assert len(churn_records) > 0

    # 验证 credit_scr 字段映射
    credit_scr = next(r for r in churn_records if r.output_column == "credit_scr")
    assert credit_scr.original_column == "CreditScore"
    assert "rename" in credit_scr.formula
```

### 9.3 测试数据

使用 `/input/sas/` 目录下的示例文件作为测试基准：

| 文件 | 用途 |
|------|------|
| `01_churn_transform.sas` | 测试单表转换、重命名、派生字段 |
| `02_loan_transform.sas` | 测试单表转换、筛选派生 |
| `03_merge_transform.sas` | 测试多表 MERGE、跨源派生 |
| `def_Churn.sas` | 测试 Mainframe 定义文件解析 |
| `Output_sas_20260318.csv` | 测试结果比对基准 |

---

## 10. 部署与依赖

### 10.1 依赖清单

```
# requirements.txt

python>=3.12
pyyaml>=6.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-anthropic>=0.2.0
pydantic>=2.0
rich>=13.0
loguru>=0.7.0
```

### 10.2 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `OPENAI_API_KEY` | OpenAI API Key | 当 provider=openai 时必填 |
| `ANTHROPIC_API_KEY` | Anthropic API Key | 当 provider=anthropic 时必填 |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI Key | 当 provider=azure_openai 时必填 |

---

## 11. 附录

### 11.1 血缘类型说明

| 类型 | formula 示例 | 说明 |
|------|--------------|------|
| PASSTHROUGH | `passthrough` | 字段直接传递，未做任何变换 |
| RENAME | `rename CreditScore -> credit_scr` | 字段仅做了重命名 |
| DERIVED | `Balance / num_prod` | 基于表达式的派生字段 |
| CONDITIONAL | `(Age >= 60)` | 条件表达式派生 |
| AGGREGATE | `SUM(amount)` | 聚合运算 |
| MERGE | `churn_raw; loan_raw` | 来自多个源表 |

### 11.2 术语表

| 术语 | 定义 |
|------|------|
| Mainframe | 主机数据，通常通过 LIBNAME 映射访问 |
| SAS Dataset | SAS 数据文件，常见后缀 .sas7bdat |
| DATA Step | SAS 数据处理步，核心处理逻辑 |
| PROC IMPORT/EXPORT | SAS 数据导入导出过程 |
| Macro Variable | SAS 宏变量，用于参数化配置 |

---

## 附录 A：Mainframe 定义文件解析规则详解

### A.1 定义文件结构

Mainframe 定义文件（`def_*.sas`）用于描述映射到大型机数据源的结构。典型结构如下：

```sas
/***********************************************************************
*  版权声明头
************************************************************************/

/* 宏变量定义 */
%let source_path=/sasdata/hsbc/user/...;
%let lib=DAT;

/* DATA 步骤定义 */
data &lib.. churn_raw /nolist;

    infile "&source_path/churn_raw&file_sfx" recfm=F lrecl=657;
    input
        @1    CustomerId                       PK2.0
        @3    Surname                           PK2.0
        @5    CreditScore                             PK3.0
        @8    Geography                              S370FPD2.0
        ...
    ;
run;
```

### A.2 解析规则表

| 提取项 | 正则表达式 | 示例 | 提取结果 |
|--------|------------|------|----------|
| 表名 | `data\s+&lib\.\.(\w+)` | `data &lib.. churn_raw` | `churn_raw` |
| 源文件路径 | `infile\s+"([^"]+)"` | `infile "&source_path/churn_raw..."` | 包含宏变量的路径 |
| 宏变量 | `%let\s+(\w+)=([^;]+)` | `%let source_path=/sasdata/...` | `{source_path: /sasdata/...}` |
| 字段定义 | `@(\d+)\s+([^\s]+)\s+(\S+)` | `@1 CustomerId PK2.0` | position=1, name=CustomerId, type=PK2.0 |
| 复杂字段名 | `@(\d+)\s+'([^']+)'\s+(\S+)` | `@3 'Loan Amount' PK2.0` | position=3, name=Loan Amount, type=PK2.0 |

### A.3 字段提取逻辑

#### A.3.1 简单字段名

对于格式 `@位置 字段名 类型` 的行：

```python
# 输入: "@1    CustomerId    PK2.0"
# 输出: ColumnDef(name="CustomerId", position=1, data_type="PK2.0")
```

#### A.3.2 带引号字段名

对于格式 `@位置 '字段名' 类型` 的行：

```python
# 输入: "@3    'Loan Amount'    PK2.0"
# 输出: ColumnDef(name="Loan Amount", position=3, data_type="PK2.0")
```

#### A.3.3 宏变量展开

宏变量在路径中使用，占位符格式为 `&变量名`：

```python
# 定义文件内容
%let source_path=/sasdata/hsbc/user;
%let file_sfx=_20260318;

# infile 语句
infile "&source_path/churn_raw&file_sfx"

# 展开后
infile "/sasdata/hsbc/user/churn_raw_20260318"
```

### A.4 解析器实现

```python
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class ColumnDef:
    name: str
    position: Optional[int]
    data_type: Optional[str]

@dataclass
class TableSchema:
    table_name: str
    source_file: str
    columns: List[ColumnDef]

class DefFileParser:
    """Mainframe 定义文件解析器"""

    # 正则表达式
    TABLE_NAME_RE = re.compile(r'data\s+&lib\.\.(\w+)')
    SOURCE_FILE_RE = re.compile(r'infile\s+"([^"]+)"')
    MACRO_VAR_RE = re.compile(r'%let\s+(\w+)=([^;]+)', re.IGNORECASE)
    COLUMN_DEF_RE = re.compile(r"@(\d+)\s+'([^']+)'\s+(\S+)")
    COLUMN_DEF_SIMPLE_RE = re.compile(r"@(\d+)\s+(\S+)\s+(\S+)")

    def parse(self, content: str) -> TableSchema:
        table_name = self._extract_table_name(content)
        source_file = self._extract_source_file(content)
        macro_vars = self._extract_macro_vars(content)
        columns = self._extract_columns(content)

        return TableSchema(
            table_name=table_name,
            source_file=self._expand_macros(source_file, macro_vars),
            columns=columns
        )

    def _extract_table_name(self, content: str) -> str:
        match = self.TABLE_NAME_RE.search(content)
        if not match:
            raise ValueError("Cannot find table name")
        return match.group(1)

    def _extract_source_file(self, content: str) -> str:
        match = self.SOURCE_FILE_RE.search(content)
        if not match:
            raise ValueError("Cannot find source file")
        return match.group(1)

    def _extract_macro_vars(self, content: str) -> Dict[str, str]:
        macro_vars = {}
        for match in self.MACRO_VAR_RE.finditer(content):
            macro_vars[match.group(1).lower()] = match.group(2).strip()
        return macro_vars

    def _expand_macros(self, template: str, macro_vars: Dict[str, str]) -> str:
        result = template
        for name, value in macro_vars.items():
            result = result.replace(f'&{name}', value)
            result = result.replace(f'&{name.upper()}', value)
        return result

    def _extract_columns(self, content: str) -> List[ColumnDef]:
        columns = []
        input_match = re.search(r'input\s+([\s\S]+?);', content)
        if not input_match:
            return columns

        for line in input_match.group(1).split('\n'):
            line = line.strip()
            if not line or line.startswith('*'):
                continue

            # 尝试匹配带引号的字段名
            match = self.COLUMN_DEF_RE.match(line)
            if match:
                columns.append(ColumnDef(
                    position=int(match.group(1)),
                    name=match.group(2),
                    data_type=match.group(3)
                ))
                continue

            # 尝试匹配简单字段名
            match = self.COLUMN_DEF_SIMPLE_RE.match(line)
            if match:
                columns.append(ColumnDef(
                    position=int(match.group(1)),
                    name=match.group(2),
                    data_type=match.group(3)
                ))

        return columns
```

---

## 附录 B：表名与定义文件关联机制

### B.1 关联策略

系统采用多级关联策略，按优先级顺序尝试：

| 优先级 | 策略 | 描述 | 适用场景 |
|--------|------|------|----------|
| 1 | 命名模式匹配 | `def_<TableName>.sas` | 标准命名规范 |
| 2 | 内容匹配 | 从定义文件内容提取表名后匹配 | 非标准命名 |
| 3 | 目录同位置 | 与 SAS 代码同目录 | 同名定义文件 |
| 4 | LLM 推断 | 调用 LLM 推断关联 | 复杂关联场景 |

### B.2 关联流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    关联机制初始化                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   扫描目录 ──▶ 识别 def_*.sas 文件                                │
│                    │                                              │
│                    ▼                                              │
│            解析每个定义文件                                         │
│                    │                                              │
│                    ▼                                              │
│         提取表名，建立映射表                                        │
│         {table_name: def_file_path}                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    运行时关联查询                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   解析 SAS 代码 ──▶ 识别表名 (churn_raw)                            │
│                           │                                      │
│                           ▼                                      │
│                  在注册表中查找                                    │
│                           │                                      │
│              ┌───────────┴───────────┐                          │
│              │                       │                          │
│         找到 ──────────────────▶ 未找到                            │
│              │                       │                          │
│              ▼                       ▼                          │
│       返回 TableSchema        标记"未定义表"                       │
│                                      │                          │
│                               可选：LLM 推断                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### B.3 关联注册表实现

```python
from pathlib import Path
from typing import Dict, List, Optional

class DefinitionRegistry:
    """
    定义文件注册表

    负责管理表名与定义文件的关联映射
    """

    def __init__(self):
        self._table_to_file: Dict[str, str] = {}      # 表名 → 文件路径
        self._file_to_schema: Dict[str, TableSchema] = {}  # 文件路径 → Schema
        self._parser = DefFileParser()

    def scan_directory(self, directory: str) -> int:
        """
        扫描目录，注册所有定义文件

        Args:
            directory: 扫描目录路径

        Returns:
            注册的表数量
        """
        count = 0
        for path in Path(directory).rglob("def_*.sas"):
            try:
                self.register_file(str(path))
                count += 1
            except Exception as e:
                print(f"Warning: Failed to parse {path}: {e}")
        return count

    def register_file(self, file_path: str) -> TableSchema:
        """
        注册单个定义文件

        Args:
            file_path: 定义文件路径

        Returns:
            解析后的 TableSchema
        """
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        schema = self._parser.parse(content)
        schema.source_file = file_path  # 存储文件路径

        # 建立双向映射
        self._table_to_file[schema.table_name] = file_path
        self._file_to_schema[file_path] = schema

        return schema

    def get_schema(self, table_name: str) -> Optional[TableSchema]:
        """
        根据表名获取表结构定义

        Args:
            table_name: 表名

        Returns:
            TableSchema 或 None（未找到）
        """
        file_path = self._table_to_file.get(table_name)
        if file_path:
            return self._file_to_schema.get(file_path)
        return None

    def find_def_file(self, table_name: str) -> Optional[str]:
        """
        根据表名查找对应的定义文件路径

        Args:
            table_name: 表名

        Returns:
            定义文件路径或 None
        """
        return self._table_to_file.get(table_name)

    def get_all_tables(self) -> List[str]:
        """获取所有已注册的表名"""
        return list(self._table_to_file.keys())

    def is_registered(self, table_name: str) -> bool:
        """检查表是否已注册"""
        return table_name in self._table_to_file

    def get_column_names(self, table_name: str) -> List[str]:
        """
        获取表的字段名列表

        Args:
            table_name: 表名

        Returns:
            字段名列表，若表未注册则返回空列表
        """
        schema = self.get_schema(table_name)
        if schema:
            return [c.name for c in schema.columns]
        return []
```

### B.4 关联示例

根据参考文件的实际关联关系：

```
┌─────────────────┐     关联      ┌─────────────────┐
│  SAS 代码表名   │ ───────────▶  │  定义文件        │
├─────────────────┤               ├─────────────────┤
│  churn_raw      │ ───────────▶  │  def_Churn.sas   │
│  loan_raw       │ ───────────▶  │  def_train.sas   │
└─────────────────┘               └─────────────────┘
```

**字段映射示例 (churn_raw)**:

| 定义文件中的字段 | 位置 | 类型 |
|-----------------|------|------|
| CustomerId | 1 | PK2.0 |
| Surname | 3 | PK2.0 |
| CreditScore | 5 | PK3.0 |
| Geography | 8 | S370FPD2.0 |
| Gender | 10 | $EBCDIC3. |
| Age | 13 | S370FPD6.0 |
| Tenure | 19 | S370FPD6.0 |
| Balance | 25 | S370FPD7.0 |
| NumOfProducts | 32 | S370FPD7.0 |
| HasCrCard | 39 | PK1.0 |
| IsActiveMember | 40 | PK1.0 |
| EstimagteSalary | 41 | S370FPD7.0 |
| Exited | 48 | S370FPD7.0 |

---

## 修订记录

### 第 1 轮修订
- 初始版本完成

### 第 2 轮修订
- 补充 Mainframe 定义文件 (def_*.sas) 的解析规则
- 补充字段提取逻辑（支持简单字段名和带引号的复杂字段名）
- 补充表名与定义文件的关联机制（定义注册表、关联策略）
- 完善 SAS 代码解析器实现
- 完善血缘关系解析器实现
