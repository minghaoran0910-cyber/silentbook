# Tauri v2 桌面打包方案（mac-dmg / Windows-exe）

> 状态：方案已验证可行，未开工。结论先行：**mac-dmg 可达，exe 需 Windows/CI 矩阵验证**。
> 预计总工作量 16–26 小时。桌面 v1 范围：后端(SQLite)+前端静态+本地定时，
> 不含 agent/parser 本地服务（走远程可配地址，无 Key 自动降级）。

## 1. 路线（唯一推荐）

- 前端：Tauri profile 切 `ssr: false` + `nuxt generate`，`frontendDist: ../dist`。
  Tauri 只 serve 静态文件，`server/api/[...path].ts` Nitro 代理在包里**永不执行**，
  前端改直连 `http://127.0.0.1:<port>`（`getApiBase()` 加 `window.__TAURI__` 分支，
  Docker/Web 行为不动）。
- 后端：PyInstaller `--onefile` 单文件 sidecar（mac-arm64 成熟），
  `tauri.conf.json:bundle.externalBin` 拉起，`--workers 1`（SQLite 写锁），
  `DATABASE_URL` 指到 Tauri `appDataDir`（如 `~/Library/Application Support/...`）。
- 精简 sidecar 依赖（去 `asyncpg/psycopg2-binary/redis`，已有 fail-open 与文档兜底）。

## 2. 必须改的点（按文件）

1. `frontend/nuxt.config.ts`：Tauri profile（ssr 关、pwa 关、generate 到 dist）。
   PWA 必须关：workbox 会把失败 API 缓存 5 分钟+ SW 在 webview 下行为异常。
2. `frontend/utils/api.ts`：`getApiBase()` 加 Tauri 分支；收敛散落的
   `fetch('/api/...')`（`assets.vue`、auth 相关页、`useAuth.ts`）到统一出口。
3. `backend/app/routers/deps.py`：`ALLOWED_ORIGINS` 默认追加
   `tauri://localhost`、`http://tauri.localhost`、`http://127.0.0.1:1420`。
4. `backend/app/main.py`：CORS + `security_headers_middleware` 的 Origin 检查 +
   CSP `connect-src` 三处同步放行（建议 `DESKTOP=1` 环境开关控制）。
5. `backend/app/auth.py`：审计 Cookie（SameSite/Secure）在 webview 下的行为，
   以 `tauri://localhost → http://127.0.0.1` 实测登录态为准（P0 验证项）。
6. 新增：`src-tauri/`（配置+`main.rs` 拉起/健康等待/优雅退出）、
   `backend/sidecar_main.py`（`--port` 参数入口）、构建脚本、
   `.gitignore`（target/binaries/dist/*.db）。
7. 审计 `frontend/server/plugins/*` 是否藏 auth/代理逻辑（SPA 下 Nitro 插件失效）。

## 3. 分阶段与验证标准

- P0 前端静态化（1–2h）：`generate` 产物无服务端引用，静态服务器能渲染登录页。
- P1 后端桌面启动（2–3h）：动态端口 + CORS/403/登录态三项全过。
- P2 单文件 sidecar（3–5h）：干净目录双击运行，记账重启不丢。
- P3 Tauri 联调（4–6h，需装 Rust）：登录→记账→重启保持；杀进程无残留。
- P4 打包分发（3–6h）：mac-dmg 需 Apple 签名+notarization（以天计）；exe 必须上 CI 矩阵，**本机无法验证**。

## 4. 风险清单

- Cookie 跨 `tauri://` 失效（P1 必测，不行就降级 Authorization header）。
- 单文件首启解压慢（10–30s，要 splash + 健康重试）。
- 端口写死会撞车，必须动态端口。
- agent/parser 不进 v1 包（复杂度翻倍），AI 走远程或降级，报错文案要处理。

## 5. 今晚没做的事（诚实）

本机无 Rust 工具链，`tauri dev/build` 一步都没跑；dmg/exe 零产出；
体积数字全是估计（60–120MB 解压后）。要开工先装 Rust 再按 P0→P4 走。
