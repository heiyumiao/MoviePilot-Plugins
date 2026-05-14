# 媒体残留清理

扫描 MoviePilot 历史记录中的源文件、整理目标和种子缓存，帮助找出“整理后的媒体已经删除，但原始下载文件还留着”的空间残留。

## 功能

- 只读扫描 `transferhistory`、`downloadfiles`、`downloadhistory`。
- 检查源路径、目标路径、文件大小、inode、硬链接数。
- 标记源文件存在但整理目标不存在的可疑残留。
- 扫描 MoviePilot `config/temp` 下的 `.torrent` 缓存。
- 支持手动删除单个扫描结果文件。

## 安全策略

- 不会自动删除任何文件。
- 删除只能针对最近一次扫描结果里的条目。
- 删除前会校验路径、文件大小和 inode。
- 默认不会修改 MoviePilot 数据库历史记录。
- 默认允许删除范围为 `/volume1`、`/volume2`、`/downloads`、`/media`、`/config`，可在插件配置中调整。

## 建议用法

1. 打开插件详情页，让它完成一次扫描。
2. 先看“源文件存在，整理目标不存在”的记录。
3. 确认路径确实是原始下载残留后，再点击删除。
4. 如果只想清小文件，可以只删除 `.torrent` 缓存项。

## 配置

- `MoviePilot user.db 路径`：留空自动尝试 `/config/user.db`、`/config/config/user.db`、`/volume1/@appdata/MoviePilot/config/user.db`。
- `允许删除的根目录`：只有这些根目录下的普通文件可以被插件删除。
- `种子缓存目录`：默认扫描 `/config/temp` 和 `/volume1/@appdata/MoviePilot/config/temp`。
