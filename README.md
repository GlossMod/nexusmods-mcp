# Nexus Mods MCP

<div align="center">

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![MCP 1.x](https://img.shields.io/badge/MCP-1.x-green.svg)](https://modelcontextprotocol.io/)

**查找游戏和 Mod，浏览图集、前置与版本文件，按账户权限下载。**

</div>

---

## ✨ 项目简介

这个非官方本地 stdio 服务通过 Nexus Mods 的 GraphQL 和 REST API 获取资料。项目由游戏域名和该游戏内的 Mod ID 共同定位，例如 `skyrimspecialedition` 下的 SkyUI 是 `12604`。可以分别查看项目声明的前置、依赖它的其他作品，以及某个文件版本的依赖。

## ⚡ 快速开始

### 前置条件

- Python 3.11 或更高版本，以及 [uv](https://docs.astral.sh/uv/)。
- 公开目录和项目资料可匿名查询。读取受限文件资料或请求下载地址时，可从 [Nexus Mods 账户设置](https://www.nexusmods.com/settings/api-keys) 获取个人 API Key。

### 安装与更新

从 PyPI 安装或更新：

```sh
python -m pip install --upgrade glossmod-nexusmods-mcp
```

安装后运行 `nexusmods-mcp`，或用 `uvx --from glossmod-nexusmods-mcp nexusmods-mcp` 直接启动。

从源码运行时，在 `nexusmods-mcp` 仓库根目录执行：

```sh
uv sync --python 3.11
```

更新仓库源码后，重新执行上面的命令并重启客户端中的服务。若使用已有的 Python 虚拟环境，也可以用 `python -m pip install --upgrade .` 安装或更新，启动命令为 `nexusmods-mcp`。

### 配置客户端

使用账户权限时，在仓库根目录的 `.env` 中设置以下变量。已有 OAuth 访问令牌也可通过 `NEXUSMODS_ACCESS_TOKEN` 提供。仅需匿名查询时，直接从下方 `args` 中移除 `"--env-file", ".env"` 即可启动。

```dotenv
NEXUSMODS_API_KEY='替换为你的个人 API Key'
# 可选；默认目录为 ~/Downloads/NexusMods
# NEXUSMODS_DOWNLOAD_DIR=E:/Downloads/NexusMods
```

将以下条目加入使用 `mcpServers` 格式的客户端，把 `--directory` 后的示例路径替换为本仓库的绝对路径。使用 VS Code 的 `.vscode/mcp.json` 时，顶层键使用 `servers`。

```json
{
  "mcpServers": {
    "nexusmods-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "E:/GitHub/mcp/nexusmods-mcp", "run", "--no-sync", "--env-file", ".env", "nexusmods-mcp"]
    }
  }
}
```

### 第一次调用

试试「查找《Skyrim Special Edition》的 SkyUI，给我项目主页和图集，再列出主文件」。先用 `find_games(name="Skyrim")` 取得 `domainName`，再调用 `find_mods(game_domain="skyrimspecialedition", name="SkyUI")`。

## 🧰 工具列表

| 工具                    | 主要参数                                                                    | 用途                                                                                                  |
| ----------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `find_games`            | 可选 `name`、`sort`、`direction`、`offset`、`count`                         | 按名称片段查游戏，返回 ID 和 `domainName`。                                                           |
| `find_mods`             | 可选 `game_domain`、`name`、`author`、`category`、`tag`、`adult_content` 等 | 筛选或排序 Mod，取得 `modId` 和项目主页。                                                             |
| `get_mod`               | `game_domain`、`mod_id`                                                     | 读取介绍、作者、上传者、封面、标签、统计和主页。`v3.data.gallery_images` 保留站点图集及各尺寸链接。   |
| `get_requirements`      | `game_domain`、`mod_id`；可选 `offset`、`reverse_offset` 等                 | 分别返回所需 Mod、所需 DLC 及依赖本项目的作品。用 `include_disabled_legacy=true` 查看已停用的旧声明。 |
| `get_file_requirements` | `game_domain`、`mod_id`、`file_id`                                          | 读取所选文件版本的依赖范围及 DLC 要求，需要相应账户权限。                                             |
| `list_files`            | `game_domain`、`mod_id`；可选 `category`、`offset`、`count`                 | 列版本、归档名和字节数，可按 `MAIN`、`OPTIONAL` 或 `ARCHIVED` 等类别筛选。                            |
| `get_file`              | `game_domain`、`mod_id`、`file_id`                                          | 读取文件的 GraphQL 元数据、网页地址和当前凭据可读取的 REST 详情。                                     |
| `get_download_links`    | `game_domain`、`mod_id`、`file_id`；可选 `nxm_url`                          | 申请指定文件的限时镜像地址。若需要网页授权，返回 `filePage`。                                         |
| `download_file`         | `game_domain`、`mod_id`、`file_id`；可选 `nxm_url`                          | 请求有效镜像并写入本地，返回绝对路径、实际字节数及校验结果。                                          |

**分页与依赖。** 搜索使用 `offset`、`count` 和 `totalCount`。`get_requirements` 的 `nexusRequirements` 是项目需要的 Mod，`modsRequiringThisMod` 是依赖它的作品；用 `reverse_offset` 独立翻后者的页。项目关闭旧依赖系统时，选择具体版本并使用 `get_file_requirements`。

**下载授权。** 有效的 API Key 可以读取更多文件资料。能否直接下载还取决于账户和具体文件。若返回 `web_authorization_required`，打开 `filePage`，按站点流程获取同一游戏、Mod 和文件的 `nxm://` 链接，然后作为 `nxm_url` 传入。下载器保留同名文件；`hashes.sha256` 为本地计算值，实际核对过的上游摘要另列在 `verifiedUpstreamHashes`。

## 测试

```powershell
uv run python -m unittest discover -s tests -v
```

用 SkyUI 进行实站验证时，在 PowerShell 中执行以下命令。下载获准时会写入临时目录，网页授权要求会单独报告。

```powershell
$env:NEXUSMODS_LIVE_TEST = '1'
uv run --env-file .env python -m unittest discover -s tests -p test_live.py -v
```

## 构建与发布到 PyPI

首次发布前，在 PyPI 为 `glossmod-nexusmods-mcp` 登记 GitHub Trusted Publisher。仓库所有者填 `GlossMod`，仓库名填 `nexusmods-mcp`，工作流文件填 `publish.yml`，环境填 `pypi`。新项目可在 [PyPI Publishing](https://pypi.org/manage/account/publishing/) 预先登记。

在 `GlossMod/nexusmods-mcp` 的 GitHub Releases 页面为目标提交选择新标签，点击 **Publish release**。例如，`v0.2.0` 会发布 `glossmod-nexusmods-mcp==0.2.0`，`v0.2.0rc1` 会发布候选版。GitHub Actions 从标签取版本，构建并校验 wheel 和源码包，然后发布到 PyPI。可在本地运行 `uv build` 检查开发版本的构建产物。

参考：[Nexus Mods GraphQL](https://graphql.nexusmods.com/) · [REST v3 接口规范](https://raw.githubusercontent.com/Nexus-Mods/Vortex/master/packages/nexus-api-v3/schema/openapi.yaml)
