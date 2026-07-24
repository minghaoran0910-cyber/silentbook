# SilentBook 分发与打包方案

> 目标：让"有服务器的人"和"只想在自己电脑上用的人"都能低门槛跑起来。
> 本文档是决策记录 + 执行路线图，不是营销文案。

---

## 一、先想清楚：谁会用 SilentBook？

SilentBook 是 6 服务的分布式系统（Frontend + Backend + Agent + Parser + PostgreSQL + Redis），且处理的是**银行短信级别的敏感财务数据**。这决定了它的受众画像：

| 人群 | 占比预判 | 他们要什么 | 他们怕什么 |
|------|---------|-----------|-----------|
| **技术自托管用户**（V2EX/少数派/NAS 玩家） | 主力 | Docker 一键起、代码透明、数据不出门 | 闭源黑盒、数据上传第三方 |
| **轻度个人用户**（想在自己电脑记账） | 次要 | 双击就能用、别让我装数据库 | 复杂的命令行、Docker |
| **尝鲜围观者** | 长尾 | 先看看长啥样 | 安装半天跑不起来 |

**关键判断：主力人群是技术自托管用户。** 对这群人，"Docker 一键部署 + 代码全透明" 的吸引力，远大于 "一个读我银行短信的闭源 .exe"。财务软件 + 闭源可执行文件 = 信任成本极高。

---

## 二、桌面打包（Win/Mac）：先泼冷水

### 方案 A：Electron / Tauri 套壳浏览器窗口
**结论：不做。**
只是套个浏览器壳，**根本不解决"后端在哪跑"** 的问题——PostgreSQL、Redis 还是得有个地方运行。套壳 = 自欺欺人，还凭空增加几十 MB 体积。

### 方案 B：真·桌面应用（Tauri + 后端编译成二进制 + 换 SQLite + 砍 Redis）
**结论：能做，但不是现在。**
这是 1-2 周的活，PyInstaller 编译 FastAPI 是出了名的坑，后续每个依赖更新都要重新验证打包，维护成本极高。而且它解决的是"次要人群"的需求。

### 为什么架构其实已经为桌面铺好路了
- `database.py` 里**已经有 SQLite 分支**（`if not DATABASE_URL.startswith("sqlite")`）
- Redis **只有 `main.py` 用它做限流**，且已有 fail-open 兜底（Redis 挂了照常运行）

也就是说，**去掉 PostgreSQL 和 Redis 依赖、单进程跑 SQLite 的"轻量模式"，架构上是通的**。这才是降低个人用户门槛的真正钥匙，比 .exe 实在得多。

---

## 三、推荐路线图（按 ROI 排序）

### Phase 1 · 跨平台一键安装脚本 ✅（本次交付）
**面向：有服务器/Mac/Linux 的技术用户。**
- `install.sh`（Linux/macOS）+ `install.ps1`（Windows）
- 自动检测 Docker 环境
- **自动生成安全密钥**（JWT_SECRET / WEBHOOK_SECRET / BACKUP_ENCRYPTION_KEY），解决 `.env` 里 `:?` 强制要求导致新手卡住的问题
- 交互式填入 LLM API Key
- 一条命令拉起全部服务 + 等待健康检查

**用户视角：**
```bash
curl -fsSL https://raw.githubusercontent.com/minghaoran0910-cyber/silentbook/main/install.sh | bash
```

### Phase 2 · SQLite 轻量单用户模式（下一个里程碑）
**面向：只想在自己电脑上用的个人用户。**
- 新增 `docker-compose.lite.yml`：单容器跑 backend（内置 SQLite + 内存限流），不需要 PostgreSQL/Redis
- 或提供 `pip install silentbook && silentbook serve` 的本地直跑方式
- 数据存本地 `~/.silentbook/data.db`，零配置

**价值：** 把"6 服务分布式系统"折叠成"一条命令的本地应用"，这是个人用户体验的质变。

### Phase 3 · npm / 包管理器分发（社区生态）
**面向：想集成、想二次开发的开发者。**
- **不做 npm 包**（SilentBook 是 Python 后端 + Nuxt 前端，npm 不是它的自然生态）
- 正确姿势：
  - **PyPI 包**：把 backend 发布为 `pip install silentbook`（配合 Phase 2 的本地直跑）
  - **Docker Hub 镜像**：预构建镜像 `docker pull minghaoran0910/silentbook`，免去用户本地 build
  - **Homebrew formula**（macOS）：`brew install silentbook`
- 这才是"其他人有服务器"时最顺滑的分发方式

### Phase 4 · 真桌面应用（远期，可选）
**前提：Phase 2 的 SQLite 单进程模式必须先成熟。**
- 用 Tauri 套壳 SQLite 模式的后端，打包 macOS `.dmg` / Windows `.exe`
- 此时成本才低、才有意义
- **现在不做。**

---

## 四、本次实际交付

- [x] `install.sh` — Linux/macOS 一键安装脚本（自动生成密钥 + 拉起服务）
- [x] `install.ps1` — Windows PowerShell 安装脚本
- [x] 本方案文档 `docs/distribution.md`
- [x] `docker-compose.lite.yml` — SQLite 轻量模式（已通过服务器并发 E2E 验证：注册/并发登录/health 均正常，无跨线程错误）
- [ ] Docker Hub 预构建镜像（Phase 3）

---

## 五、为什么是这个顺序（deep-grill 结论）

1. **先 Docker 一键，不做 .exe** —— 主力人群是技术自托管用户，Docker 是他们的母语；.exe 读银行短信的信任成本太高。
2. **先 SQLite 轻量，再做 Tauri 壳** —— 桌面打包的真正障碍是"后端依赖太重"，SQLite 模式先解决这个问题，套壳才有意义。
3. **PyPI + Docker Hub，不做 npm** —— 尊重技术栈的自然生态，不为了"看起来有 npm 包"而强行错位。
4. **脚本自动生成密钥** —— 这是新手部署失败的头号原因，ROI 极高。

---

*有想法？欢迎 [提 Issue](https://github.com/minghaoran0910-cyber/silentbook/issues) 讨论。*
