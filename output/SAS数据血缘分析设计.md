# SAS 数据血缘分析模块 技术设计文档

## 1. 项目概述

### 1.1 项目背景

本项目旨在构建一个 Python 应用模块，用于自动分析 SAS 代码的数据血缘关系，生成源表/源字段到目标表/目标字段的映射对照表。

核心挑战：
- 实际场景中 SAS 代码和文件数量较多，无法一次性全部提交给 LLM
- 需要支持增量处理和分批次分析
- 数据源类型多样：Mainframe SAS 数据集（`.sas7bdat`）、CSV 文件、Excel 文件
- 输出统一为 CSV 格式

### 1.2 核心目标

| 目标 | 描述 |
|------|------|
| 血缘追溯 | 从输出 CSV 出发，逆向追溯每个字段的来源 |
| 关系类型识别 | 区分透传、重命名、衍生计算、多源合并等关系类型 |
| 批量处理 | 支持处理大量 SAS 文件，避免 LLM 上下文溢出 |
| 可验证性 | 输出结果可追溯、可验证 |

### 1.3 预期输出格式

```csv
output_table,output_column,original_table,original_column,formula,script_file
churn_out,credit_scr,churn_raw,CreditScore,rename CreditScore -> credit_scr,/path/to/01_churn_transform.sas
churn_out,bal_per_prod,churn_raw,Balance; NumOfProducts,Balance / num_prod,/path/to/01_churn_transform.sas
merged_out,risk_score,churn_raw; loan_raw,CreditScore; Debit_to_Income,credit_scr - (dti * 10),/path/to/03_merge_transform.sas
```

**字段说明：**

| 字段名 | 说明 | 示例 |
|--------|------|------|
| output_table | 输出表/文件名 | churn_out |
| output_column | 输出字段名 | credit_scr |
| original_table | 源表名（多个用分号分隔） | churn_raw; loan_raw |
| original_column | 源字段名（多个用分号分隔） | CreditScore; Debit_to_Income |
| formula | 转换关系类型和表达式 | rename / passthrough / 计算表达式 |
| script_file | 解析使用的 SAS 脚本路径 | /path/to/01_churn_transform.sas |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           主控制层 (Orchestrator)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ 文件扫描器   │  │ 批次管理器   │  │ 结果聚合器   │  │ 增量缓存管理器  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                          处理管道 (Processing Pipeline)                  │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────┐ │
│  │ SAS 解析器   │ -> │ 血缘构建器   │ -> │ LLM 增强器  │ -> │ 输出生成器│ │
│  │ Parser      │    │ LineageBuilder│    │ LLMAugmenter│    │ Formatter│ │
│  └─────────────┘    └─────────────┘    └─────────────┘    └──────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                           外部依赖层 (External Dependencies)              │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────┐  │
│  │ LLM Provider      │  │ 缓存存储 (SQLite) │  │ 配置管理器            │  │
│  │ (OpenAI/Anthropic)│  │                   │  │                       │  │
│  └───────────────────┘  └───────────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 处理流程

```
1. 扫描输入目录
   ├── 发现所有 .sas 脚本文件
   ├── 发现所有输出 CSV 文件（根据目录结构或命名约定识别）
   └── 建立文件列表

2. 增量处理循环
   ├── 批次分组（每批次 N 个文件，防止上下文溢出）
   ├── 对每个批次执行处理管道
   │   ├── SAS 解析：提取 SET/MERGE/DATA 语句
   │   ├── 血缘构建：建立字段级映射关系
   │   ├── LLM 增强：解析复杂表达式和多源依赖
   │   └── 格式化输出
   └── 结果持久化到缓存

3. 结果聚合
   ├── 合并所有批次结果
   ├── 去重和冲突解决
   └── 生成最终 CSV 报告
```

### 2.3 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 分析入口 | 从输出 CSV 出发 | 用户关心的是最终输出的字段来源 |
| LLM 调用粒度 | 以 SAS 文件为单位 | 保持上下文相关性，减少 token 消耗 |
| 批次大小 | 默认 10 个文件/批次 | 根据 LLM 上下文窗口动态调整 |
| 缓存策略 | SQLite 本地缓存 | 支持增量处理，避免重复解析 |
| 血缘表示 | 结构化字段级映射 | 便于下游应用消费和验证 |

---

## 3. 核心模块详细设计

### 3.1 SAS 解析器 (SAS Parser)

**职责：** 将 SAS 代码解析为结构化的中间表示（IR），提取数据转换逻辑。

**关键 SAS 语法支持：**

```python
class SASStatementType(Enum):
    DATA_STEP = "data_step"           # DATA output_table; SET input_table
    MERGE_STEP = "merge_step"          # MERGE table1 table2; BY key
    PROC_IMPORT = "proc_import"        # PROC IMPORT -> 定义输入文件
    PROC_EXPORT = "proc_export"        # PROC EXPORT -> 定义输出文件
    PROC_SORT = "proc_sort"            # PROC SORT -> 不影响血缘
    RENAME = "rename"                  # RENAME 子句
    KEEP = "keep"                      # KEEP 子句
    DROP = "drop"                      # DROP 子句
    ASSIGNMENT = "assignment"          # 赋值语句（衍生字段）
    INFMT = "informat"                 # 数据定义语句
```

**解析器输出结构：**

```python
@dataclass
class SASDataStep:
    """单个 DATA 步骤"""
    output_table: str
    input_tables: List[str]           # SET/MERGE 的输入表
    statements: List[SASStatement]
    
@dataclass
class FieldMapping:
    """字段映射关系"""
    output_field: str
    source_field: str
    mapping_type: MappingType          # PASSTHROUGH, RENAME, DERIVED, MERGE
    source_table: Optional[str]        # 明确来源表（用于 MERGE）
    formula: Optional[str]              # 计算表达式
    line_number: int                   # 代码行号
    script_path: str

@dataclass
class ParsedScript:
    """解析后的脚本"""
    path: Path
    data_steps: List[SASDataStep]
    imports: List[ImportInfo]
    exports: List[ExportInfo]
    field_mappings: List[FieldMapping]
```

**解析示例：**

```sas
DATA churn_out;
    SET churn_raw (RENAME=(CreditScore = credit_scr
                            EstimatedSalary = est_sal));
    bal_per_prod = Balance / num_prod;
    KEEP CustomerId Geography Gender Age Tenure Balance Exited
         credit_scr est_sal num_prod bal_per_prod senior_flag;
RUN;
```

解析输出：
```
output_table: churn_out
input_tables: [churn_raw]
mappings:
  - credit_scr <- CreditScore (RENAME)
  - est_sal <- EstimatedSalary (RENAME)
  - bal_per_prod = Balance / num_prod (DERIVED)
  - CustomerId, Geography, Gender, Age, Tenure, Balance, Exited (PASSTHROUGH)
  - senior_flag = (Age >= 60) (DERIVED)
```

### 3.2 血缘构建器 (Lineage Builder)

**职责：** 将解析器输出转换为完整的血缘关系图。

**核心数据结构：**

```python
@dataclass
class ColumnLineage:
    """单个字段的血缘链路"""
    output_table: str
    output_column: str
    sources: List[SourceRef]            # 可能来自多个源
    transformation: str                 # 转换表达式
    script_path: str
    
@dataclass
class SourceRef:
    """来源引用"""
    table: str
    column: str
    is_primary: bool = True            # 是否为主来源

@dataclass
class LineageGraph:
    """完整血缘图"""
    nodes: Dict[str, TableNode]        # 表节点
    edges: List[LineageEdge]            # 血缘边
    column_mappings: List[ColumnLineage]
    
@dataclass
class TableNode:
    """表节点"""
    name: str
    table_type: TableType               # CSV, SAS7BDAT, MAINFRAME, INTERMEDIATE
    file_path: Optional[Path]
    source_location: str                # 物理路径或逻辑名
```

**血缘构建算法：**

```
Algorithm: BuildColumnLineage(script, output_table)
Input: ParsedScript, target_output_table
Output: List[ColumnLineage]

1. 找到 target_output_table 对应的 DATA 步骤
2. 分析 INPUT_TABLES:
   - 如果是 SET：单源，直接建立映射
   - 如果是 MERGE：多源，需要跟踪 BY 语句确定 join key
3. 处理 RENAME 子句：
   - 记录原始字段名 -> 新字段名 的映射
4. 处理 KEEP/DROP 子句：
   - 确定最终输出的字段集合
5. 分析赋值语句：
   - 提取表达式中的变量引用
   - 解析计算公式
6. 对于复杂表达式，标记为需要 LLM 增强
7. 返回 ColumnLineage 列表
```

### 3.3 LLM 增强器 (LLM Augmenter)

**职责：** 使用 LLM 解析无法通过规则解析的复杂表达式。

**触发条件：** 以下场景需要 LLM 介入：
1. 复杂的多字段计算表达式
2. 宏变量引用（`&macro_var`）
3. 条件逻辑（IF-THEN-ELSE）
4. 函数调用（如 `CALCULATED` 引用）
5. PROC SQL 语句
6. 多层嵌套的 DATA 步骤

**LLM Prompt 模板：**

```python
LINEAGE_ANALYSIS_PROMPT = """
你是一个数据血缘分析专家。请分析以下 SAS 代码片段，提取指定输出字段的来源信息。

## 代码片段
```sas
{sas_code}
```

## 目标输出
表名: {output_table}
字段: {target_column}

## 分析要求
1. 追溯该字段的直接来源（源表、源字段）
2. 如果是计算字段，给出计算表达式
3. 说明字段转换类型（passthrough/rename/derived/merge）

## 输出格式
JSON格式:
{{
    "source_table": "源表名",
    "source_column": "源字段名",
    "transformation_type": "passthrough|rename|derived|merge",
    "formula": "计算表达式（如有）",
    "confidence": "high|medium|low"
}}

只输出JSON，不要有其他内容。
"""
```

**批处理策略：**

```python
class LLMBatchProcessor:
    """LLM 批处理器"""
    
    def __init__(self, llm_client, max_batch_size: int = 10):
        self.llm = llm_client
        self.max_batch_size = max_batch_size
        self._pending_requests: List[AnalysisRequest] = []
        
    async def process_batch(self, requests: List[AnalysisRequest]) -> List[AnalysisResult]:
        """批量处理请求，合并为一个 LLM 调用"""
        # 将多个字段分析请求合并为一个 prompt
        combined_prompt = self._combine_prompts(requests)
        
        # 调用 LLM
        response = await self.llm.agenerate([combined_prompt])
        
        # 解析响应并拆分结果
        return self._parse_combined_response(response, requests)
```

### 3.4 主控制器 (Orchestrator)

**职责：** 协调整个处理流程，管理批次和状态。

```python
class LineageOrchestrator:
    """血缘分析主控制器"""
    
    def __init__(
        self,
        config: AppConfig,
        parser: SASParser,
        lineage_builder: LineageBuilder,
        llm_augmenter: Optional[LLMAugmenter],
        cache_manager: CacheManager
    ):
        self.config = config
        self.parser = parser
        self.builder = lineage_builder
        self.augmenter = llm_augmenter
        self.cache = cache_manager
        
    def analyze(
        self,
        input_path: Path,
        output_csv: Optional[Path] = None
    ) -> LineageResult:
        """
        入口方法：执行完整的血缘分析流程
        
        Args:
            input_path: SAS 脚本目录或文件
            output_csv: 可选，指定输出 CSV 路径
            
        Returns:
            LineageResult: 包含血缘关系和分析报告
        """
        # 1. 扫描文件
        sas_files, output_files = self._scan_directory(input_path)
        
        # 2. 建立分析队列（按依赖关系排序）
        analysis_queue = self._build_analysis_queue(sas_files, output_files)
        
        # 3. 增量处理
        all_results = []
        for batch in self._batch_requests(analysis_queue):
            batch_results = self._process_batch(batch)
            all_results.extend(batch_results)
            
            # 持久化中间结果
            self.cache.save_batch(batch_results)
            
        # 4. 聚合结果
        final_result = self._aggregate_results(all_results)
        
        # 5. 输出
        if output_csv:
            self._export_to_csv(final_result, output_csv)
            
        return final_result
```

---

## 4. 数据模型

### 4.1 核心实体

```python
# === 血缘关系实体 ===

@dataclass
class ColumnLineage:
    """字段级血缘"""
    output_table: str
    output_column: str
    source_tables: List[str]           # 用分号分隔存储
    source_columns: List[str]          # 用分号分隔存储
    transformation_type: str            # passthrough | rename | derived | merge
    formula: str
    script_file: str
    confidence: str = "high"
    is_verified: bool = False

@dataclass
class TableLineage:
    """表级血缘"""
    output_table: str
    output_file: str
    source_tables: List[SourceTable]
    script_files: List[str]

@dataclass
class SourceTable:
    """源表定义"""
    table_name: str
    table_type: TableType              # CSV, SAS7BDAT, MAINFRAME
    file_path: Optional[str]
    libname: Optional[str]             # SAS libname

# === 枚举定义 ===

class TableType(Enum):
    CSV = "csv"
    SAS7BDAT = "sas7bdat"
    MAINFRAME = "mainframe"
    EXCEL = "excel"
    INTERMEDIATE = "intermediate"
    UNKNOWN = "unknown"

class TransformationType(Enum):
    PASSTHROUGH = "passthrough"        # 直接透传
    RENAME = "rename"                   # 重命名
    DERIVED = "derived"                # 衍生计算
    MERGE = "merge"                    # 多源合并
    CONDITIONAL = "conditional"        # 条件逻辑
    AGGREGATE = "aggregate"            # 聚合操作
```

### 4.2 缓存模型

```sql
-- SQLite 缓存表结构

CREATE TABLE parsed_scripts (
    id INTEGER PRIMARY KEY,
    script_path TEXT UNIQUE NOT NULL,
    script_hash TEXT NOT NULL,
    parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_steps_json TEXT,
    field_mappings_json TEXT
);

CREATE TABLE column_lineage (
    id INTEGER PRIMARY KEY,
    output_table TEXT NOT NULL,
    output_column TEXT NOT NULL,
    source_tables TEXT,                -- 分号分隔
    source_columns TEXT,               -- 分号分隔
    transformation_type TEXT NOT NULL,
    formula TEXT,
    script_file TEXT NOT NULL,
    confidence TEXT DEFAULT 'high',
    is_verified INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(output_table, output_column, script_file)
);

CREATE TABLE processing_queue (
    id INTEGER PRIMARY KEY,
    script_path TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',     -- pending | processing | completed | failed
    priority INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE TABLE analysis_sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    total_files INTEGER,
    processed_files INTEGER,
    total_lineage_records INTEGER
);
```

---

## 5. API 设计

### 5.1 核心接口

```python
# === 公开 API ===

class LineageAnalyzer:
    """血缘分析器主类"""
    
    def analyze_directory(
        self,
        directory: str | Path,
        output_path: Optional[str | Path] = None,
        config: Optional[AnalysisConfig] = None
    ) -> LineageResult:
        """
        分析目录下所有 SAS 文件的血缘关系
        
        Args:
            directory: 包含 SAS 文件的目录路径
            output_path: 可选的输出 CSV 路径
            config: 分析配置
            
        Returns:
            LineageResult: 血缘分析结果
        """
        pass
    
    def analyze_script(
        self,
        script_path: str | Path,
        output_table: Optional[str] = None
    ) -> List[ColumnLineage]:
        """
        分析单个 SAS 脚本的血缘关系
        
        Args:
            script_path: SAS 脚本路径
            output_table: 可选，指定目标输出表
            
        Returns:
            字段血缘列表
        """
        pass
    
    def analyze_from_output(
        self,
        output_csv: str | Path,
        source_directory: str | Path
    ) -> List[ColumnLineage]:
        """
        从输出 CSV 出发，追溯其血缘
        
        Args:
            output_csv: 输出 CSV 文件
            source_directory: SAS 脚本所在目录
            
        Returns:
            字段血缘列表
        """
        pass

@dataclass
class AnalysisConfig:
    """分析配置"""
    batch_size: int = 10               # 每批处理文件数
    use_llm: bool = True               # 是否启用 LLM
    llm_provider: str = "openai"        # LLM 提供商
    cache_enabled: bool = True         # 是否启用缓存
    max_workers: int = 4               # 并行工作线程数
    timeout_seconds: int = 300        # LLM 调用超时
    confidence_threshold: float = 0.8 # 置信度阈值

@dataclass
class LineageResult:
    """分析结果"""
    total_files: int
    processed_files: int
    failed_files: List[str]
    column_lineages: List[ColumnLineage]
    table_lineages: List[TableLineage]
    execution_time: float
    session_id: str
```

### 5.2 命令行接口

```bash
# 基本用法
python -m sas_lineage.analyze /path/to/sas/files --output lineage_report.csv

# 高级选项
python -m sas_lineage.analyze \
    /path/to/sas/files \
    --output lineage_report.csv \
    --batch-size 5 \
    --llm-provider anthropic \
    --no-cache \
    --from-output /path/to/output.csv \
    --verbose

# 从输出 CSV 追溯
python -m sas_lineage.trace \
    --output-file merged_out.csv \
    --source-dir /path/to/sas/files \
    --format json
```

---

## 6. LLM 集成设计

### 6.1 Provider 抽象

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """LLM Provider 抽象基类"""
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        **kwargs
    ) -> str:
        """生成文本响应"""
        pass
    
    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: Dict,
        **kwargs
    ) -> Dict:
        """生成结构化 JSON 响应"""
        pass

class OpenAIProvider(LLMProvider):
    """OpenAI 实现"""
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        
class AnthropicProvider(LLMProvider):
    """Anthropic 实现"""
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet"):
        self.client = Anthropic(api_key=api_key)
        self.model = model

class LocalProvider(LLMProvider):
    """本地模型实现（Ollama 等）"""
    def __init__(self, base_url: str, model: str = "llama3"):
        self.base_url = base_url
        self.model = model
```

### 6.2 配置管理

```yaml
# config.yaml
llm:
  provider: "anthropic"  # openai | anthropic | local
  model: "claude-3-5-sonnet-20240620"
  api_key: "${ANTHROPIC_API_KEY}"  # 从环境变量读取
  temperature: 0.0
  max_tokens: 4096
  
processing:
  batch_size: 10
  max_workers: 4
  timeout_seconds: 300
  retry_attempts: 3
  
cache:
  enabled: true
  db_path: "./lineage_cache.db"
  ttl_hours: 24
  
paths:
  input_dir: "./sas_files"
  output_dir: "./output"
  cache_dir: "./cache"
  
output:
  format: "csv"  # csv | json | xlsx
  include_header: true
  encoding: "utf-8"
```

---

## 7. 关键算法

### 7.1 字段溯源算法

```python
def trace_field_lineage(
    data_step: SASDataStep,
    target_field: str,
    intermediate_renames: Dict[str, Dict[str, str]]
) -> FieldSource:
    """
    追溯单个字段的血缘来源
    
    Algorithm:
    1. 检查是否是 RENAME 映射的结果
    2. 检查是否是赋值语句的定义
    3. 检查是否在 KEEP 列表中（透传）
    4. 如果来自 MERGE，确定来自哪个源表
    
    Args:
        data_step: DATA 步骤
        target_field: 目标字段
        intermediate_renames: 中间重命名映射
        
    Returns:
        FieldSource: 字段来源信息
    """
    # Step 1: 检查重命名映射
    for rename in data_step.renames:
        if rename.new_name == target_field:
            return FieldSource(
                table=rename.source_table or data_step.input_tables[0],
                column=rename.old_name,
                transformation=TransformationType.RENAME,
                formula=f"rename {rename.old_name} -> {target_field}"
            )
    
    # Step 2: 检查赋值语句
    for assignment in data_step.assignments:
        if assignment.target == target_field:
            source_fields = extract_field_references(assignment.expression)
            return FieldSource(
                table=data_step.input_tables,  # 可能多表
                column=source_fields,
                transformation=TransformationType.DERIVED,
                formula=assignment.expression
            )
    
    # Step 3: 检查 KEEP 列表（透传）
    if target_field in data_step.keep_fields:
        # 需要确定来源表（用于 MERGE）
        source_table, source_column = resolve_keep_field(
            target_field,
            data_step
        )
        return FieldSource(
            table=source_table,
            column=source_column,
            transformation=TransformationType.PASSTHROUGH
        )
    
    # Step 4: 无法确定，需要 LLM 介入
    return FieldSource(
        table="UNKNOWN",
        column="UNKNOWN",
        transformation=TransformationType.UNKNOWN,
        needs_llm=True
    )
```

### 7.2 依赖排序算法

```python
def topological_sort(scripts: List[ParsedScript]) -> List[ParsedScript]:
    """
    根据依赖关系对脚本进行拓扑排序
    
    确保处理顺序：先处理被依赖的脚本
    """
    # 构建依赖图
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    
    all_tables = set()
    for script in scripts:
        for step in script.data_steps:
            all_tables.add(step.output_table)
            for input_table in step.input_tables:
                graph[input_table].append(step.output_table)
                in_degree[step.output_table] += 1
    
    # Kahn 算法
    queue = deque([t for t in all_tables if in_degree[t] == 0])
    result = []
    
    while queue:
        table = queue.popleft()
        # 找到生成该表的脚本
        for script in scripts:
            for step in script.data_steps:
                if step.output_table == table:
                    result.append(script)
                    break
        
        for dependent in graph[table]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    
    return result
```

---

## 8. 项目结构

```
sas_lineage/
├── __init__.py
├── main.py                    # 入口点
├── cli.py                     # 命令行接口
│
├── config/
│   ├── __init__.py
│   ├── settings.py            # 配置加载
│   └── default_config.yaml    # 默认配置
│
├── core/
│   ├── __init__.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── sas_parser.py      # SAS 解析器
│   │   ├── sas_lexer.py       # 词法分析器
│   │   ├── sas_nodes.py       # AST 节点定义
│   │   └── statement_types.py # 语句类型枚举
│   │
│   ├── lineage/
│   │   ├── __init__.py
│   │   ├── builder.py         # 血缘构建器
│   │   ├── tracer.py          # 字段溯源
│   │   └── models.py          # 血缘数据模型
│   │
│   └── llm/
│       ├── __init__.py
│       ├── base.py            # Provider 抽象
│       ├── openai.py          # OpenAI 实现
│       ├── anthropic.py       # Anthropic 实现
│       ├── local.py           # 本地模型实现
│       └── augmenter.py        # LLM 增强器
│
├── cache/
│   ├── __init__.py
│   ├── manager.py             # 缓存管理器
│   └── migrations.py          # 数据库迁移
│
├── output/
│   ├── __init__.py
│   ├── csv_formatter.py       # CSV 输出格式化
│   ├── json_formatter.py      # JSON 输出格式化
│   └── report_generator.py    # 报告生成
│
├── utils/
│   ├── __init__.py
│   ├── file_scanner.py        # 文件扫描
│   ├── batch_processor.py     # 批处理
│   └── decorators.py          # 工具装饰器
│
├── orchestrator/
│   ├── __init__.py
│   ├── coordinator.py         # 主控制器
│   └── state_machine.py       # 状态机
│
└── tests/
    ├── __init__.py
    ├── test_parser.py
    ├── test_lineage_builder.py
    ├── test_llm_augmenter.py
    ├── fixtures/
    │   ├── simple_transform.sas
    │   ├── merge_transform.sas
    │   └── expected_lineage.csv
    └── conftest.py
```

---

## 9. 异常处理

```python
class LineageError(Exception):
    """基础异常"""
    pass

class ParseError(LineageError):
    """解析错误"""
    def __init__(self, message: str, line_number: int, script_path: str):
        self.line_number = line_number
        self.script_path = script_path
        super().__init__(f"{script_path}:{line_number} - {message}")

class LLMError(LineageError):
    """LLM 调用错误"""
    pass

class CacheError(LineageError):
    """缓存错误"""
    pass

class ConfigurationError(LineageError):
    """配置错误"""
    pass

# 全局异常处理
def handle_error(error: LineageError) -> None:
    """统一错误处理"""
    if isinstance(error, ParseError):
        logger.error(f"Parse error in {error.script_path} at line {error.line_number}")
        # 可以选择跳过该文件继续处理
    elif isinstance(error, LLMError):
        logger.warning(f"LLM error, falling back to rule-based analysis")
        # 回退到规则解析
    else:
        logger.error(f"Unexpected error: {error}")
        raise
```

---

## 10. 测试策略

### 10.1 单元测试

```python
# tests/test_parser.py

class TestSASParser:
    """解析器单元测试"""
    
    def test_parse_simple_data_step(self):
        """测试简单 DATA 步骤解析"""
        code = """
        DATA churn_out;
            SET churn_raw;
            KEEP CustomerId Age Balance;
        RUN;
        """
        result = self.parser.parse(code)
        assert result.data_steps[0].output_table == "churn_out"
        assert result.data_steps[0].input_tables == ["churn_raw"]
        
    def test_parse_rename_clause(self):
        """测试 RENAME 子句解析"""
        code = """
        DATA churn_out;
            SET churn_raw (RENAME=(CreditScore = credit_scr));
        RUN;
        """
        result = self.parser.parse(code)
        renames = result.data_steps[0].renames
        assert renames[0].old_name == "CreditScore"
        assert renames[0].new_name == "credit_scr"
        
    def test_parse_merge_step(self):
        """测试 MERGE 步骤解析"""
        code = """
        DATA merged_out;
            MERGE table1 table2;
            BY CustomerId;
        RUN;
        """
        result = self.parser.parse(code)
        assert len(result.data_steps[0].input_tables) == 2
```

### 10.2 集成测试

```python
# tests/test_lineage_builder.py

class TestLineageBuilder:
    """血缘构建集成测试"""
    
    def test_churn_transform_lineage(self):
        """测试 churn_transform 的血缘关系"""
        script_path = Path("tests/fixtures/01_churn_transform.sas")
        result = self.builder.build_from_script(script_path)
        
        # 验证关键映射
        credit_scr = self._find_mapping(result, "churn_out", "credit_scr")
        assert credit_scr.source_column == "CreditScore"
        assert credit_scr.transformation == "rename"
        
    def test_merge_lineage(self):
        """测试 MERGE 语句的血缘"""
        script_path = Path("tests/fixtures/03_merge_transform.sas")
        result = self.builder.build_from_script(script_path)
        
        risk_score = self._find_mapping(result, "merged_out", "risk_score")
        assert "churn_raw" in risk_score.source_tables
        assert "loan_raw" in risk_score.source_tables
        assert "derived" in risk_score.transformation
```

### 10.3 端到端测试

```python
# tests/test_e2e.py

class TestEndToEnd:
    """端到端测试"""
    
    def test_full_pipeline(self, tmp_path):
        """测试完整处理流程"""
        # 准备测试数据
        test_dir = tmp_path / "sas_files"
        test_dir.mkdir()
        
        # 复制测试文件
        shutil.copy("tests/fixtures/01_churn_transform.sas", test_dir)
        shutil.copy("tests/fixtures/02_loan_transform.sas", test_dir)
        
        # 执行分析
        analyzer = LineageAnalyzer()
        result = analyzer.analyze_directory(test_dir)
        
        # 验证结果
        assert result.processed_files == 2
        assert len(result.column_lineages) > 0
        
        # 验证输出文件
        output_csv = tmp_path / "lineage.csv"
        assert output_csv.exists()
        
        df = pd.read_csv(output_csv)
        assert "output_table" in df.columns
        assert "output_column" in df.columns
```

---

## 11. 配置参考

```yaml
# config.yaml 示例配置

app:
  name: "SAS Lineage Analyzer"
  version: "1.0.0"
  debug: false

llm:
  provider: "anthropic"
  model: "claude-3-5-sonnet-20240620"
  api_key: "${ANTHROPIC_API_KEY}"
  temperature: 0.0
  max_tokens: 4096
  timeout: 300

processing:
  batch_size: 10
  max_workers: 4
  retry_attempts: 3
  retry_delay: 5
  
cache:
  enabled: true
  db_path: "./lineage_cache.db"
  ttl_hours: 24
  auto_cleanup: true

paths:
  input_dir: "./sas_files"
  output_dir: "./output"
  temp_dir: "./temp"

output:
  format: "csv"
  include_header: true
  encoding: "utf-8"
  delimiter: ","
  
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "./lineage_analyzer.log"
```

---

## 12. 附录：SAS 语法支持矩阵

| 语法元素 | 支持状态 | 说明 |
|----------|----------|------|
| DATA step | ✅ 完全支持 | DATA、SET、RENAME、KEEP、DROP |
| MERGE step | ✅ 完全支持 | MERGE、BY、IN= 选项 |
| PROC IMPORT | ✅ 支持 | CSV、Excel 导入 |
| PROC EXPORT | ✅ 支持 | CSV 导出 |
| PROC SORT | ⚪ 透明 | 不影响血缘 |
| PROC SQL | 🔄 部分支持 | 需要 LLM 增强 |
| 宏变量 | 🔄 部分支持 | 需要 LLM 增强 |
| PROC FORMAT | ⚪ 忽略 | 不影响字段血缘 |
| CALL 语句 | ⚪ 忽略 | 不影响字段血缘 |
| PROC MEANS/SUMMARY | 🔄 部分支持 | 需要 LLM 增强 |
| 条件逻辑 (IF) | 🔄 部分支持 | 需要 LLM 增强 |

**状态说明：**
- ✅ 完全支持：通过规则解析可完整处理
- 🔄 部分支持：基础规则解析 + LLM 增强
- ⚪ 透明/忽略：不直接影响血缘或暂不支持

---

## 修订记录

### 第 1 轮修订
- 初始版本创建
