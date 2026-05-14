# Heiyumiao MoviePilot Plugins

这是 `heiyumiao` 的个人 MoviePilot 插件源，目前只保留自用和测试插件。

插件源地址：

```text
https://github.com/heiyumiao/MoviePilot-Plugins
```

## 插件列表

### MediaResidueCleaner / 媒体残留清理

按源文件夹和目标媒体库文件夹核对硬链接，同时读取 MoviePilot 媒体整理历史，辅助找出整理后遗留的原始下载文件。

主要用途：

- 扫描源目录和目标媒体库目录，按 inode 判断硬链接是否仍存在。
- 读取 MoviePilot `transferhistory` 等媒体整理历史作为辅助判断。
- 源文件和目标硬链接都存在时只展示，不计入可释放空间。
- 只对可疑残留提供手动删除按钮，删除前校验路径、大小和 inode。

插件目录：

```text
plugins.v2/mediaresiduecleaner
```

## 使用方式

在 MoviePilot 的插件市场中添加第三方插件源：

```text
https://github.com/heiyumiao/MoviePilot-Plugins
```

如果插件市场缓存没有立即刷新，可以等待缓存过期，或重启 MoviePilot 后重新进入插件市场。

## 仓库内容

- `package.v2.json`：MoviePilot V2 插件市场索引。
- `plugins.v2/`：插件源码。
- `icons/`：插件图标。
- `docs/`：保留的官方开发文档，方便后续维护插件。
- `README.official.md`：官方原 README 备份。

## 开发备注

这个仓库不是官方全量插件市场，只作为个人插件源使用。官方仓库和开发文档见：

- https://github.com/jxxghp/MoviePilot-Plugins
- [官方原 README](./README.official.md)
- [V2 插件开发指南](./docs/V2_Plugin_Development.md)
