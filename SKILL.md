---
name: paper-download
description: 在 XMOL 学术检索论文、按影响因子与期刊过滤，然后从出版社官网下载正式版 PDF 并输出清单——包括对付付费墙、反爬虫和"点了下载却没反应"的排查。
whenToUse: 用户要求在 XMOL（或类似学术平台）检索某关键词的论文并批量下载 PDF、要求"影响因子 ≥ X"、"排除某几个期刊"、要求只下出版社正式版（不要 arXiv/镜像），或抱怨"PDF 下不下来""被反爬""要手动一篇篇点"时使用。
---

# XMOL 文献检索与批量下载

目标：把「在 XMOL 检索 → 按 IF/期刊过滤 → 从出版社官网拿正式版 PDF → 出清单」这条链跑通，
并且在下载失败时**说清楚是订阅没权限、反爬拦住了，还是文章下架了**。

脚本在 `{{SCRIPTS_DIR}}`，配置在 `{{SCRIPTS_DIR}}/config.json`（首次运行 `config.py` 会打印默认值）。

---

## 一、先读：四条用血换来的结论

### 1. 「默认配置的 Edge + 调试端口」是打不开的

实测：对一个**已经用默认 profile 运行的 Edge**，无论加不加 `--remote-debugging-port`，
`127.0.0.1:9222` 都不会监听（Chromium 拒绝为默认 profile 开 DevTools，
第二个实例又会被转发给已运行进程而直接退出）。

**对策**：skill 自己持有一个独立 profile（`edge-profile/`），用 `launch.py` 启动。
独立 profile 是**全新的 cookie**，所以：**订阅是校园网 IP 授权时照样能下**（实测 APS 全通、
Nature Communications 全通），**需要账号登录态时不行**——那种情况要么在这个窗口里登录一次，
要么让用户在自己浏览器里手动点（见第四节的手动清单）。

### 2. 必须先把「PDF 强制外部下载」打开，否则点击 PDF 只会打开内置阅读器

这是最常见的"点了没反应"：页面里的 PDF 链接被 Edge 内置阅读器接管，文件根本不会落到磁盘。
`launch.py` 会在启动前写入偏好：

```json
{"plugins": {"always_open_pdf_externally": true},
 "download": {"prompt_for_download": false, "default_directory": "<下载目录>"}}
```

另外 `Page.setDownloadBehavior(behavior=allow, downloadPath=<目录>)` 也要设，
两条都到位，浏览器才会把 PDF 直接写进目标目录。

### 3. 反爬拦的是「脚本 HTTP」，不是「浏览器」

同一台机器、同一时刻：

| 请求方式 | Wiley / ACS / RSC / OUP | APS | Nature 系 OA |
|---|---|---|---|
| Python `urllib` 直连 PDF | ❌ 403 Cloudflare | ✅ 200 | ✅ 200 |
| 浏览器内 `fetch`（带 cookie） | ✅ 拿到 PDF 字节 | ✅ | ✅ |
| 浏览器直接打开 PDF 地址 | ✅ 自动下载 | ✅ | ✅ |
| **系统级鼠标点击页面上的 "Download PDF"** | ✅ 最稳 | ✅ | ✅ |

所以**能用鼠标点击就别用脚本直连**——这也是平台更愿意接受的方式（点击频率别太猛）。

### 4. APS 的 DOI 大小写敏感

`journals.aps.org/prl/pdf/10.1103/physrevlett.134.106802` → **404**
`journals.aps.org/prl/pdf/10.1103/PhysRevLett.134.106802` → **200**

APSU 的 `physrevx/physrevlett/...` 必须写成 `PhysRevX/PhysRevLett/...`。
XMOL 给的 DOI 常常是全小写，`download.py` 里已做归一化；
**另外 APS 官网搜索（`journalals.aps.org/search/results?q=`）给出的 `abstract` 链接里就是正确大小写**，
拿它把 `/abstract/` 换成 `/pdf/` 最保险。

---

## 二、三条命令跑完主流程

```bash
cd "{{SCRIPTS_DIR}}"

python launch.py                       # 1) 启动可驱动的窗口（含 PDF 强制下载配置）
python xmol_adv.py "Altermagnetism" 2026 5   # 2) 高级检索：关键词+年份+IF，**完整翻页**
python resolve.py fill                 # 3) 给 XMOL 没给 DOI 的条目补规范 DOI（Crossref）
python resolve.py oa                   # 4) 标注是否开放获取 + 免费全文地址（OpenAlex）
python access_map.py show              # 5) 查看出版社准入表（哪些直接跳过）
python download.py run                 # 6) 逐篇按四条路线下载 + 校验（自动跳过无权限出版社）
python verify.py                       # 7) 校验全部 PDF + 生成 README.md 与手动下载清单
```

> `xmol.py`（旧路径）保留作为"只取前 30 条"的快速摸底；**要全量必须用 `xmol_adv.py`**。

常用参数：

```bash
python download.py run --limit 20      # 先试跑 20 篇
python download.py run --min-if 15     # 只下 IF≥15 的
python download.py run --only-oa       # 只下确认开放获取的（先跑过 resolve.py oa）
python download.py status              # 已下/还差多少，按期刊统计
python resolve.py report               # 免订阅可达性总览（OA / 非 OA / 未查）
python access_map.py probe             # 重新探测各出版社可达性
python verify.py --check               # 只做校验表
```

### ⚠️ 最容易踩的坑：XMOL 检索的两个接口（实测）

**用错接口会让"全量"变成"抽样"，而且毫无报错。**

| 接口 | 行为 |
|---|---|
| `/spaceApi/next/paper/doc/search?option=…&pageNo=N` | **只返回前 30 条**；`pageNo=2` 返回空；`start/offset/page/pageNum` 全部无效；`startDate/endDate/startYear/…` 等日期参数被静默忽略 |
| `/spaceApi/next/paper/doc/createPaperAdvancedSearch` | UI 提交高级检索时调用，**把关键词/出版时间/IF 条件存在服务端**并返回 `searchLogId` |
| `/spaceApi/next/paper/doc/searchPaperAdvancedById?searchLogId=…&pageNo=N` | 取**上面那份**检索结果的第 N 页；`totalRecord`/`totalPage` 真实可用 |

**正确流程**（`xmol_adv.py` 已实现）：

1. 在窗口里填「关键词 + 出版时间 + IF」，点**立即搜索**（真实事件）；
2. 从地址栏取 `searchLogId`；
3. 用 `searchPaperAdvancedById` 翻完 `totalPage` 页。

实测：关键词 `Altermagnetism` + 出版时间 2026 + IF 5 → **196 条命中、7 页全部取回**。
而错误流程在同一条件下只拿到 63 条（且 `total` 恒显示为上限 300）。

> `IF` 的真实参数名是 `impactFactorStart` / `impactFactorEnd`（`ifStart` 无效）；
> `journalId` 也是有效切面；`pageNo` 配合 `searchPaperAdvancedById` 才真正翻页。

### 出版社准入表（`access_map.py`）

同一台机器上，各出版社的可达性差别很大，且**直连探测看不出浏览器会话有没有订阅权**。
所以准入表以**实战结果**为准，并让下载器据此跳过必然失败的论文（每篇省约 40 秒）：

| 判定 | 含义 | 本机实测 |
|---|---|---|
| `reachable` | 有办法拿到 PDF（直连 / 页面内点击 / session-fetch） | Nature 系、APS、ACS、RSC、OUP、Springer、SciPost |
| `refused` | 出版社拒绝（脚本与浏览器内都返回 HTML） | Wiley（10.1002） |
| `captcha` | 反爬挑战自动化过不去 | Elsevier（10.1016）、IOP（10.1088） |

```bash
python access_map.py probe   # 直连探测一遍（只用于补我们没有经验的出版社）
python access_map.py show    # 查看当前判定与判据
```

`download.py run` 会自动跳过 `refused`/`captcha` 的论文并把原因写进状态表；
实测某次 196 篇里有 51 篇属于这类，直接省掉约 34 分钟无效尝试。

### 为什么不换谷歌学术，而用 resolve.py 补短板

谷歌学术在本网络下**根本连不上**（实测 `scholar.google.com` 21 秒超时、`google.com` 连接被重置），
而且它本身不托管全文——点进去还是落到同一个出版社页面，**换检索源不改变能否下载**。
XMOL 不可替代的点是结果里直接带 `impactFactor` 字段，IF 筛选一步做完。

XMOL 的两个短板由两个**免登录、无反爬**的结构化接口补上：

| 命令 | 接口 | 解决什么 |
|---|---|---|
| `resolve.py fill` | Crossref | XMOL 有约 6% 条目**没有 DOI**；Crossref 按标题反查规范 DOI，并能发现 XMOL 期刊标错（标成 PRL 实为 PRB，按排除规则剔除） |
| `resolve.py oa` | OpenAlex | 事先知道**哪些是开放获取、免费全文在哪**，避免对必然失败的付费文章白跑一遍（每篇约 40 秒） |

实测（关键词 `Altermagnetism`，112 篇候选）：开放获取 **71 篇**、非 OA 34 篇、未查 7 篇。
非 OA 中 IF 最高的为 Nature Materials / Nature Nanotechnology / Nature Physics / ACS Nano / JACS
——这些要么靠机构订阅，要么只能手动。

### 过滤规则

- `IF ≥ minImpactFactor`（默认 5.0），IF 取 XMOL 结果里的 `impactFactor` 字段
- 排除 `excludeJournals`（默认 Physical Review B / Physical Review Materials / Applied Physics Letters）
- 只收**出版社正式版**；arXiv、ResearchGate、Sci-Hub 一律不用（想加 arXiv 兜底要显式说明）

### 四条下载路线（`download.py` 按顺序试）

| # | 路线 | 做法 | 适用 |
|---|---|---|---|
| 1 | `direct` | HTTP 直连已知 PDF 地址 | OA 期刊（Nature Comms、npj 系、Springer OA） |
| 2 | `session-fetch` | 在落地页里让**页面自己** fetch PDF → base64 回传 | 需要 cookie/订阅鉴权，且文件不太大 |
| 3 | `landing-link` | 打开落地页 → 读 `meta[citation_pdf_url]` 或页面上的 PDF 链接 → 浏览器打开 | 大多数出版社 |
| 4 | `os-click` | 定位页面上的 "Download PDF" 控件 → **真实鼠标点击** | 前三者都失败时的兜底 |

> 路线 2 有坑：PDF 转 base64 后如果超过约 1 MB，`Runtime.evaluate` 回传容易超时。
> 所以路线 2 只用于小文件；大文件走 3/4（浏览器自己写盘，不经 WebSocket）。

---

## 三、XMOL 侧的技术细节

- 搜索页是 Next.js，**搜索结果走的接口**是：
  `GET /spaceApi/next/paper/doc/search?option=<关键词>&pageNo=<n>&pageSize=30`
- 裸 HTTP 请求它 → `401 {"msg":"请先登录再继续访问"}`；
  用真实浏览器（页面上下文 `fetch`，带上 cookie）→ `200`，返回
  `obj.pageResults.results[]`，每行含 `title / journalName / impactFactor / doi / pubDate / oaStatus`。
  **`impactFactor` 直接可用，不需要另外查 IF 表。**
- ⚠️ **接口硬上限 300 条（10 页 × 30）**。页面显示"共有 N 个结果"可能远大于 300
  （例：显示 448，实际只放 300 条明细）。要覆盖全量就把检索式切片
  （按年份、按期刊、按子关键词分别 harvest 再合并去重）。
- 直接 `GET /paper/search/q?...` 会撞阿里云验证码；走"真实键盘输入 + 点立即搜索"就正常。
- XMOL 里很多"期刊名"字段是页面上的 IF 标签，与 JCR 年份可能差一年，作筛选依据够用，写报告时注明来源。

---

## 四、下不下来的怎么办（重要）

`verify.py` 会把未获取的论文写成两张表：

- `<下载目录>/README.md`：已下载清单（标题/期刊/IF/日期/DOI/页数/文件名）
- `<工作目录>/missing_manual.md`：**未获取清单 + 每篇的 DOI 跳转入口**，方便手动点

同时 `download.py status` 会按期刊汇总缺口。典型缺口与原因：

| 现象 | 真实原因 | 处理 |
|---|---|---|
| `403` + Cloudflare 页面 | 脚本直连被拦 | 走浏览器点击（路线 3/4） |
| 页面是 `请稍候…` | 反爬 JS 挑战还没跑完 | 多等几秒再读 DOM（`wait_ready`），或直接点链接 |
| 页面显示 "You have full access via <学校>" 但 `.pdf` 返回 HTML | 该刊没有订阅，或按钮在 iframe 里 | 点页面上的 PDF 按钮；仍失败就记入手动清单 |
| APS 返回 404 | DOI 大小写 | 用 `PhysRevLett` 形式，或从 APS 搜索页取链接 |
| Crossref 查出该文其实属 PRB/PRM/APL | XMOL 期刊字段标错 | 按排除规则剔除，不要下 |
| 官网搜不到、Crossref 也查不到 | 可能已下架/撤稿 | 记入手动清单，别硬试 |

**红线**：只用开放获取或用户本人机构订阅能合法访问的内容；不碰 Sci-Hub 之类镜像；
点击节奏放慢（每篇间隔 ≥2 秒），只读不写（不点赞、不下载无关内容）。

---

## 五、排错速查

| 现象 | 处理 |
|---|---|
| `no page target on port 9222` | 窗口没起来 → `python launch.py`；确认没有第二个实例占着 `edge-profile` |
| 端口拒连但进程在跑 | 用 `--force` 重启：`python launch.py --force`（只杀自己 profile 的进程） |
| 点击后没有文件 | 检查 `always_open_pdf_externally` 是否写入 + `Page.setDownloadBehavior` 是否设置 |
| `Runtime.evaluate: Inspected target navigated or closed` | 导航还没完成就发指令 → 先 `wait_ready()` 再操作 |
| `fetch` 返回 `Failed to fetch` | 页面在 `edge://` 或跨域；先切到目标站点再 fetch |
| XMOL 接口 401 | 请求不是从 x-mol 页面上下文发出的 → 用 `xmol.py harvest`，别用 urllib |
| 只抓到 300 条 | 接口上限，切片检索式（见第三节） |
| 目录里出现 2 页的小 PDF | 多半是 `citation_pdf_url` 落到了 "reference" 或摘要页 → `verify.py` 会标 `!!`，删除重下 |

---

## 六、目录约定

```
{{SCRIPTS_DIR}}/
├── config.py / config.json    路径、端口、过滤规则
├── cdp.py                     极简 CDP 客户端（纯标准库 WebSocket）
├── oswin.py                   系统级鼠标键盘（SetCursorPos + mouse_event + SendInput）
├── driven.py                  找可驱动窗口的 OS 窗口句柄/矩形、置前台
├── paperlib.py                PDF 校验、arXiv/OpenAlex 查询、工具函数
├── launch.py                  启动可驱动窗口（含 PDF 强制下载 + 禁用 onboarding 劫持）
├── xmol_adv.py                **XMOL 高级检索全量抓取**（create + 分页，推荐）
├── xmol.py                    旧路径：单查询只取前 30 条，适合快速摸底
├── resolve.py                 Crossref 补 DOI + OpenAlex 判开放获取（免登录、无反爬）
├── access_map.py              出版社准入表：refused/captcha 的直接跳过
├── download.py                四条路线下载 + 断点续跑（状态存 statusFile）
└── verify.py                  校验 + README.md + 手动下载清单
```

上次实测战绩（关键词 `Altermagnetism`，IF≥5 且排除 PRB/PRM/APL）：
候选 112 篇 → **成功 97 篇正式版 PDF**，其中 Nature 2、Nature Materials 1、Nature Physics 1、
Nature Nanotechnology 1、Nature Communications 4、PRL 20+、PRX 3、JACS 9、Nano Letters 13（全部）、
ACS Nano、ACS Materials Au、RSC 综述与 Nanoscale、npj 系 11、Advanced Materials 等。

剩余 8 篇未获取，原因均已写进交付清单：
| 原因 | 篇数 | 说明 |
|---|---|---|
| 该刊无订阅权限 | 1 | Nature Reviews Materials（页面显示 Subscribe） |
| Wiley 拒绝脚本下载 | 2 | Advanced Science、Rare Metals；页面有 Download PDF 按钮，浏览器里手点可下 |
| 出版社反爬 | 5 | ScienceDirect ×3、IOP（Radware 验证码）、Elsevier |
其余 7 条为 XMOL 里无 DOI 的重复条目（Crossref 也查不到，多为预印本条目）。
