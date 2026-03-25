# SAS数据血缘分析系统技术设计文档

## 1. 文档概述

### 1.1 目标
设计一个Python应用模块，用于分析SAS代码和数据集，提取数据血缘关系，输出字段级别的源-目标映射对照表。

### 1.2 输入输出规范

**输入：**
- SAS代码文件（`.sas`）：数据处理代码、数据集定义代码
- 数据文件：`.csv`、`.xlsx`、`.sas7bdat`
- 支持mainframe SAS数据集定义（通过`def_*.sas`文件）

**输出：**
- CSV格式的血缘对照表，包含字段：
  - `output_table`: 输出表名
  - `output_column`: 输出字段名
  - `original_table`: 源表名（多源用`;`分隔）
  - `original_column`: 源字段名（多源用`;`分隔）
  - `formula`: 转换公式（`passthrough`/`rename`/`表达式`）
  - `script_file`: SAS脚本文件路径

### 1.3 技术栈
- Python 3.12+
- LangChain / LangGraph（工作流编排）
- 可配置LLM Provider（OpenAI、Azure OpenAI、本地模型等）
- Pandas（数据处理）
- Pydantic（数据验证）

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SAS Lineage Analyzer                          │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Scanner    │→│   Parser     │→│  Analyzer    │→│   Exporter   │ │
│  │  (文件扫描)   │  │  (代码解析)   │  │  (血缘分析)   │  │  (结果导出)   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│         │                │                 │                 │          │
│         ▼                ▼                 ▼                 ▼          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    LangGraph Workflow Engine                      │   │
│  │  (工作流编排：扫描 → 解析 → 分析 → 验证 → 导出)                      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│         │                                                               │
│         ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    LLM Provider (Configurable)                    │   │
│  │         (分块处理、提示工程、结果解析、缓存机制)                      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件职责

| 组件 | 职责 | 关键技术 |
|------|------|----------|
| **FileScanner** | 递归扫描输入目录，识别SAS代码文件和数据文件，建立文件索引 | `pathlib`, 文件类型检测 |
| **SASParser** | 解析SAS代码，提取DATA步、PROC步、字段定义等结构化信息 | 正则表达式、LLM辅助解析 |
| **LineageAnalyzer** | 基于解析结果构建血缘图，追溯字段来源 | 图算法、拓扑排序 |
| **LLMClient** | 管理LLM调用，实现分块处理策略 | LangChain、Token计算 |
| **ExportManager** | 将血缘关系导出为CSV格式 | Pandas |
| **WorkflowEngine** | 编排完整分析流程，支持失败重试 | LangGraph |

---

## 3. 数据模型设计

### 3.1 核心实体

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class TransformType(str, Enum):
    """字段转换类型"""
    PASSTHROUGH = "passthrough"      # 直接透传
    RENAME = "rename"                # 重命名
    DERIVED = "derived"              # 派生计算
    AGGREGATION = "aggregation"      # 聚合
    JOIN = "join"                    # 关联

class DataSource(BaseModel):
    """数据源定义"""
    source_id: str                   # 唯一标识
    source_name: str                 # 数据集/文件名
    source_type: str                 # csv/excel/sas7bdat/mainframe
    file_path: Optional[str] = None  # 文件路径
    columns: List[Dict[str, Any]] = []  # 字段列表 [{name, type, length}]
    definition_file: Optional[str] = None  # def_*.sas文件路径

class ColumnMapping(BaseModel):
    """字段映射关系"""
    output_table: str                # 输出表名
    output_column: str               # 输出字段名
    source_tables: List[str]         # 源表名列表
    source_columns: List[str]        # 源字段名列表
    transform_type: TransformType    # 转换类型
    formula: str                     # 转换公式或描述
    script_file: str                 # 所属SAS脚本路径

class LineageGraph(BaseModel):
    """血缘关系图"""
    nodes: Dict[str, DataSource]     # 表节点 {table_name: DataSource}
    edges: List[ColumnMapping]       # 字段映射边
    
class AnalysisResult(BaseModel):
    """分析结果"""
    mappings: List[ColumnMapping]    # 字段映射列表
    errors: List[str] = []           # 错误信息
    warnings: List[str] = []         # 警告信息
```

### 3.2 输出CSV格式

```csv
output_table,output_column,original_table,original_column,formula,script_file
churn_out,credit_scr,churn_raw,CreditScore,rename CreditScore -> credit_scr,/path/to/01_churn_transform.sas
churn_out,bal_per_prod,churn_raw,Balance; NumOfProducts,Balance / num_prod,/path/to/01_churn_transform.sas
merged_out,risk_score,churn_raw; loan_raw,CreditScore; Debit_to_Income,credit_scr - (dti * 10),/path/to/03_merge_transform.sas
```

---

## 4. 模块详细设计

### 4.1 FileScanner 文件扫描模块

**职责：** 递归扫描输入目录，识别和分类所有相关文件。

**实现要点：**

```python
class FileScanner:
    """文件扫描器"""
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.sas_files: List[Path] = []
        self.data_files: List[Path] = []
        self.definition_files: List[Path] = []
    
    def scan(self) -> Dict[str, List[Path]]:
        """
        扫描目录，返回分类文件列表
        
        Returns:
            {
                'transform_scripts': [...],  # 转换脚本 *_transform.sas
                'definition_files': [...],   # 定义文件 def_*.sas
                'data_files': [...]          # 数据文件 csv/xlsx/sas7bdat
            }
        """
        # 递归遍历所有文件
        # 按文件名模式分类：
        # - def_*.sas → 数据集定义文件（mainframe字段定义）
        # - *_transform.sas → 数据转换脚本
        # - *.csv/*.xlsx/*.sas7bdat → 数据文件
        pass
    
    def build_file_index(self) -> Dict[str, Any]:
        """建立文件索引，关联定义文件与转换脚本"""
        # 分析文件名和注释中的关联关系
        pass
```

**扫描规则：**
1. `def_*.sas` 文件识别为数据集定义文件，解析字段结构
2. `*_transform.sas` 或包含 `DATA`/`PROC` 步骤的文件识别为转换脚本
3. 数据文件（`.csv`, `.xlsx`, `.sas7bdat`）记录路径和类型

### 4.2 SASParser SAS代码解析模块

**职责：** 解析SAS代码，提取DATA步、字段定义、转换逻辑等结构化信息。

**解析策略（混合模式）：**

```python
class SASParser:
    """SAS代码解析器"""
    
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        self.patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[str, Any]:
        """编译正则表达式模式"""
        return {
            'data_step': re.compile(r'DATA\s+(\w+)', re.IGNORECASE),
            'set_statement': re.compile(r'SET\s+([\w\s]+)(?:\s*\(|;)', re.IGNORECASE),
            'merge_statement': re.compile(r'MERGE\s+([\w\s]+);', re.IGNORECASE),
            'rename_option': re.compile(r'RENAME=\(([^)]+)\)', re.IGNORECASE),
            'keep_statement': re.compile(r'KEEP\s+([^;]+);', re.IGNORECASE),
            'assignment': re.compile(r'(\w+)\s*=\s*([^;]+);', re.IGNORECASE),
            'proc_export': re.compile(r'PROC EXPORT\s+DATA\s*=\s*(\w+)', re.IGNORECASE),
            'libname': re.compile(r'LIBNAME\s+(\w+)\s+["\']([^"\']+)', re.IGNORECASE),
        }
    
    def parse_transform_script(self, file_path: Path) -> Dict[str, Any]:
        """
        解析转换脚本
        
        Returns:
            {
                'output_tables': [
                    {
                        'table_name': 'churn_out',
                        'source_tables': ['churn_raw'],
                        'columns': [
                            {
                                'name': 'credit_scr',
                                'source': {'table': 'churn_raw', 'column': 'CreditScore'},
                                'transform': 'rename',
                                'formula': 'CreditScore -> credit_scr'
                            },
                            {
                                'name': 'bal_per_prod',
                                'source': {'table': 'churn_raw', 'column': 'Balance; NumOfProducts'},
                                'transform': 'derived',
                                'formula': 'Balance / num_prod'
                            }
                        ]
                    }
                ]
            }
        """
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        
        # Step 1: 规则解析提取基础结构
        base_structure = self._rule_based_parse(content)
        
        # Step 2: LLM辅助解析复杂表达式（如果启用）
        if self.use_llm:
            complex_parts = self._identify_complex_parts(content)
            llm_results = self._llm_enhanced_parse(complex_parts)
            base_structure = self._merge_results(base_structure, llm_results)
        
        return base_structure
    
    def parse_definition_file(self, file_path: Path) -> DataSource:
        """
        解析数据集定义文件（def_*.sas）
        
        解析mainframe数据集的字段定义：
        - infile语句中的recfm、lrecl
        - input语句中的字段位置、类型、格式
        """
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        
        # 提取字段定义
        columns = []
        # 匹配 @位置 字段名 格式 的模式
        # 例如: @1 CustomerId PK2.0
        
        return DataSource(
            source_id=file_path.stem,
            source_name=self._extract_dataset_name(content),
            source_type='mainframe',
            file_path=str(file_path),
            columns=columns
        )
    
    def _rule_based_parse(self, content: str) -> Dict[str, Any]:
        """基于规则的解析"""
        # 使用正则表达式提取：
        # - DATA语句（输出表）
        # - SET/MERGE语句（输入表）
        # - RENAME选项
        # - KEEP语句（输出字段列表）
        # - 赋值语句（派生字段公式）
        # - PROC EXPORT（确认最终输出）
        pass
    
    def _identify_complex_parts(self, content: str) -> List[str]:
        """识别需要LLM辅助解析的复杂部分"""
        # 复杂的派生表达式
        # 多源MERGE的字段关联
        # 条件逻辑（IF/THEN/ELSE）
        pass
```

**解析规则清单：**

| SAS语句 | 解析目标 | 正则模式 |
|---------|----------|----------|
| `DATA output_table;` | 输出表名 | `r'DATA\s+(\w+)'` |
| `SET input_table;` | 输入表名 | `r'SET\s+([\w\s]+)'` |
| `MERGE table1 table2;` | 多源输入 | `r'MERGE\s+([^;]+)'` |
| `RENAME=(old=new)` | 字段重命名 | `r'RENAME=\(([^)]+)\)'` |
| `col = expression;` | 派生公式 | `r'(\w+)\s*=\s*([^;]+)'` |
| `KEEP col1 col2;` | 输出字段 | `r'KEEP\s+([^;]+)'` |
| `PROC EXPORT DATA=table` | 确认输出 | `r'PROC EXPORT\s+DATA\s*=\s*(\w+)'` |

### 4.3 LineageAnalyzer 血缘分析引擎

**职责：** 构建血缘关系图，追溯每个输出字段到源字段的完整路径。

```python
class LineageAnalyzer:
    """血缘分析引擎"""
    
    def __init__(self):
        self.graph = LineageGraph(nodes={}, edges=[])
        self.visited = set()
    
    def build_lineage_graph(self, 
                           parsed_scripts: List[Dict],
                           definitions: List[DataSource]) -> LineageGraph:
        """
        构建血缘关系图
        
        Algorithm:
        1. 将所有表作为节点加入图
        2. 遍历每个脚本的每个输出字段
        3. 递归追溯字段来源，直到达到原始输入
        4. 记录完整的源-目标映射路径
        """
        # 添加节点
        for script in parsed_scripts:
            for table in script['output_tables']:
                self._add_table_node(table['table_name'])
        
        for def_file in definitions:
            self.graph.nodes[def_file.source_name] = def_file
        
        # 构建边（字段映射关系）
        for script in parsed_scripts:
            for table in script['output_tables']:
                for col in table['columns']:
                    mapping = self._trace_column_source(
                        table['table_name'],
                        col,
                        script['file_path']
                    )
                    self.graph.edges.append(mapping)
        
        return self.graph
    
    def _trace_column_source(self, 
                            output_table: str,
                            column: Dict,
                            script_file: str) -> ColumnMapping:
        """
        追溯字段来源
        
        处理场景：
        1. 单源透传：output_col = input_col
        2. 单源重命名：RENAME=(old_col=output_col)
        3. 单源派生：output_col = expression(input_col1, input_col2)
        4. 多源派生：MERGE后，output_col = expression(t1.col1, t2.col2)
        """
        transform_type = column.get('transform', 'passthrough')
        
        if transform_type == 'passthrough':
            source_tables = [column['source']['table']]
            source_columns = [column['source']['column']]
            formula = 'passthrough'
        elif transform_type == 'rename':
            source_tables = [column['source']['table']]
            source_columns = [column['source']['column']]
            formula = f"rename {column['source']['column']} -> {column['name']}"
        else:  # derived
            source_tables = column['source']['table'].split('; ')
            source_columns = column['source']['column'].split('; ')
            formula = column.get('formula', '')
        
        return ColumnMapping(
            output_table=output_table,
            output_column=column['name'],
            source_tables=source_tables,
            source_columns=source_columns,
            transform_type=TransformType(transform_type),
            formula=formula,
            script_file=script_file
        )
    
    def resolve_multi_hop_lineage(self) -> List[ColumnMapping]:
        """
        解析多跳血缘（中间表）
        
        场景：脚本A输出 → 脚本B输入 → 脚本B输出
        需要将脚本B的字段追溯到脚本A的原始输入
        """
        # 拓扑排序确定处理顺序
        # 对于每个输出表，如果其输入表也是其他脚本的输出表，
        # 则需要展开递归追溯
        pass
```

### 4.4 LLMClient LLM集成模块

**职责：** 管理LLM调用，实现智能分块处理策略。

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from typing import List, Callable
import tiktoken

class LLMClient:
    """LLM客户端"""
    
    DEFAULT_SYSTEM_PROMPT = """你是一个SAS代码分析专家。
你的任务是分析SAS代码片段，提取数据转换逻辑和字段血缘关系。
请准确识别：
1. 输入表和输出表
2. 字段映射关系（包括重命名）
3. 派生字段的计算公式
4. 多表关联（MERGE/JOIN）的字段来源

输出必须是严格的JSON格式。"""
    
    def __init__(self, 
                 provider: str = "openai",
                 model: str = "gpt-4",
                 api_key: Optional[str] = None,
                 max_tokens: int = 4000):
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.encoding = tiktoken.encoding_for_model(model)
        self._init_llm()
    
    def _init_llm(self):
        """初始化LLM客户端"""
        if self.provider == "openai":
            self.llm = ChatOpenAI(
                model=self.model,
                api_key=self.api_key,
                max_tokens=self.max_tokens,
                temperature=0.0  # 确定性输出
            )
        # 支持其他provider：azure, anthropic, local等
    
    def analyze_sas_chunk(self, 
                         chunk: str, 
                         context: Optional[Dict] = None) -> Dict:
        """
        分析SAS代码片段
        
        Args:
            chunk: SAS代码片段
            context: 上下文信息（相邻代码块、文件元数据）
        
        Returns:
            {
                'output_table': str,
                'input_tables': List[str],
                'column_mappings': List[{
                    'output_column': str,
                    'source_table': str,
                    'source_column': str,
                    'transform_type': str,
                    'formula': str
                }]
            }
        """
        messages = [
            SystemMessage(content=self.DEFAULT_SYSTEM_PROMPT),
            HumanMessage(content=self._build_prompt(chunk, context))
        ]
        
        response = self.llm.invoke(messages)
        return self._parse_response(response.content)
    
    def _build_prompt(self, chunk: str, context: Optional[Dict]) -> str:
        """构建分析提示词"""
        prompt = f"""请分析以下SAS代码片段，提取字段血缘关系：

```sas
{chunk}
```
"""
        if context:
            prompt += f"\n上下文信息：\n{json.dumps(context, ensure_ascii=False)}\n"
        
        prompt += """
请输出JSON格式结果：
{
    "output_table": "输出表名",
    "input_tables": ["输入表1", "输入表2"],
    "column_mappings": [
        {
            "output_column": "输出字段名",
            "source_table": "源表名",
            "source_column": "源字段名",
            "transform_type": "passthrough|rename|derived",
            "formula": "转换公式或描述"
        }
    ]
}
"""
        return prompt
    
    def chunk_file(self, 
                   file_content: str, 
                   max_chunk_tokens: int = 3000) -> List[str]:
        """
        将大文件分块
        
        分块策略：
        1. 优先按DATA步边界分割
        2. 单个DATA步过大时，按语句边界分割
        3. 保留必要的上下文（宏变量定义、LIBNAME等）
        """
        # 检测token数量
        total_tokens = len(self.encoding.encode(file_content))
        
        if total_tokens <= max_chunk_tokens:
            return [file_content]
        
        chunks = []
        # 按DATA步分割
        data_steps = self._split_by_data_steps(file_content)
        
        current_chunk = ""
        current_tokens = 0
        
        for step in data_steps:
            step_tokens = len(self.encoding.encode(step))
            
            if current_tokens + step_tokens > max_chunk_tokens:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = step
                current_tokens = step_tokens
            else:
                current_chunk += "\n" + step
                current_tokens += step_tokens
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def _split_by_data_steps(self, content: str) -> List[str]:
        """按DATA步边界分割代码"""
        # 匹配 DATA ... RUN; 的完整步骤
        pattern = r'(?:^|\n)(DATA\s+[^;]+;.*?RUN;)' 
        return re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
```

### 4.5 ExportManager 导出管理模块

**职责：** 将分析结果导出为标准CSV格式。

```python
import pandas as pd

class ExportManager:
    """导出管理器"""
    
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
    
    def export_lineage(self, 
                      graph: LineageGraph,
                      format: str = 'csv') -> str:
        """
        导出血缘关系
        
        Args:
            graph: 血缘关系图
            format: 输出格式（csv/json）
        
        Returns:
            输出文件路径
        """
        if format == 'csv':
            return self._export_csv(graph)
        elif format == 'json':
            return self._export_json(graph)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _export_csv(self, graph: LineageGraph) -> str:
        """导出为CSV格式"""
        rows = []
        for edge in graph.edges:
            row = {
                'output_table': edge.output_table,
                'output_column': edge.output_column,
                'original_table': '; '.join(edge.source_tables),
                'original_column': '; '.join(edge.source_columns),
                'formula': edge.formula,
                'script_file': edge.script_file
            }
            rows.append(row)
        
        df = pd.DataFrame(rows)
        
        # 按输出表和字段排序
        df = df.sort_values(['output_table', 'output_column'])
        
        output_file = self.output_path / 'lineage_report.csv'
        df.to_csv(output_file, index=False, encoding='utf-8')
        
        return str(output_file)
```

### 4.6 WorkflowEngine 工作流引擎

**职责：** 使用LangGraph编排完整分析流程。

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

class AnalysisState(TypedDict):
    """分析状态"""
    root_path: str
    scanned_files: Dict[str, List[Path]]
    parsed_results: List[Dict]
    lineage_graph: Optional[LineageGraph]
    output_file: Optional[str]
    errors: Annotated[List[str], operator.add]
    current_step: str

def create_workflow() -> StateGraph:
    """创建工作流图"""
    
    workflow = StateGraph(AnalysisState)
    
    # 定义节点
    workflow.add_node("scan_files", scan_files_node)
    workflow.add_node("parse_definitions", parse_definitions_node)
    workflow.add_node("parse_scripts", parse_scripts_node)
    workflow.add_node("build_lineage", build_lineage_node)
    workflow.add_node("resolve_hops", resolve_hops_node)
    workflow.add_node("export_results", export_results_node)
    
    # 定义边
    workflow.set_entry_point("scan_files")
    workflow.add_edge("scan_files", "parse_definitions")
    workflow.add_edge("parse_definitions", "parse_scripts")
    workflow.add_edge("parse_scripts", "build_lineage")
    workflow.add_edge("build_lineage", "resolve_hops")
    workflow.add_edge("resolve_hops", "export_results")
    workflow.add_edge("export_results", END)
    
    return workflow.compile()

def scan_files_node(state: AnalysisState) -> AnalysisState:
    """文件扫描节点"""
    scanner = FileScanner(state['root_path'])
    state['scanned_files'] = scanner.scan()
    state['current_step'] = 'scan_complete'
    return state

def parse_definitions_node(state: AnalysisState) -> AnalysisState:
    """解析定义文件节点"""
    parser = SASParser(use_llm=False)  # 定义文件使用规则解析
    definitions = []
    
    for file_path in state['scanned_files'].get('definition_files', []):
        try:
            ds = parser.parse_definition_file(file_path)
            definitions.append(ds)
        except Exception as e:
            state['errors'].append(f"Parse error in {file_path}: {e}")
    
    state['parsed_results'] = {'definitions': definitions}
    state['current_step'] = 'definitions_parsed'
    return state

def parse_scripts_node(state: AnalysisState) -> AnalysisState:
    """解析转换脚本节点"""
    parser = SASParser(use_llm=True)  # 转换脚本使用LLM辅助
    scripts = []
    
    for file_path in state['scanned_files'].get('transform_scripts', []):
        try:
            result = parser.parse_transform_script(file_path)
            result['file_path'] = str(file_path)
            scripts.append(result)
        except Exception as e:
            state['errors'].append(f"Parse error in {file_path}: {e}")
    
    state['parsed_results']['scripts'] = scripts
    state['current_step'] = 'scripts_parsed'
    return state

def build_lineage_node(state: AnalysisState) -> AnalysisState:
    """构建血缘图节点"""
    analyzer = LineageAnalyzer()
    graph = analyzer.build_lineage_graph(
        state['parsed_results']['scripts'],
        state['parsed_results']['definitions']
    )
    state['lineage_graph'] = graph
    state['current_step'] = 'lineage_built'
    return state

def export_results_node(state: AnalysisState) -> AnalysisState:
    """导出结果节点"""
    exporter = ExportManager('./output')
    output_file = exporter.export_lineage(state['lineage_graph'])
    state['output_file'] = output_file
    state['current_step'] = 'export_complete'
    return state
```

---

## 5. 关键算法设计

### 5.1 分块处理策略

**问题：** 实际场景SAS代码量大，不能一次性提交给LLM。

**解决方案：**

```python
class ChunkingStrategy:
    """分块策略"""
    
    def __init__(self, max_tokens: int = 3000, overlap_tokens: int = 200):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
    
    def create_chunks(self, file_path: Path) -> List[CodeChunk]:
        """
        创建代码块
        
        策略优先级：
        1. 按DATA步边界分割（保持语义完整）
        2. 单DATA步过大时，提取关键部分（RENAME、赋值语句）
        3. 保留全局上下文（宏变量、LIBNAME）到每个块
        """
        content = file_path.read_text()
        
        # 提取全局上下文
        global_context = self._extract_global_context(content)
        
        # 分割DATA步
        data_steps = self._extract_data_steps(content)
        
        chunks = []
        for step in data_steps:
            if self._estimate_tokens(step) > self.max_tokens:
                # 超大DATA步：提取关键语句
                sub_chunks = self._split_large_step(step, global_context)
                chunks.extend(sub_chunks)
            else:
                chunk = CodeChunk(
                    content=step,
                    context=global_context,
                    chunk_type='data_step'
                )
                chunks.append(chunk)
        
        return chunks
    
    def _extract_global_context(self, content: str) -> str:
        """提取全局上下文"""
        # 宏变量定义 %LET
        # LIBNAME定义
        # 文件头注释
        patterns = [
            r'%LET\s+\w+\s*=\s*[^;]+;',
            r'LIBNAME\s+\w+\s+[^;]+;',
        ]
        context_parts = []
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            context_parts.extend(matches)
        return '\n'.join(context_parts)
```

### 5.2 血缘追溯算法

```python
def trace_column_lineage(column: str, 
                         table: str, 
                         parsed_scripts: Dict) -> LineagePath:
    """
    追溯字段血缘路径
    
    递归算法：
    1. 在parsed_scripts中找到生成该表的脚本
    2. 查找该字段的映射关系
    3. 如果源表是原始输入，停止递归
    4. 如果源表是其他脚本的输出，递归追溯
    """
    script = find_script_by_output(table, parsed_scripts)
    mapping = find_column_mapping(column, script)
    
    path = LineagePath(
        target_table=table,
        target_column=column,
        source_mappings=[]
    )
    
    for src_table, src_col in zip(mapping.source_tables, mapping.source_columns):
        if is_original_source(src_table):
            path.source_mappings.append(SourceMapping(
                table=src_table,
                column=src_col,
                is_original=True
            ))
        else:
            # 递归追溯
            sub_path = trace_column_lineage(src_col, src_table, parsed_scripts)
            path.source_mappings.append(sub_path)
    
    return path
```

---

## 6. 配置设计

### 6.1 配置文件格式

```yaml
# config.yaml
llm:
  provider: openai  # openai, azure, anthropic, ollama
  model: gpt-4
  api_key: ${OPENAI_API_KEY}
  max_tokens: 4000
  temperature: 0.0

analysis:
  max_chunk_tokens: 3000
  chunk_overlap: 200
  use_llm_for_parsing: true
  parallel_parsing: true
  max_workers: 4

output:
  format: csv  # csv, json
  include_formula: true
  include_script_path: true
  delimiter: ","

paths:
  input_dir: "./input/sas"
  output_dir: "./output"
  cache_dir: "./cache"
```

### 6.2 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API密钥 | 使用OpenAI时必填 |
| `AZURE_OPENAI_KEY` | Azure OpenAI密钥 | 使用Azure时必填 |
| `LLM_PROVIDER` | LLM提供商 | 否，默认openai |
| `LOG_LEVEL` | 日志级别 | 否，默认INFO |

---

## 7. 使用示例

### 7.1 命令行使用

```bash
# 基本使用
python -m sas_lineage_analyzer --input ./input/sas --output ./output/lineage.csv

# 使用配置文件
python -m sas_lineage_analyzer --config ./config.yaml

# 指定LLM提供商
python -m sas_lineage_analyzer --input ./input/sas --llm-provider azure --llm-model gpt-4
```

### 7.2 编程接口

```python
from sas_lineage_analyzer import LineageAnalyzer, Config

# 配置
config = Config(
    llm_provider='openai',
    llm_model='gpt-4',
    max_chunk_tokens=3000
)

# 运行分析
analyzer = LineageAnalyzer(config)
result = analyzer.analyze('./input/sas')

# 获取结果
print(f"输出文件: {result.output_file}")
print(f"发现映射关系: {len(result.mappings)}条")
print(f"错误: {result.errors}")
```

---

## 8. 异常处理

### 8.1 错误类型

| 错误代码 | 描述 | 处理策略 |
|----------|------|----------|
| `PARSE_ERROR` | SAS代码解析失败 | 记录错误，跳过该文件，继续处理其他文件 |
| `LLM_TIMEOUT` | LLM调用超时 | 重试3次，失败后使用规则解析降级 |
| `TOKEN_LIMIT` | 超出Token限制 | 触发更细粒度的分块策略 |
| `CYCLE_DETECTED` | 检测到循环依赖 | 记录警告，中断该分支追溯 |
| `FILE_NOT_FOUND` | 引用的数据文件不存在 | 记录警告，使用定义文件替代 |

### 8.2 重试机制

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry_error_callback=lambda _: use_rule_based_fallback()
)
def llm_analyze_with_retry(chunk: str) -> Dict:
    """带重试的LLM分析"""
    return llm_client.analyze_sas_chunk(chunk)
```

---

## 9. 测试策略

### 9.1 单元测试

```python
# test_parser.py
def test_parse_data_step():
    code = """
    DATA output;
        SET input (RENAME=(old_col=new_col));
        derived = col1 + col2;
    RUN;
    """
    parser = SASParser(use_llm=False)
    result = parser.parse_transform_script(code)
    
    assert result['output_tables'][0]['table_name'] == 'output'
    assert len(result['output_tables'][0]['columns']) == 3

def test_parse_merge():
    code = """
    DATA merged;
        MERGE t1 t2;
        BY key;
        combined = t1.col + t2.col;
    RUN;
    """
    parser = SASParser(use_llm=False)
    result = parser.parse_transform_script(code)
    
    assert 't1' in result['output_tables'][0]['input_tables']
    assert 't2' in result['output_tables'][0]['input_tables']
```

### 9.2 集成测试

```python
# test_integration.py
def test_end_to_end():
    analyzer = LineageAnalyzer(Config(use_llm=False))
    result = analyzer.analyze('./test_data/sample_sas')
    
    assert result.output_file.exists()
    df = pd.read_csv(result.output_file)
    assert len(df) > 0
    assert 'output_table' in df.columns
    assert 'original_table' in df.columns
```

---

## 10. 性能考虑

### 10.1 优化策略

1. **并行处理**：多线程并行解析多个SAS文件
2. **缓存机制**：缓存LLM解析结果，避免重复调用
3. **增量分析**：只分析变更的文件
4. **流式导出**：大数据量时流式写入CSV

### 10.2 预估资源消耗

| 场景 | 文件数 | 预估Token数 | 预估时间 | 预估成本(USD) |
|------|--------|-------------|----------|---------------|
| 小规模 | 10个 | ~50K | ~2分钟 | ~$0.5 |
| 中规模 | 50个 | ~200K | ~8分钟 | ~$2.0 |
| 大规模 | 200个 | ~1M | ~30分钟 | ~$10.0 |

---

## 11. 目录结构

```
sas_lineage_analyzer/
├── __init__.py
├── cli.py                    # 命令行入口
├── config.py                 # 配置管理
├── core/
│   ├── __init__.py
│   ├── scanner.py            # FileScanner
│   ├── parser.py             # SASParser
│   ├── analyzer.py           # LineageAnalyzer
│   ├── llm_client.py         # LLMClient
│   └── exporter.py           # ExportManager
├── models/
│   ├── __init__.py
│   └── data_models.py        # Pydantic模型
├── workflow/
│   ├── __init__.py
│   └── graph.py              # LangGraph工作流
├── utils/
│   ├── __init__.py
│   ├── chunking.py           # 分块工具
│   └── helpers.py            # 通用工具
└── prompts/
    ├── __init__.py
    └── sas_analysis.py       # LLM提示词模板

tests/
├── unit/
│   ├── test_parser.py
│   ├── test_analyzer.py
│   └── test_chunking.py
├── integration/
│   └── test_workflow.py
└── fixtures/
    └── sample_sas/           # 测试用SAS文件

config/
└── config.yaml               # 默认配置
```

---

## 12. 修订记录

### 第1轮设计
- 初始版本，包含完整架构设计、数据模型、模块设计、工作流编排
