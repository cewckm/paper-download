# paper-download（DSH 技能）

[English](README.md) | **中文**

在 **XMOL 学术**检索论文 → 按**影响因子/期刊**过滤 → 从**出版社官网**下载正式版 PDF → 输出清单。
附带对付付费墙、反爬虫和"点了下载却没反应"的排查方法。

## 它解决什么问题

批量下文献通常死在两件事上：

1. **反爬**：脚本直连出版商 PDF 会吃 403/Cloudflare，而**真实浏览器会话不会**；
2. **下载不落盘**：点了 PDF 只打开内置阅读器，文件根本没下来。

这个技能把两条都处理了：驱动真实浏览器，并预先把浏览器配置成「**PDF 强制下载而不是渲染**」。

## 四条下载路线

| # | 路线 | 做法 | 适用 |
|---|---|---|---|
| 1 | `direct` | HTTP 直连已知 PDF 地址 | 开放获取期刊 |
| 2 | `session-fetch` | 在落地页里让页面自己 `fetch` PDF | 需要 cookie/订阅鉴权的小文件 |
| 3 | `landing-link` | 读落地页的 `meta[citation_pdf_url]` / 页面自带 PDF 链接 | 大多数出版社 |
| 4 | `os-click` | **真实鼠标点击**页面上的 Download PDF 控件 | 兜底 |

全部为**出版社正式版**（开放获取或你自己的机构订阅），不含 arXiv、不含第三方镜像。

## 快速开始

```bash
cd scripts

python launch.py                        # 启动可驱动的浏览器窗口
python xmol.py search "Altermagnetism"  # 在窗口里真实输入关键词检索
python xmol.py harvest "Altermagnetism" # 逐页抓结果 → 按 IF/期刊过滤
python resolve.py fill                  # 补全缺失的 DOI（Crossref）
python resolve.py oa                    # 标注开放获取与免费全文地址（OpenAlex）
python download.py run                  # 四级路线下载 + PDF 校验
python verify.py                        # 生成 README 清单 + 手动下载清单
```

常用参数：`download.py run --limit 20`、`--min-if 15`、`--only-oa`、`download.py status`、
`resolve.py report`。

## 为什么不换谷歌学术

谷歌学术在本网络下**根本连不上**（实测 `scholar.google.com` 21 秒超时、`google.com` 连接被重置），
而且它本身不托管全文——点进去还是落到同一个出版社页面，**换检索源不改变能否下载**。
XMOL 不可替代的点是结果里直接带 `impactFactor` 字段，IF 筛选一步做完。

XMOL 的两个短板由两个**免登录、无反爬**的结构化接口补上：

| 命令 | 接口 | 解决什么 |
|---|---|---|
| `resolve.py fill` | Crossref | XMOL 有约 6% 条目**没有 DOI**；Crossref 按标题反查规范 DOI，并能发现 XMOL 期刊标错（标成 PRL 实为 PRB） |
| `resolve.py oa` | OpenAlex | 事先知道**哪些是开放获取、免费全文在哪**，避免对必然失败的付费文章白跑一遍（每篇约 40 秒） |

实测（关键词 `Altermagnetism`，112 篇候选）：开放获取 71 篇、非 OA 34 篇、未查 7 篇。

## 关键经验（SKILL.md 里有完整版）

- **默认 profile 的浏览器打不开调试端口**，必须用独立 profile 启动；
- **必须禁用内置 PDF 阅读器**（`plugins.always_open_pdf_externally` 配合
  `Page.setDownloadBehavior`），否则点击 PDF 永远不会落盘；
- **APS 的 DOI 大小写敏感**：`physrevlett` → 404，`PhysRevLett` → 200；
- **XMOL 检索接口硬上限 300 条**（10 页 × 30），页面显示的总数可能更大；
- **反爬拦的是脚本 HTTP，不是浏览器**：同一台机器同一秒，脚本 403、浏览器 200；
- 出版社**拒绝"直接打开 PDF 地址"**，但接受**点击页面上的 Download PDF**——点击要在页面内派发，
  不要用屏幕坐标（窗口一动就失效）。

## 目录

```
scripts/
├── config.py       路径/端口/过滤规则
├── launch.py       启动可驱动窗口（预置 PDF 强制下载）
├── xmol.py         XMOL 检索 / 逐页抓取 / 过滤
├── resolve.py      Crossref 补 DOI + OpenAlex 开放获取预判
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
- 一台处于「你打算使用的订阅」网络下的机器（IP 授权或已登录）

## 合规红线

只下载开放获取或你本人机构订阅可合法访问的内容；不碰 Sci-Hub 之类的镜像；
节奏放慢（每篇 ≥2 秒），只读不写。

## License

MIT
