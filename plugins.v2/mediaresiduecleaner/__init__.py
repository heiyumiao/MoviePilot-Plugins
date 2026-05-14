import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app import schemas
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase


class MediaResidueCleaner(_PluginBase):
    plugin_name = "媒体残留清理"
    plugin_desc = "按源目录和媒体库目录核对硬链接，辅助清理整理后的下载残留。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "0.2.5"
    plugin_author = "heiyu"
    author_url = "https://github.com/heiyumiao/MoviePilot-Plugins"
    plugin_config_prefix = "mediaresiduecleaner_"
    plugin_order = 88
    auth_level = 1

    _enabled = False
    _scan_on_open = True
    _scan_history = True
    _include_torrents = True
    _sync_downloader_tasks = False
    _downloader_action = "pause"
    _sync_related_seeds = True
    _source_roots = ""
    _target_roots = ""
    _db_path = ""
    _torrent_dirs = ""
    _allowed_roots = ""
    _max_items = 200
    _last_error = ""

    _default_allowed_roots = "/volume1,/volume2,/downloads,/media,/config"
    _default_torrent_dirs = "/config/temp,/volume1/@appdata/MoviePilot/config/temp"

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._scan_on_open = bool(config.get("scan_on_open", True))
        self._scan_history = bool(config.get("scan_history", True))
        self._include_torrents = bool(config.get("include_torrents", True))
        self._sync_downloader_tasks = bool(config.get("sync_downloader_tasks", False))
        self._downloader_action = self._clean_text(config.get("downloader_action")) or "pause"
        if self._downloader_action not in {"pause", "delete"}:
            self._downloader_action = "pause"
        self._sync_related_seeds = bool(config.get("sync_related_seeds", True))
        self._source_roots = self._clean_text(config.get("source_roots"))
        self._target_roots = self._clean_text(config.get("target_roots"))
        self._db_path = self._clean_text(config.get("db_path"))
        self._torrent_dirs = self._clean_text(config.get("torrent_dirs")) or self._default_torrent_dirs
        self._allowed_roots = self._clean_text(config.get("allowed_roots")) or self._source_roots or self._default_allowed_roots
        self._max_items = self._safe_int(config.get("max_items"), 200, minimum=20, maximum=1000)
        self._last_error = ""

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/scan",
                "endpoint": self.api_scan,
                "methods": ["GET", "POST"],
                "summary": "扫描媒体残留",
            },
            {
                "path": "/delete_file",
                "endpoint": self.api_delete_file,
                "methods": ["GET", "POST"],
                "summary": "删除扫描结果中的文件",
            },
            {
                "path": "/delete_torrent",
                "endpoint": self.api_delete_torrent,
                "methods": ["GET", "POST"],
                "summary": "删除扫描结果中的种子缓存",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "scan_on_open",
                                            "label": "打开详情页时扫描",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "scan_history",
                                            "label": "扫描历史记录",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "include_torrents",
                                            "label": "扫描种子缓存",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "sync_downloader_tasks",
                                            "label": "联动处理下载任务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "sync_related_seeds",
                                            "label": "处理辅种记录",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "downloader_action",
                                            "label": "下载任务动作",
                                            "items": [
                                                {"title": "暂停任务", "value": "pause"},
                                                {"title": "删除任务（不删除下载器文件）", "value": "delete"},
                                            ],
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "source_roots",
                                            "label": "源文件夹，逗号或换行分隔",
                                            "placeholder": "/volume1/downloads\n/volume2/downloads",
                                            "rows": 3,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "target_roots",
                                            "label": "目标/媒体库文件夹，逗号或换行分隔",
                                            "placeholder": "/volume1/video\n/volume2/video",
                                            "rows": 3,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "db_path",
                                            "label": "MoviePilot user.db 路径",
                                            "placeholder": "留空自动探测",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_items",
                                            "label": "详情页最多显示条数",
                                            "placeholder": "200",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "allowed_roots",
                                            "label": "允许删除的根目录，逗号或换行分隔",
                                            "rows": 2,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "torrent_dirs",
                                            "label": "种子缓存目录，逗号或换行分隔",
                                            "rows": 2,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "默认安装后不启用。建议先填好源文件夹和目标媒体库文件夹，再打开插件或手动扫描；删除前会校验路径、大小和 inode。联动处理下载任务会影响下载器里的做种任务，请确认后再开启。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "scan_on_open": True,
            "scan_history": True,
            "include_torrents": True,
            "sync_downloader_tasks": False,
            "downloader_action": "pause",
            "sync_related_seeds": True,
            "source_roots": "",
            "target_roots": "",
            "db_path": "",
            "torrent_dirs": self._default_torrent_dirs,
            "allowed_roots": self._default_allowed_roots,
            "max_items": 200,
        }

    def get_page(self) -> List[dict]:
        report = self.get_data("last_scan") or {}
        if self._enabled and self._scan_on_open:
            report = self._scan_and_save()

        items = report.get("items") or []
        summary = report.get("summary") or {}
        generated_at = report.get("generated_at") or "-"
        error = report.get("error") or self._last_error
        deletable_items = int(summary.get("deletable_items") or 0)
        total_items = int(summary.get("total_items") or 0)
        deletable_bytes = int(summary.get("deletable_bytes") or 0)

        contents: List[dict] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "warning" if deletable_items else "success",
                    "variant": "tonal",
                    "text": (
                        f"扫描时间：{generated_at}；发现 {total_items} 条记录，"
                        f"可释放候选 {deletable_items} 条，约 {self._format_size(deletable_bytes)}。"
                    ),
                },
            },
            {
                "component": "div",
                "props": {"class": "d-flex flex-wrap ga-2 my-2"},
                "content": [
                    {
                        "component": "VChip",
                        "props": {"color": "error", "variant": "tonal"},
                        "text": f"可释放 {deletable_items} 条",
                    },
                    {
                        "component": "VChip",
                        "props": {"color": "warning", "variant": "tonal"},
                        "text": f"预计 {self._format_size(deletable_bytes)}",
                    },
                    {
                        "component": "VChip",
                        "props": {"variant": "outlined"},
                        "text": f"总记录 {total_items} 条",
                    },
                ],
            },
            {
                "component": "VBtn",
                "props": {
                    "prepend-icon": "mdi-refresh",
                    "variant": "tonal",
                    "class": "my-2",
                },
                "text": "重新扫描",
                "events": {
                    "click": {
                        "api": f"plugin/{self.__class__.__name__}/scan?apikey={settings.API_TOKEN}",
                        "method": "get",
                    }
                },
            },
        ]

        if error:
            contents.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "error",
                        "variant": "tonal",
                        "text": f"扫描错误：{error}",
                    },
                }
            )

        if not items:
            contents.append(
                {
                    "component": "div",
                    "props": {"class": "text-center pa-4"},
                    "text": "暂无扫描结果",
                }
            )
            return contents

        candidate_items = [item for item in items if item.get("deletable")]
        reference_items = [item for item in items if not item.get("deletable")]
        contents.append(
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "class": "my-2",
                    "text": "硬链接只按设备号和 inode 判断。目标存在但当前源文件 inode 不同，会作为额外副本计入可释放候选；源文件和目标 inode 相同则只作为参考记录展示。",
                },
            }
        )

        result_cards = []
        ordered_items = (candidate_items + reference_items)[: self._max_items]
        current_group = ""
        for item in ordered_items:
            group = "可释放候选" if item.get("deletable") else "参考记录"
            if group != current_group:
                current_group = group
                result_cards.append(
                    {
                        "component": "div",
                        "props": {"class": "text-subtitle-2 font-weight-bold mt-4 mb-2"},
                        "text": group,
                    }
                )
            api_path = "delete_torrent" if item.get("kind") == "torrent" else "delete_file"
            status_color = self._status_color(item.get("status"), bool(item.get("deletable")))
            card_content = [
                {
                    "component": "VCardText",
                    "props": {"class": "pb-2"},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "d-flex flex-wrap align-center ga-2 mb-2"},
                            "content": [
                                {
                                    "component": "VChip",
                                    "props": {
                                        "color": status_color,
                                        "variant": "tonal",
                                        "size": "small",
                                    },
                                    "text": item.get("status_text"),
                                },
                                {
                                    "component": "VChip",
                                    "props": {"variant": "outlined", "size": "small"},
                                    "text": item.get("size_text"),
                                },
                                {
                                    "component": "VChip",
                                    "props": {"variant": "outlined", "size": "small"},
                                    "text": f"硬链接 {item.get('nlink') or '-'}",
                                },
                                {
                                    "component": "VChip",
                                    "props": {"variant": "outlined", "size": "small"},
                                    "text": item.get("source") or "-",
                                },
                            ],
                        },
                        {
                            "component": "div",
                            "props": {"class": "font-weight-medium mb-1"},
                            "text": item.get("display_title") or "-",
                        },
                        {
                            "component": "div",
                            "props": {"class": "text-caption text-medium-emphasis"},
                            "text": f"源文件：{item.get('path')}",
                        },
                    ],
                }
            ]
            if item.get("target_path"):
                card_content[0]["content"].append(
                    {
                        "component": "div",
                        "props": {"class": "text-caption text-medium-emphasis mt-1"},
                        "text": f"目标：{item.get('target_path')}",
                    }
                )
            if item.get("deletable"):
                card_content.append(
                    {
                        "component": "VCardActions",
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "prepend-icon": "mdi-delete",
                                    "color": "error",
                                    "variant": "tonal",
                                },
                                "text": "删除此文件",
                                "events": {
                                    "click": {
                                        "api": f"plugin/{self.__class__.__name__}/{api_path}?apikey={settings.API_TOKEN}",
                                        "method": "post",
                                        "params": {"item_id": item.get("id")},
                                    }
                                },
                            }
                        ],
                    }
                )
            card_props = {"variant": "tonal", "class": "my-2"}
            if item.get("deletable"):
                card_props["color"] = "error"
            result_cards.append(
                {
                    "component": "VCard",
                    "props": card_props,
                    "content": card_content,
                }
            )
        contents.append({"component": "div", "content": result_cards})

        if len(items) > self._max_items:
            contents.append(
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis mt-2"},
                    "text": f"仅显示前 {self._max_items} 条结果，可在插件配置里调整显示数量。",
                }
            )

        return contents

    def api_scan(self, apikey: str = ""):
        if apikey and apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        report = self._scan_and_save()
        if report.get("error"):
            return schemas.Response(success=False, message=report["error"], data=report)
        return schemas.Response(success=True, message="扫描完成", data=report)

    def api_delete_file(self, item_id: str, apikey: str = ""):
        return self._delete_item(item_id=item_id, apikey=apikey, expected_kind="file")

    def api_delete_torrent(self, item_id: str, apikey: str = ""):
        return self._delete_item(item_id=item_id, apikey=apikey, expected_kind="torrent")

    def stop_service(self):
        pass

    def _scan_and_save(self) -> Dict[str, Any]:
        try:
            report = self._scan()
            self.save_data("last_scan", report)
            self._last_error = ""
            return report
        except Exception as exc:
            logger.error(f"媒体残留扫描失败：{exc}")
            self._last_error = str(exc)
            report = {
                "generated_at": self._now_text(),
                "items": [],
                "summary": {"total_items": 0, "deletable_bytes": 0},
                "error": str(exc),
            }
            self.save_data("last_scan", report)
            return report

    def _scan(self) -> Dict[str, Any]:
        self._last_error = ""
        db_path = self._resolve_db_path()
        items: List[Dict[str, Any]] = []
        transfer_protections = self._build_transfer_protections(db_path) if self._scan_history and db_path else {}
        if self._source_roots and self._target_roots:
            items.extend(self._scan_source_roots(transfer_protections))

        if self._scan_history and db_path:
            items.extend(self._scan_history_db(db_path))
        elif self._scan_history:
            self._last_error = "未找到 MoviePilot user.db，请在插件配置中填写路径"

        if self._include_torrents:
            items.extend(self._scan_torrents())

        deduped = self._dedupe_items(items)
        deduped.sort(key=lambda item: (item.get("deletable", False), item.get("size", 0)), reverse=True)
        deletable_bytes = sum(int(item.get("size") or 0) for item in deduped if item.get("deletable"))
        return {
            "generated_at": self._now_text(),
            "db_path": db_path,
            "items": deduped,
            "summary": {
                "total_items": len(deduped),
                "deletable_items": sum(1 for item in deduped if item.get("deletable")),
                "deletable_bytes": deletable_bytes,
            },
            "error": self._last_error,
        }

    def _scan_source_roots(self, transfer_protections: Dict[Tuple[str, int], Dict[str, str]]) -> List[Dict[str, Any]]:
        source_roots = self._split_paths(self._source_roots)
        target_roots = self._split_paths(self._target_roots)
        target_index = self._build_target_inode_index(target_roots)
        items: List[Dict[str, Any]] = []

        for root in source_roots:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not self._is_under_any(os.path.join(dirpath, name), target_roots)
                ]
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    if self._is_under_any(path, target_roots):
                        continue
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    target_path = target_index.get(self._stat_key(stat))
                    if target_path:
                        status = "source_and_target_exist"
                    elif (name, int(stat.st_size)) in transfer_protections:
                        protected = transfer_protections[(name, int(stat.st_size))]
                        target_path = protected.get("target_path")
                        status = "target_exists_but_source_not_linked"
                    else:
                        status = "source_without_target"
                    item = self._build_file_item(
                        path=path,
                        source="source_roots",
                        title=transfer_protections.get((name, int(stat.st_size)), {}).get("title") or name,
                        row={},
                        status=status,
                        target_path=target_path or "",
                    )
                    if item:
                        items.append(item)
        return items

    def _build_target_inode_index(self, roots: List[str]) -> Dict[Tuple[int, int], str]:
        index: Dict[Tuple[int, int], str] = {}
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    index.setdefault(self._stat_key(stat), path)
        return index

    def _build_transfer_protections(self, db_path: str) -> Dict[Tuple[str, int], Dict[str, str]]:
        protections: Dict[Tuple[str, int], Dict[str, str]] = {}
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
        except sqlite3.Error:
            return protections
        try:
            if "transferhistory" not in set(self._sqlite_tables(con)):
                return protections
            for row in self._fetch_rows(con, "transferhistory"):
                data = dict(row)
                title = self._display_title(data)
                src_paths = self._extract_paths(data, ["src", "files"])
                dest_paths = self._extract_paths(data, ["dest"])
                for dest in dest_paths:
                    if not dest or not os.path.isfile(dest):
                        continue
                    try:
                        dest_size = int(os.stat(dest).st_size)
                    except OSError:
                        continue
                    for src in src_paths:
                        name = os.path.basename(self._normalize_path(src))
                        if name:
                            protections.setdefault(
                                (name, dest_size),
                                {"target_path": dest, "title": title},
                            )
            return protections
        finally:
            con.close()

    def _scan_history_db(self, db_path: str) -> List[Dict[str, Any]]:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            tables = set(self._sqlite_tables(con))
            items: List[Dict[str, Any]] = []
            if "transferhistory" in tables:
                items.extend(self._scan_transferhistory(con))
            if "downloadfiles" in tables:
                items.extend(self._scan_downloadfiles(con))
            if "downloadhistory" in tables:
                items.extend(self._scan_downloadhistory(con))
            return items
        finally:
            con.close()

    def _scan_transferhistory(self, con: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = self._fetch_rows(con, "transferhistory")
        items = []
        for row in rows:
            data = dict(row)
            title = self._display_title(data)
            src_paths = self._extract_paths(data, ["src", "files"])
            dest_paths = self._extract_paths(data, ["dest"])
            existing_dests = [path for path in dest_paths if os.path.exists(path)]
            dest_exists = bool(existing_dests)
            for path in src_paths:
                item = self._build_file_item(
                    path=path,
                    source="transferhistory",
                    title=title,
                    row=data,
                    status="source_and_dest_exist" if dest_exists else "source_without_dest",
                    target_path=existing_dests[0] if existing_dests else "",
                )
                if item:
                    items.append(item)
            for path in dest_paths:
                item = self._build_missing_item(path, "transferhistory", title, data)
                if item:
                    items.append(item)
        return items

    def _scan_downloadfiles(self, con: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = self._fetch_rows(con, "downloadfiles")
        items = []
        for row in rows:
            data = dict(row)
            title = self._display_title(data)
            paths = self._extract_paths(data, ["fullpath"])
            if not paths:
                paths = self._join_savepath_filepath(data)
            for path in paths:
                item = self._build_file_item(path, "downloadfiles", title, data, "history_existing_file")
                if item:
                    items.append(item)
                else:
                    missing = self._build_missing_item(path, "downloadfiles", title, data)
                    if missing:
                        items.append(missing)
        return items

    def _scan_downloadhistory(self, con: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = self._fetch_rows(con, "downloadhistory")
        items = []
        for row in rows:
            data = dict(row)
            title = self._display_title(data)
            for path in self._extract_paths(data, ["path"]):
                if os.path.isfile(path):
                    item = self._build_file_item(path, "downloadhistory", title, data, "history_existing_file")
                    if item:
                        items.append(item)
                elif path and not os.path.exists(path):
                    missing = self._build_missing_item(path, "downloadhistory", title, data)
                    if missing:
                        items.append(missing)
        return items

    def _scan_torrents(self) -> List[Dict[str, Any]]:
        items = []
        for root in self._split_paths(self._torrent_dirs):
            if not root or not os.path.isdir(root):
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    if not name.lower().endswith(".torrent"):
                        continue
                    path = os.path.join(dirpath, name)
                    item = self._build_file_item(
                        path=path,
                        source="torrent_cache",
                        title=name,
                        row={},
                        status="torrent_cache",
                        kind="torrent",
                    )
                    if item:
                        items.append(item)
        return items

    def _build_file_item(
        self,
        path: str,
        source: str,
        title: str,
        row: Dict[str, Any],
        status: str,
        kind: str = "file",
        target_path: str = "",
    ) -> Optional[Dict[str, Any]]:
        path = self._normalize_path(path)
        if not path or not os.path.isfile(path):
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        item = {
            "id": self._make_item_id(path, stat.st_size, stat.st_ino, kind),
            "kind": kind,
            "path": path,
            "target_path": self._normalize_path(target_path),
            "source": source,
            "status": status,
            "status_text": self._status_text(status),
            "title": title,
            "display_title": title or self._clean_text(row.get("torrentname")) or self._clean_text(row.get("torrent_name")),
            "size": int(stat.st_size),
            "size_text": self._format_size(stat.st_size),
            "nlink": int(getattr(stat, "st_nlink", 1)),
            "inode": int(getattr(stat, "st_ino", 0)),
            "mtime": int(getattr(stat, "st_mtime", 0)),
            "deletable": self._is_status_deletable(status) and self._is_allowed_delete_path(path),
        }
        return item

    def _build_missing_item(
        self,
        path: str,
        source: str,
        title: str,
        row: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        path = self._normalize_path(path)
        if not path or os.path.exists(path):
            return None
        return {
            "id": self._make_item_id(path, 0, 0, "missing"),
            "kind": "missing",
            "path": path,
            "source": source,
            "status": "record_missing_file",
            "status_text": self._status_text("record_missing_file"),
            "title": title,
            "display_title": title or self._clean_text(row.get("torrentname")) or self._clean_text(row.get("torrent_name")),
            "size": 0,
            "size_text": "-",
            "nlink": "-",
            "inode": 0,
            "mtime": 0,
            "deletable": False,
        }

    def _delete_item(self, item_id: str, apikey: str, expected_kind: str):
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        report = self.get_data("last_scan") or {}
        items = report.get("items") or []
        item = next((entry for entry in items if entry.get("id") == item_id), None)
        if not item:
            return schemas.Response(success=False, message="未找到扫描结果，请先重新扫描")
        if item.get("kind") != expected_kind:
            return schemas.Response(success=False, message="文件类型不匹配，已拒绝删除")
        if not item.get("deletable"):
            return schemas.Response(success=False, message="此路径不在允许删除范围内")

        path = self._normalize_path(item.get("path"))
        if not path or not self._is_allowed_delete_path(path):
            return schemas.Response(success=False, message="路径不在允许删除范围内")
        if not os.path.isfile(path):
            return schemas.Response(success=False, message="文件不存在或不是普通文件")

        try:
            stat = os.stat(path)
        except OSError as exc:
            return schemas.Response(success=False, message=f"读取文件状态失败：{exc}")

        if int(stat.st_size) != int(item.get("size") or -1):
            return schemas.Response(success=False, message="文件大小已变化，已拒绝删除")
        if int(getattr(stat, "st_ino", 0)) != int(item.get("inode") or -1):
            return schemas.Response(success=False, message="文件 inode 已变化，已拒绝删除")

        try:
            os.remove(path)
        except OSError as exc:
            return schemas.Response(success=False, message=f"删除失败：{exc}")

        task_message = ""
        if expected_kind == "file" and self._sync_downloader_tasks:
            task_message = self._sync_download_tasks(path)

        self._scan_and_save()
        message = f"已删除：{path}"
        if task_message:
            message = f"{message}；{task_message}"
        return schemas.Response(success=True, message=message)

    def _sync_download_tasks(self, path: str) -> str:
        records = self._find_download_records(path)
        if not records:
            return "未找到对应下载任务"

        handled: List[str] = []
        errors: List[str] = []
        for record in records:
            download_hash = self._clean_text(record.get("download_hash"))
            downloader = self._clean_text(record.get("downloader"))
            if not download_hash or download_hash in handled:
                continue
            ok, message = self._handle_torrent_task(download_hash, downloader)
            if ok:
                handled.append(download_hash)
                if self._sync_related_seeds:
                    handled.extend(self._handle_related_seed_tasks(download_hash, handled))
            else:
                errors.append(message)

        if handled and not errors:
            action_text = "已暂停" if self._downloader_action == "pause" else "已删除"
            return f"下载任务{action_text} {len(set(handled))} 个"
        if handled and errors:
            return f"下载任务已处理 {len(set(handled))} 个，失败 {len(errors)} 个"
        return "下载任务处理失败：" + "；".join(errors[:3])

    def _find_download_records(self, path: str) -> List[Dict[str, str]]:
        db_path = self._resolve_db_path()
        if not db_path:
            return []
        path = self._normalize_path(path)
        records: List[Dict[str, str]] = []
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
        except sqlite3.Error:
            return records
        try:
            if "downloadfiles" not in set(self._sqlite_tables(con)):
                return records
            rows = self._fetch_rows(con, "downloadfiles")
            for row in rows:
                data = dict(row)
                candidates = self._extract_paths(data, ["fullpath"])
                if not candidates:
                    candidates = self._join_savepath_filepath(data)
                if path not in candidates:
                    continue
                records.append(
                    {
                        "download_hash": self._clean_text(data.get("download_hash")),
                        "downloader": self._clean_text(data.get("downloader")),
                    }
                )
            return self._unique_download_records(records)
        finally:
            con.close()

    @staticmethod
    def _unique_download_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        unique = []
        for record in records:
            key = (record.get("download_hash") or "", record.get("downloader") or "")
            if not key[0] or key in seen:
                continue
            seen.add(key)
            unique.append(record)
        return unique

    def _handle_torrent_task(self, download_hash: str, downloader: str = "") -> Tuple[bool, str]:
        chain = getattr(self, "chain", None)
        if not chain:
            return False, "当前 MoviePilot 环境未提供下载链"
        try:
            if self._downloader_action == "delete":
                self._call_chain_torrent_method(chain, "remove_torrents", download_hash, downloader)
            else:
                self._call_chain_torrent_method(chain, "stop_torrents", download_hash, downloader)
            logger.info(f"媒体残留清理联动处理下载任务：{self._downloader_action} {downloader or '-'} {download_hash}")
            return True, download_hash
        except Exception as exc:
            logger.error(f"媒体残留清理处理下载任务失败：{downloader or '-'} {download_hash} {exc}")
            return False, f"{download_hash}: {exc}"

    @staticmethod
    def _call_chain_torrent_method(chain: Any, method_name: str, download_hash: str, downloader: str = ""):
        method = getattr(chain, method_name)
        if downloader:
            try:
                return method(hashs=download_hash, downloader=downloader)
            except TypeError:
                return method(download_hash)
        try:
            return method(hashs=download_hash)
        except TypeError:
            return method(download_hash)

    def _handle_related_seed_tasks(self, download_hash: str, handled: List[str]) -> List[str]:
        seed_history = self.get_data(key=download_hash, plugin_id="IYUUAutoSeed") or []
        if not seed_history or not isinstance(seed_history, list):
            return []
        related: List[str] = []
        for history in seed_history:
            downloader = self._clean_text(history.get("downloader"))
            torrents = history.get("torrents") or []
            if not isinstance(torrents, list):
                torrents = [torrents]
            for torrent_hash in torrents:
                torrent_hash = self._clean_text(torrent_hash)
                if not torrent_hash or torrent_hash in handled or torrent_hash in related:
                    continue
                ok, _message = self._handle_torrent_task(torrent_hash, downloader)
                if ok:
                    related.append(torrent_hash)
                    related.extend(self._handle_related_seed_tasks(torrent_hash, handled + related))
        if self._downloader_action == "delete" and related:
            try:
                self.del_data(key=download_hash, plugin_id="IYUUAutoSeed")
            except Exception:
                pass
        return related

    def _resolve_db_path(self) -> str:
        candidates = []
        if self._db_path:
            candidates.append(self._db_path)
        candidates.extend(
            [
                "/config/user.db",
                "/config/config/user.db",
                "/volume1/@appdata/MoviePilot/config/user.db",
            ]
        )
        for candidate in candidates:
            candidate = self._normalize_path(candidate)
            if candidate and os.path.isfile(candidate):
                return candidate
        return ""

    @staticmethod
    def _sqlite_tables(con: sqlite3.Connection) -> List[str]:
        cur = con.cursor()
        cur.execute("select name from sqlite_master where type='table'")
        return [row[0] for row in cur.fetchall()]

    @staticmethod
    def _fetch_rows(con: sqlite3.Connection, table: str) -> List[sqlite3.Row]:
        cur = con.cursor()
        cur.execute(f"select rowid as _rowid,* from {table}")
        return cur.fetchall()

    def _extract_paths(self, row: Dict[str, Any], keys: List[str]) -> List[str]:
        paths: List[str] = []
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            text = str(value).strip()
            if not text:
                continue
            paths.extend(self._paths_from_text(text))
        return self._unique_paths(paths)

    def _join_savepath_filepath(self, row: Dict[str, Any]) -> List[str]:
        savepath = self._clean_text(row.get("savepath"))
        filepath = self._clean_text(row.get("filepath"))
        if not savepath or not filepath:
            return []
        if filepath.startswith("/"):
            return [filepath]
        return [os.path.join(savepath, filepath)]

    def _paths_from_text(self, text: str) -> List[str]:
        paths: List[str] = []
        if os.path.isabs(text):
            paths.append(text)
        try:
            decoded = json.loads(text)
            paths.extend(self._paths_from_json(decoded))
        except Exception:
            pass
        paths.extend(re.findall(r"/volume[12]/[^\"]+", text))
        paths.extend(re.findall(r"/config/[^\"]+", text))
        return self._unique_paths(paths)

    def _paths_from_json(self, value: Any) -> List[str]:
        paths: List[str] = []
        if isinstance(value, str):
            if value.startswith("/"):
                paths.append(value)
        elif isinstance(value, list):
            for item in value:
                paths.extend(self._paths_from_json(item))
        elif isinstance(value, dict):
            for item in value.values():
                paths.extend(self._paths_from_json(item))
        return paths

    @staticmethod
    def _unique_paths(paths: List[str]) -> List[str]:
        seen = set()
        unique = []
        for path in paths:
            normalized = MediaResidueCleaner._normalize_path(path)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    @staticmethod
    def _normalize_path(path: Any) -> str:
        if path is None:
            return ""
        text = str(path).strip().strip("'\"")
        if not text:
            return ""
        text = text.replace("\\/", "/")
        text = os.path.normpath(text)
        return text

    def _split_paths(self, text: str) -> List[str]:
        parts = re.split(r"[\n,;]+", text or "")
        return [self._normalize_path(part) for part in parts if self._normalize_path(part)]

    @staticmethod
    def _stat_key(stat: os.stat_result) -> Tuple[int, int]:
        return int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0))

    def _is_under_any(self, path: str, roots: List[str]) -> bool:
        path = self._normalize_path(path)
        if not path:
            return False
        for root in roots:
            root = self._normalize_path(root)
            if not root:
                continue
            try:
                common = os.path.commonpath([path, root])
            except ValueError:
                continue
            if common == root:
                return True
        return False

    @staticmethod
    def _is_status_deletable(status: str) -> bool:
        return status in {
            "source_without_target",
            "target_exists_but_source_not_linked",
            "source_without_dest",
            "torrent_cache",
        }

    def _is_allowed_delete_path(self, path: str) -> bool:
        path = self._normalize_path(path)
        if not path or path == "/":
            return False
        roots = self._split_paths(self._allowed_roots)
        for root in roots:
            try:
                common = os.path.commonpath([path, root])
            except ValueError:
                continue
            if common == root and path != root:
                return True
        return False

    def _dedupe_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_key: Dict[Tuple[str, int, int, str], Dict[str, Any]] = {}
        priority = {
            "source_and_target_exist": 90,
            "source_and_dest_exist": 80,
            "target_exists_but_source_not_linked": 75,
            "source_without_target": 70,
            "source_without_dest": 60,
            "torrent_cache": 30,
            "history_existing_file": 20,
            "record_missing_file": 10,
        }
        for item in items:
            key = (item.get("path", ""), int(item.get("size") or 0), int(item.get("inode") or 0), item.get("kind", ""))
            previous = by_key.get(key)
            if not previous or priority.get(item.get("status"), 0) > priority.get(previous.get("status"), 0):
                by_key[key] = item
        return list(by_key.values())

    @staticmethod
    def _make_item_id(path: str, size: int, inode: int, kind: str) -> str:
        raw = f"{kind}|{path}|{size}|{inode}".encode("utf-8", errors="ignore")
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _status_text(status: str) -> str:
        mapping = {
            "source_without_dest": "源文件存在，整理目标不存在",
            "source_and_dest_exist": "源文件和整理目标都存在",
            "source_without_target": "目标目录未找到对应硬链接",
            "source_and_target_exist": "源文件和目标硬链接都存在",
            "target_exists_but_source_not_linked": "目标存在，但当前源文件不是硬链接",
            "record_missing_file": "只有历史记录，文件不存在",
            "torrent_cache": "种子缓存",
            "history_existing_file": "历史记录中的现存文件",
        }
        return mapping.get(status, status)

    @staticmethod
    def _status_color(status: str, deletable: bool = False) -> str:
        if deletable:
            return "error"
        mapping = {
            "source_and_target_exist": "success",
            "source_and_dest_exist": "success",
            "history_existing_file": "info",
            "record_missing_file": "default",
        }
        return mapping.get(status, "warning")

    @staticmethod
    def _format_size(size: Any) -> str:
        try:
            value = float(size or 0)
        except Exception:
            value = 0
        units = ["B", "K", "M", "G", "T"]
        idx = 0
        while value >= 1024 and idx < len(units) - 1:
            value /= 1024
            idx += 1
        if idx == 0:
            return f"{int(value)}{units[idx]}"
        return f"{value:.2f}{units[idx]}"

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _now_text() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    @staticmethod
    def _display_title(row: Dict[str, Any]) -> str:
        title = MediaResidueCleaner._clean_text(row.get("title"))
        year = MediaResidueCleaner._clean_text(row.get("year"))
        if title and year:
            return f"{title} ({year})"
        return title or MediaResidueCleaner._clean_text(row.get("torrentname")) or MediaResidueCleaner._clean_text(row.get("torrent_name"))
