# paper-download（DSH 技能）

在 **XMOL 学术**检索论文 → 按**影响因子/期刊**过滤 → 从**出版社官网**下载正式版 PDF → 输出清单。
包含对付付费墙、反爬虫和"点了下载却没反应"的排查方法。

## 它解决什么问题

批量下文献通常死在两件事上：

1. **反爬**：脚本直连出版商 PDF 会吃 403/Cloudflare，但**浏览器会话不会**；
2. **下载不落盘**：点了 PDF 只打开内置阅读器，文件根本没下来。

这个技能把两条都处理掉了：用真实浏览器 + 系统级鼠标点击，并预先把浏览器配置成
"PDF 强制外部下载"。

## 四条下载路线

| # | 路线 | 做法 | 适用 |
|---|---|---|---|
| 1 | `direct` | HTTP 直连已知 PDF 地址 | 开放获取期刊 |
| 2 | `session-fetch` | 在落地页里让页面自己 `fetch` PDF | 需要 cookie/订阅鉴权的小文件 |
| 3 | `landing-link` | 读落地页的 `meta[citation_pdf_url]` / PDF 链接 | 大多数出版社 |
| 4 | `os-click` | **真实鼠标点击**页面上的 Download PDF | 前三者都失败时兜底 |

全部为**出版社正式版**（开放获取或你自己的机构订阅），不含 arXiv、不含第三方镜像。

## 快速开始

```bash
cd scripts

python launch.py                        # 启动可驱动的浏览器窗口
python xmol.py search "Altermagnetism"  # 在窗口里真实输入关键词检索
python xmol.py harvest "Altermagnetism" # 逐页抓结果 → 过滤 IF/期刊
python download.py run                  # 四级路线下载 + PDF 校验
python verify.py                        # 生成 README 清单 + 手动下载清单
```

常用参数：`download.py run --limit 20`、`--min-if 15`、`download.py status`。

## 关键经验（SKILL.md 里有完整版）

- **默认 profile 的浏览器打不开调试端口**，必须用独立 profile 启动；
- **必须设 `plugins.always_open_pdf_externally=true`**，否则点击 PDF 只会打开阅读器；
- **APS 的 DOI 大小写敏感**：`physrevlett` → 404，`PhysRevLett` → 200；
- **XMOL 检索接口硬上限 300 条**（10 页 × 30），页面显示的总数可能更大；
- **反爬拦的是脚本 HTTP，不是浏览器**：同一时刻脚本 403、浏览器 200。

## 目录

```
scripts/
├── config.py       路径/端口/过滤规则
├── launch.py       启动可驱动窗口（含 PDF 强制下载配置）
├── xmol.py         XMOL 检索 / 逐页抓取 / 过滤
├── download.py     四级下载路线 + 断点续跑
├── verify.py       校验 + README 清单 + 手动下载清单
├── cdp.py          极简 CDP 客户端（纯标准库 WebSocket）
├── oswin.py        系统级鼠标键盘（SetCursorPos / mouse_event / SendInput）
├── driven.py       定位可驱动窗口并置前台
└── paperlib.py     PDF 校验与工具函数
```

## 依赖

- Python 3.10+（标准库 + `pypdf` 用于校验）
- Windows + Edge（或 Chrome）
- 一个已登录机构网络/校园网的机器（订阅权限来自 IP 或账号登录态）

## 合规红线

只下载开放获取或你本人机构订阅可合法访问的内容；不碰 Sci-Hub 之类的镜像；
点击节奏放慢（每篇 ≥2 秒），只读不写。

## License

MIT
