# SAS数据血缘分析系统技术设计文档

## 1. 概述

### 1.1 项目背景
本系统旨在分析SAS代码，自动提取数据血缘关系，生成源表字段到目标表字段的映射对照表。系统需要处理多种数据源类型（mainframe数据集、CSV、Excel）和中间临时文件（.sas7bdat），支持从输出表反向追踪到源字段。

### 1.2 设计目标
- **准确性**：正确识别字段间的映射关系，包括直接传递、重命名、衍生计算等
- **可扩展性**：支持大量SAS文件的处理，避免LLM上下文限制
- **灵活性**：支持多种LLM Provider配置，便于集成不同AI模型
- **完整性**：覆盖所有血缘关系类型，包括多源合并场景

## 2. 术语定义

- **Source/Origin**：输入数据源，包括mainframe数据集、CSV文件、Excel文件
- **Target/Output**：输出数据，限定为CSV文件
- **Intermediate**：中间临时文件，后缀为.sas7bdat
- **Passthrough**：字段直接传递，无任何变换
- **Rename**：字段重命名操作
- **Derived**：通过表达式计算得到的新字段
- **Multi-source**：字段来源于多个输入表的组合

## 3. 系统架构

### 3.1 整体架构
系统采用分层架构设计：
```
┌─────────────────┐
│     CLI/API     │
└────────┬────────┘
         │
┌────────▼────────┐
│  Configuration  │
└────────┬────────┘
         │
┌────────▼────────┐
│ SAS File Scanner│
└────────┬────────┘
         │
┌────────▼────────┐    ┌───────────────┐
│ SAS Code Parser ├────► LLM Provider │
└────────┬────────┘    └───────────────┘
         │
┌────────▼────────┐
│ Lineage Graph   │
└────────┬────────┘
         │
┌────────▼────────┐
│ CSV Exporter    │
└─────────────────┘
```

### 3.2 核心组件
- **SASFileScanner**：扫描指定目录下的SAS文件和数据文件
- **SASCodeParser**：解析SAS代码，提取关键信息（输入/输出表、字段操作）
- **LLMProvider**：调用LLM进行复杂血缘关系提取
- **LineageGraph**：构建和维护血缘关系图
- **CSVExporter**：导出标准格式的血缘对照表

## 4. 数据模型

### 4.1 核心实体

```python
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class DataSourceType(str, Enum):
    MAINFRAME = "mainframe"
    CSV = "csv" 
    EXCEL = "excel"
    SAS7BDAT = "sas7bdat"

class Field(BaseModel):
    name: str
    source_name: Optional[str] = None  # 原始字段名（用于重命名场景）
    data_type: Optional[str] = None
    is_derived: bool = False
    formula: Optional[str] = None  # 衍生字段的计算公式
    source_fields: List[str] = []  # 多源字段的源字段列表

class Table(BaseModel):
    name: str
    file_path: str
    source_type: DataSourceType
    fields: List[Field]
    is_intermediate: bool = False  # 是否为中间临时文件
    script_file: str  # 生成该表的SAS脚本文件

class LineageEdge(BaseModel):
    source_table: str
    source_field: str  
    target_table: str
    target_field: str
    operation_type: str  # "passthrough", "rename", "derived", "multi_source"
    formula: Optional[str] = None
    script_file: str
```

### 4.2 血缘关系输出格式
与参考文件`Output_sas_20260318.csv`保持一致：
- `output_table`: 目标表名
- `output_column`: 目标字段名  
- `original_table`: 源表名（多源时用分号分隔）
- `original_column`: 源字段名（多源时用分号分隔）
- `formula`: 计算公式或操作描述
- `script_file`: SAS脚本文件路径

## 5. 核心算法设计

### 5.1 SAS代码解析策略

#### 5.1.1 分块处理机制
由于SAS文件数量可能很多，无法一次性提交给LLM，采用分块处理策略：

```python
class SASChunkManager:
    def __init__(self, max_tokens_per_chunk: int = 3000):
        self.max_tokens_per_chunk = max_tokens_per_chunk
    
    def create_chunks(self, sas_files: List[str]) -> List[List[str]]:
        """将SAS文件分组，确保每组token数不超过限制"""
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for file_path in sas_files:
            file_tokens = self._estimate_tokens(file_path)
            if current_tokens + file_tokens > self.max_tokens_per_chunk:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_tokens = 0
            current_chunk.append(file_path)
            current_tokens += file_tokens
            
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks
```

#### 5.1.2 反向溯源算法
从目标表开始，递归查找所有源字段：

```python
import networkx as nx

class LineageGraph:
    def __init__(self):
        self.graph = nx.DiGraph()  # 有向图：源 -> 目标
    
    def add_edge(self, source_table: str, source_field: str, 
                 target_table: str, target_field: str, 
                 operation_type: str, formula: str = None):
        """添加血缘关系边"""
        edge_data = {
            'operation_type': operation_type,
            'formula': formula
        }
        self.graph.add_edge(
            f"{source_table}.{source_field}", 
            f"{target_table}.{target_field}",
            **edge_data
        )
    
    def trace_backward(self, target_table: str, target_field: str) -> List[Dict]:
        """反向溯源，找到所有源字段路径"""
        target_node = f"{target_table}.{target_field}"
        if target_node not in self.graph:
            return []
            
        source_paths = []
        for source_node in self.graph.predecessors(target_node):
            paths = list(nx.all_simple_paths(self.graph, source_node, target_node))
            for path in paths:
                source_paths.append({
                    'source_table': path[0].split('.')[0],
                    'source_field': path[0].split('.')[1],
                    'target_table': target_table,
                    'target_field': target_field,
                    'path': path
                })
                
        return source_paths
```

### 5.2 LLM提示工程

#### 5.2.1 血缘提取Prompt模板
```python
LINEAGE_EXTRACTION_PROMPT = """
你是一个SAS代码专家，请分析以下SAS代码，提取数据血缘关系。

SAS代码内容：
{code_content}

请按照以下JSON格式返回结果：
{
  "tables": [
    {
      "name": "表名",
      "file_path": "文件路径", 
      "source_type": "mainframe|csv|excel|sas7bdat",
      "is_intermediate": true|false,
      "fields": [
        {
          "name": "字段名",
          "source_name": "原始字段名（如果重命名）",
          "is_derived": true|false,
          "formula": "计算公式（如果是衍生字段）",
          "source_fields": ["源字段1", "源字段2"]  // 多源字段
        }
      ]
    }
  ],
  "lineage_edges": [
    {
      "source_table": "源表名",
      "source_field": "源字段名", 
      "target_table": "目标表名",
      "target_field": "目标字段名",
      "operation_type": "passthrough|rename|derived|multi_source",
      "formula": "公式或操作描述"
    }
  ]
}

注意事项：
1. 输出表都是CSV格式
2. 源数据可能是mainframe定义、CSV或Excel
3. 中间文件是.sas7bdat格式
4. 准确识别字段重命名和衍生计算
5. 处理多源合并场景（如MERGE操作）
"""
```

## 6. 技术栈实现

### 6.1 LLM Provider抽象层与LangChain集成

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

# 血缘提取结果的Pydantic模型（用于LangChain结构化输出）
class LineageExtractionResult(BaseModel):
    tables: List[Dict]  # 与之前定义的Table模型对应
    lineage_edges: List[Dict]  # 与之前定义的LineageEdge模型对应

class LLMProvider(ABC):
    @abstractmethod
    def extract_lineage(self, code_content: str) -> LineageExtractionResult:
        pass

class LangChainOpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4-turbo", temperature: float = 0.1):
        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=2000
        )
        self.output_parser = PydanticOutputParser(pydantic_object=LineageExtractionResult)
        
        # 使用LangChain的ChatPromptTemplate
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个SAS代码专家，请分析以下SAS代码，提取数据血缘关系。"),
            ("human", "SAS代码内容：\n{code_content}\n\n请按照以下JSON格式返回结果：\n{format_instructions}")
        ])
        
        # 构建LangChain处理链
        self.chain = self.prompt | self.llm | self.output_parser
    
    def extract_lineage(self, code_content: str) -> LineageExtractionResult:
        try:
            result = self.chain.invoke({
                "code_content": code_content,
                "format_instructions": self.output_parser.get_format_instructions()
            })
            return result
        except Exception as e:
            raise LLMExtractionError(f"OpenAI LLM extraction failed: {str(e)}")

class LangChainAnthropicProvider(LLMProvider):
    def __ __init__(self, api_key: str, model: str = "claude-3-opus-20240229", temperature: float = 0.1):
        self.llm = ChatAnthropic(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=2000
        )
        self.output_parser = PydanticOutputParser(pydantic_object=LineageExtractionResult)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个SAS代码专家，请分析以下SAS代码，提取数据血缘关系。"),
            ("human", "SAS代码内容：\n{code_content}\n\n请按照以下JSON格式返回结果：\n{format_instructions}")
        ])
        
        self.chain = self.prompt | self.llm | self.output_parser
    
    def extract_lineage(self, code_content: str) -> LineageExtractionResult:
        try:
            result = self.chain.invoke({
                "code_content": code_content,
                "format_instructions": self.output_parser.get_format_instructions()
            })
            return result
        except Exception as e:
            raise LLMExtractionError(f"Anthropic LLM extraction failed: {str(e)}")

class LLMProviderFactory:
    @staticmethod
    def create_provider(provider_type: str, **kwargs) -> LLMProvider:
        if provider_type == "openai":
            return LangChainOpenAIProvider(**kwargs)
        elif provider_type == "anthropic":
            return LangChainAnthropicProvider(**kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider_type}")
```

### 6.2 主处理流程

```python
class SASLineageAnalyzer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.llm_provider = LLMProviderFactory.create_provider(
            config['llm']['provider'], 
            **config['llm']['settings']
        )
        self.lineage_graph = LineageGraph()
        self.chunk_manager = SASChunkManager(config['processing']['max_tokens_per_chunk'])
        self.table_registry = {}  # 注册所有表的信息：表名 -> Table对象
    
    def analyze_directory(self, sas_directory: str) -> List[Dict]:
        """分析整个SAS目录"""
        # 1. 扫描所有SAS文件
        sas_files = self._scan_sas_files(sas_directory)
        
        # 2. 分块处理
        chunks = self.chunk_manager.create_chunks(sas_files)
        
        # 3. 并行处理每个块
        all_results = []
        for chunk in chunks:
            chunk_result = self._process_chunk(chunk)
            all_results.extend(chunk_result)
            self._update_lineage_graph(chunk_result)
            
        # 4. 处理中间文件关联
        self._link_intermediate_files()
        
        # 5. 处理Mainframe数据集定义文件
        definition_files = self._find_definition_files(sas_directory)
        for def_file in definition_files:
            self._parse_definition_file(def_file)
            
        return all_results
    
    def _process_chunk(self, sas_files: List[str]) -> List[Dict]:
        """处理单个SAS文件块"""
        results = []
        for file_path in sas_files:
            with open(file_path, 'r') as f:
                code_content = f.read()
            
            # 调用LLM提取血缘关系
            lineage_result = self.llm_provider.extract_lineage(
                code_content, 
                LINEAGE_EXTRACTION_PROMPT
            )
            
            # 添加脚本文件信息并注册表
            for table_data in lineage_result.get('tables', []):
                table_data['script_file'] = file_path
                table = Table(**table_data)
                self.table_registry[table.name] = table
                
            results.append(lineage_result)
            
        return results
    
    def _link_intermediate_files(self):
        """关联中间临时文件
        
        匹配规则：
        1. 完全匹配表名（不区分大小写）
        2. 检查是否有其他SAS脚本将此表作为输入
        3. 如果表被其他脚本引用且不是最终CSV输出，则标记为中间文件
        
        实现步骤：
        - 遍历所有表，检查是否在其他脚本的输入表列表中
        - 如果是，且该表的source_type不是CSV，则标记为is_intermediate=True
        - 更新血缘图中的关联关系
        """
        # 构建输入表引用映射
        input_table_references = {}
        for table_name, table in self.table_registry.items():
            if hasattr(table, 'input_tables'):  # 假设LLM提取结果包含input_tables
                for input_table in table.input_tables:
                    if input_table not in input_table_references:
                        input_table_references[input_table] = []
                    input_table_references[input_table].append(table_name)
        
        # 标记中间文件
        for table_name, table in self.table_registry.items():
            # 如果表被其他表引用，且不是CSV输出，则为中间文件
            if (table_name in input_table_references and 
                table.source_type != DataSourceType.CSV):
                table.is_intermediate = True
                # 更新血缘图：添加从中间文件到引用表的边
                for referencing_table in input_table_references[table_name]:
                    ref_table = self.table_registry[referencing_table]
                    for field in table.fields:
                        if field.name in [f.name for f in ref_table.fields]:
                            self.lineage_graph.add_edge(
                                table_name, field.name,
                                referencing_table, field.name,
                                "passthrough",
                                script_file=ref_table.script_file
                            )
    
    def _parse_definition_file(self, def_file_path: str):
        """解析Mainframe数据集定义文件
        
        解析def_Churn.sas、def_train.sas等文件中的字段定义格式：
        - infile语句：获取物理文件路径
        - input语句：提取字段位置、名称、格式
        
        字段格式说明：
        - PK2.0: Packed decimal format
        - S370FPD6.0: IBM System/370 floating point decimal
        - $EBCDIC3.: EBCDIC character format
        
        解析步骤：
        1. 提取infile语句中的文件路径
        2. 解析input语句中的字段定义
        3. 创建Table对象并注册到table_registry
        """
        with open(def_file_path, 'r') as f:
            content = f.read()
        
        # 提取infile语句
        import re
        infile_match = re.search(r'infile\s+"([^"]+)"', content, re.IGNORECASE)
        if not infile_match:
            # 尝试提取infile语句中的变量引用
            infile_match = re.search(r'infile\s+(&\w+)', content, re.IGNORECASE)
            if infile_match:
                # 需要解析宏变量，这里简化处理
                file_path = f"mainframe_dataset_{infile_match.group(1)}"
            else:
                file_path = def_file_path.replace('.sas', '_raw')
        else:
            file_path = infile_match.group(1)
        
        # 解析input语句中的字段定义
        fields = []
        input_section_match = re.search(r'input\s+(.+?);', content, re.DOTALL | re.IGNORECASE)
        if input_section_match:
            input_lines = input_section_match.group(1).strip().split('\n')
            for line in input_lines:
                line = line.strip()
                if not line or line.startswith('*'):
                    continue
                
                # 解析字段定义：@位置 字段名 格式
                field_match = re.match(r'@(\d+)\s+([\'"\w]+)\s+(\S+)', line)
                if field_match:
                    position = int(field_match.group(1))
                    field_name = field_match.group(2).strip("'\"")
                    field_format = field_match.group(3)
                    
                    # 确定数据类型
                    if field_format.startswith('$'):
                        data_type = 'CHAR'
                    elif 'PK' in field_format or 'FPD' in field_format:
                        data_type = 'NUMERIC'
                    else:
                        data_type = 'UNKNOWN'
                    
                    fields.append(Field(
                        name=field_name,
                        data_type=data_type,
                        source_name=None,
                        is_derived=False,
                        formula=None,
                        source_fields=[]
                    ))
        
        # 从文件名推断表名（如def_Churn.sas -> churn_raw）
        table_name_match = re.search(r'data\s+&lib\.\.?\s*(\w+)', content, re.IGNORECASE)
        if table_name_match:
            table_name = table_name_match.group(1)
        else:
            # 从文件名推断
            table_name = def_file_path.split('/')[-1].replace('def_', '').replace('.sas', '') + '_raw'
        
        # 创建Mainframe数据集表
        mainframe_table = Table(
            name=table_name,
            file_path=file_path,
            source_type=DataSourceType.MAINFRAME,
            fields=fields,
            is_intermediate=False,
            script_file=def_file_path
        )
        
        self.table_registry[table_name] = mainframe_table
```

## 7. 配置管理

### 7.1 配置文件结构
```yaml
# config.yaml
llm:
  provider: "openai"
  settings:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4-turbo"
    temperature: 0.1
    max_tokens: 2000

processing:
  max_tokens_per_chunk: 3000
  parallel_workers: 4
  timeout_seconds: 300

output:
  format: "csv"
  include_formula: true
  include_script_path: true

logging:
  level: "INFO"
  file: "logs/lineage_analysis.log"
```

### 7.2 配置加载
```python
import os
from typing import Dict, Any
import yaml

class Settings:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        else:
            config = {}
        
        # 替换环境变量
        self._resolve_env_vars(config)
        return config
    
    def _resolve_env_vars(self, config: Dict[str, Any]):
        """递归替换配置中的环境变量"""
        for key, value in config.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                config[key] = os.getenv(env_var, "")
            elif isinstance(value, dict):
                self._resolve_env_vars(value)
```

## 8. 错误处理与容错机制

### 8.1 异常类型定义
```python
class LineageAnalysisError(Exception):
    """血缘分析基础异常"""
    pass

class SASParseError(LineageAnalysisError):
    """SAS代码解析错误"""
    pass

class LLMExtractionError(LineageAnalysisError):
    """LLM提取血缘关系失败"""
    pass

class GraphConstructionError(LineageAnalysisError):
    """血缘图构建错误"""
    pass

class OutputGenerationError(LineageAnalysisError):
    """输出文件生成错误"""
    pass
```

### 8.2 降级处理策略
- **LLM失败降级**：当LLM提取失败时，使用规则-based解析器作为备选
- **部分失败容忍**：单个文件处理失败不影响整体分析
- **重试机制**：对LLM调用实施指数退避重试

```python
import re
from typing import List, Dict, Any

class FallbackParser:
    """规则-based降级解析器"""
    
    def extract_simple_lineage(self, code_content: str) -> Dict[str, Any]:
        """使用正则表达式等简单规则提取基本血缘关系"""
        tables = []
        lineage_edges = []
        
        # 提取DATA语句中的输出表名
        data_tables = self._extract_data_tables(code_content)
        
        # 提取SET/MERGE语句中的输入表名
        input_tables = self._extract_input_tables(code_content)
        
        # 提取KEEP语句中的字段列表
        kept_fields = self._extract_kept_fields(code_content)
        
        # 提取RENAME选项中的重命名映射
        rename_mappings = self._extract_rename_mappings(code_content)
        
        # 构建表信息
        for table_name in data_tables:
            fields = []
            # 添加保留的字段
            for field_name in kept_fields:
                if field_name in rename_mappings:
                    # 重命名字段
                    original_name = rename_mappings[field_name]
                    fields.append({
                        "name": field_name,
                        "source_name": original_name,
                        "is_derived": False,
                        "formula": f"rename {original_name} -> {field_name}",
                        "source_fields": [original_name]
                    })
                    # 添加血缘边
                    for input_table in input_tables:
                        lineage_edges.append({
                            "source_table": input_table,
                            "source_field": original_name,
                            "target_table": table_name,
                            "target_field": field_name,
                            "operation_type": "rename",
                            "formula": f"rename {original_name} -> {field_name}"
                        })
                else:
                    # 直接传递字段
                    fields.append({
                        "name": field_name,
                        "source_name": None,
                        "is_derived": False,
                        "formula": "passthrough",
                        "source_fields": [field_name]
                    })
                    # 添加血缘边
                    for input_table in input_tables:
                        lineage_edges.append({
                            "source_table": input_table,
                            "source_field": field_name,
                            "target_table": table_name,
                            "target_field": field_name,
                            "operation_type": "passthrough",
                            "formula": "passthrough"
                        })
            
            tables.append({
                "name": table_name,
                "file_path": f"{table_name}.csv",  # 假设输出为CSV
                "source_type": "csv",
                "is_intermediate": len(input_tables) > 0 and table_name not in [t.split('/')[-1].replace('.csv', '') for t in data_tables],
                "fields": fields
            })
        
        return {
            "tables": tables,
            "lineage_edges": lineage_edges
        }
    
    def _extract_data_tables(self, code_content: str) -> List[str]:
        """提取DATA语句中的表名"""
        data_matches = re.findall(r'DATA\s+([^\s;]+)', code_content, re.IGNORECASE)
        return [match.strip() for match in data_matches if match.strip()]
    
    def _extract_input_tables(self, code_content: str) -> List[str]:
        """提取SET和MERGE语句中的输入表名"""
        input_tables = []
        
        # 提取SET语句
        set_matches = re.findall(r'SET\s+([^\s;]+)', code_content, re.IGNORECASE)
        input_tables.extend([match.strip() for match in set_matches if match.strip()])
        
        # 提取MERGE语句
        merge_matches = re.findall(r'MERGE\s+([^;]+)', code_content, re.IGNORECASE)
        for match in merge_matches:
            tables = [t.strip() for t in match.split() if t.strip()]
            input_tables.extend(tables)
        
        return list(set(input_tables))  # 去重
    
    def _extract_kept_fields(self, code_content: str) -> List[str]:
        """提取KEEP语句中的字段列表"""
        keep_matches = re.findall(r'KEEP\s+([^;]+)', code_content, re.IGNORECASE)
        kept_fields = []
        for match in keep_matches:
            fields = [f.strip() for f in match.split() if f.strip()]
            kept_fields.extend(fields)
        return list(set(kept_fields))
    
    def _extract_rename_mappings(self, code_content: str) -> Dict[str, str]:
        """提取RENAME选项中的重命名映射"""
        rename_mappings = {}
        
        # 提取RENAME=(old=new)格式
        rename_matches = re.findall(r'RENAME\s*=\s*\(([^)]+)\)', code_content, re.IGNORECASE)
        for match in rename_matches:
            pairs = [p.strip() for p in match.split(',')]
            for pair in pairs:
                if '=' in pair:
                    old_name, new_name = pair.split('=', 1)
                    rename_mappings[new_name.strip()] = old_name.strip()
        
        return rename_mappings
```

## 9. API与CLI接口设计

### 9.1 Python API
```python
# 初始化分析器
analyzer = SASLineageAnalyzer(config=settings.config)

# 分析单个目录
results = analyzer.analyze_directory("/path/to/sas/files")

# 导出血缘关系
analyzer.export_lineage_csv("output/lineage.csv")

# 查询特定字段的血缘
lineage_paths = analyzer.trace_field_lineage("merged_out", "risk_score")

# 在SASLineageAnalyzer类中添加以下方法：
def trace_field_lineage(self, target_table: str, target_field: str) -> List[Dict]:
    """查询特定字段的完整血缘路径"""
    return self.lineage_graph.trace_backward(target_table, target_field)

def export_lineage_csv(self, output_file: str):
    """导出标准格式的血缘对照表"""
    import csv
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['output_table', 'output_column', 'original_table', 'original_column', 'formula', 'script_file'])
        
        # 遍历血缘图中的所有边
        for edge in self.lineage_graph.graph.edges(data=True):
            source_node, target_node, edge_data = edge
            source_table, source_field = source_node.split('.', 1)
            target_table, target_field = target_node.split('.', 1)
            
            # 处理多源情况（需要从图中收集所有源）
            original_tables = [source_table]
            original_columns = [source_field]
            
            # 检查是否有其他源（多源合并场景）
            predecessors = list(self.lineage_graph.graph.predecessors(target_node))
            if len(predecessors) > 1:
                original_tables = [p.split('.')[0] for p in predecessors]
                original_columns = [p.split('.')[1] for p in predecessors]
            
            writer.writerow([
                target_table,
                target_field,
                '; '.join(original_tables),
                '; '.join(original_columns),
                edge_data.get('formula', edge_data.get('operation_type', '')),
                edge_data.get('script_file', '')
            ])
```

### 9.2 CLI接口
```bash
# 基本用法
python -m sas_lineage_analyzer --input-dir /path/to/sas --output-file lineage.csv

# 指定配置文件
python -m sas_lineage_analyzer --config config.yaml --input-dir /path/to/sas

# 详细参数
python -m sas_lineage_analyzer \
  --input-dir /path/to/sas \
  --output-file lineage.csv \
  --llm-provider openai \
  --max-workers 4 \
  --verbose
```

## 10. 测试策略

### 10.1 单元测试覆盖
- SAS代码解析器单元测试
- LLM Provider模拟测试
- 血缘图构建和查询测试
- CSV导出格式验证

### 10.2 集成测试场景
- 单源单表场景（01_churn_transform.sas）
- 单源多表场景（02_loan_transform.sas）  
- 多源合并场景（03_merge_transform.sas）
- Mainframe定义文件解析（def_Churn.sas, def_train.sas）

## 11. 性能考虑

### 11.1 内存优化
- 流式处理大文件，避免全量加载
- 图数据结构使用高效存储格式
- 结果分批写入，避免内存累积

### 11.2 并行处理
- SAS文件块并行处理
- I/O操作异步化
- LLM调用连接池管理

## 12. 部署要求

### 12.1 环境依赖
- Python 3.12+
- langchain-core >= 0.1.0
- networkx >= 3.0
- pydantic >= 2.0
- pandas >= 2.0 (用于CSV处理)

### 12.2 硬件要求
- 内存：至少8GB（处理大型SAS项目建议16GB+）
- 存储：足够的磁盘空间存储SAS文件和输出结果
- 网络：稳定的网络连接（用于LLM API调用）

## 13. 扩展性设计

### 13.1 新增LLM Provider
通过继承`LLMProvider`抽象类，实现新的Provider即可支持其他AI模型。

### 13.2 新增数据源类型
扩展`DataSourceType`枚举，并在解析逻辑中添加相应处理。

### 13.3 自定义输出格式
实现新的Exporter类，支持JSON、数据库等其他输出格式。