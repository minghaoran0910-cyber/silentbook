-- SilentBook webhook 业务幂等：webhook_events 加 body_hash 列
-- 部署顺序（重要）：先执行本 SQL，再部署新代码。
-- 新代码在缺列的旧库上会自动降级（跳过去重、记 warning 日志），不会丢数据；
-- 但去重要等本迁移执行后才生效。
-- 全新安装无需执行（create_all 已包含该列）。

-- PostgreSQL（生产）：
ALTER TABLE webhook_events ADD COLUMN IF NOT EXISTS body_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_user_body
    ON webhook_events (user_id, body_hash);

-- SQLite（lite 模式，存量单文件）：
-- ALTER TABLE webhook_events ADD COLUMN body_hash VARCHAR(64);
-- CREATE UNIQUE INDEX uq_webhook_events_user_body
--     ON webhook_events (user_id, body_hash);
