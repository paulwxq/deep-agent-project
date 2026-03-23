"""drafts 目录备份行为测试。

目标行为：
1. 运行前将 drafts 工作区内容备份到 ./drafts/_backups/drafts_时间戳
2. 清理时不触碰 _backups 目录下的历史内容
"""

from __future__ import annotations

from datetime import datetime as _dt
from pathlib import Path
from unittest.mock import MagicMock

import main as main_module


class TestBackupDraftsContents:
    def test_backups_workspace_into_drafts_backups(self, tmp_path: Path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "design.md").write_text("v1", encoding="utf-8")
        (drafts / "review-verdict.json").write_text("{}", encoding="utf-8")

        # 历史备份目录应被保留，不参与本次备份
        old_backup = drafts / "_backups" / "drafts_old"
        old_backup.mkdir(parents=True)
        (old_backup / "old.txt").write_text("old", encoding="utf-8")

        logger = MagicMock()
        backup_dir = main_module._backup_drafts_contents(drafts, logger)

        assert backup_dir is not None
        assert backup_dir.parent == drafts / "_backups"
        assert backup_dir.name.startswith("drafts_")

        # 工作区文件被移动到新备份目录
        assert not (drafts / "design.md").exists()
        assert (backup_dir / "design.md").read_text(encoding="utf-8") == "v1"
        assert (backup_dir / "review-verdict.json").exists()

        # 旧备份内容仍在
        assert (old_backup / "old.txt").read_text(encoding="utf-8") == "old"

    def test_no_backup_created_when_only_backups_exist(self, tmp_path: Path):
        drafts = tmp_path / "drafts"
        old_backup = drafts / "_backups" / "drafts_old"
        old_backup.mkdir(parents=True)
        (old_backup / "old.txt").write_text("old", encoding="utf-8")

        logger = MagicMock()
        backup_dir = main_module._backup_drafts_contents(drafts, logger)

        assert backup_dir is None
        # 仍只保留原有历史备份
        assert (old_backup / "old.txt").read_text(encoding="utf-8") == "old"
        assert len(list((drafts / "_backups").iterdir())) == 1

    def test_timestamp_collision_adds_suffix(self, tmp_path: Path, monkeypatch):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "design.md").write_text("v1", encoding="utf-8")

        fixed_ts = "20260323_120147"
        existing = drafts / "_backups" / f"drafts_{fixed_ts}"
        existing.mkdir(parents=True)

        class _FixedDatetime:
            @staticmethod
            def now():
                return _dt(2026, 3, 23, 12, 1, 47)

        monkeypatch.setattr(main_module, "datetime", _FixedDatetime)
        logger = MagicMock()

        backup_dir = main_module._backup_drafts_contents(drafts, logger)
        assert backup_dir is not None
        assert backup_dir.name == f"drafts_{fixed_ts}_1"
        assert (backup_dir / "design.md").exists()
