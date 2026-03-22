"""pytest 全局配置。

通过 pyproject.toml 的 pythonpath=["."] 已将项目根加入 sys.path，
此处提供共享 fixture。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """返回项目根目录的绝对路径，供需要读取项目文件的测试使用。"""
    return Path(__file__).parent.parent
