# Python CLI 计算器技术设计文档

## 1. 概述

开发一个简单的命令行界面(CLI)计算器，支持基本的四则运算（加、减、乘、除）。用户通过命令行参数提供两个数字和一个运算符，程序计算并输出结果。

## 2. 功能需求

- 支持四种基本运算：加法(+)、减法(-)、乘法(*)、除法(/)
- 接受三个命令行参数：第一个数字、运算符、第二个数字
- 输出计算结果到标准输出
- 处理除零错误并给出适当提示
- 验证输入参数的有效性

## 3. 技术方案

### 3.1 编程语言和依赖

- **语言**: Python 3.6+
- **标准库**: 
  - `sys` - 获取命令行参数
  - `argparse` - 命令行参数解析（推荐方案）

### 3.2 程序架构

采用简单的单文件脚本架构，包含以下组件：

1. **参数解析模块**: 使用 `argparse` 解析命令行参数
2. **计算引擎**: 实现四则运算的核心逻辑
3. **错误处理**: 处理无效输入和运行时错误
4. **主函数**: 程序入口点

### 3.3 详细设计

#### 3.3.1 参数解析

使用 `argparse.ArgumentParser` 定义三个位置参数：
- `num1`: 第一个操作数（浮点数类型）
- `operator`: 运算符（字符串类型，限制为 ['+', '-', '*', '/']）
- `num2`: 第二个操作数（浮点数类型）

#### 3.3.2 计算逻辑

实现 `calculate(num1, operator, num2)` 函数：
- 使用字典映射运算符到对应的 lambda 函数
- 支持的运算符: '+', '-', '*', '/'
- 除法运算需要检查除数是否为零

#### 3.3.3 错误处理

- **参数验证**: argparse 自动处理类型转换和参数数量验证
- **除零错误**: 捕获 ZeroDivisionError 并输出错误信息
- **无效运算符**: argparse 的 choices 参数限制确保运算符有效性

### 3.4 使用示例

```bash
# 加法
python calculator.py 5 + 3
# 输出: 8.0

# 除法
python calculator.py 10 / 2
# 输出: 5.0

# 除零错误
python calculator.py 5 / 0
# 输出: 错误: 除数不能为零
```

## 4. 实现细节

### 4.1 文件结构

- `calculator.py` - 主程序文件

### 4.2 核心代码结构

```python
import argparse
import sys

def calculate(num1, operator, num2):
    """执行四则运算"""
    operations = {
        '+': lambda x, y: x + y,
        '-': lambda x, y: x - y,
        '*': lambda x, y: x * y,
        '/': lambda x, y: x / y if y != 0 else None
    }
    
    if operator not in operations:
        raise ValueError(f"不支持的运算符: {operator}")
    
    if operator == '/' and num2 == 0:
        raise ZeroDivisionError("除数不能为零")
    
    return operations[operator](num1, num2)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='简单的CLI计算器')
    parser.add_argument('num1', type=float, help='第一个数字')
    parser.add_argument('operator', choices=['+', '-', '*', '/'], help='运算符')
    parser.add_argument('num2', type=float, help='第二个数字')
    
    args = parser.parse_args()
    
    try:
        result = calculate(args.num1, args.operator, args.num2)
        print(result)
    except ZeroDivisionError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

## 5. 测试用例

### 5.1 正常情况测试
- `5 + 3` → `8.0`
- `10 - 4` → `6.0`
- `7 * 6` → `42.0`
- `15 / 3` → `5.0`

### 5.2 异常情况测试
- `5 / 0` → 错误: 除数不能为零
- `5 % 3` → argparse 参数验证错误（无效运算符）
- `abc + 3` → argparse 参数验证错误（无效数字）
- 缺少参数 → argparse 显示帮助信息

## 6. 部署和使用

### 6.1 运行环境
- Python 3.6 或更高版本

### 6.2 执行方式
```bash
python calculator.py <num1> <operator> <num2>
```

### 6.3 退出码
- `0`: 成功执行
- `1`: 发生错误（如除零、无效输入等）