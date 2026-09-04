-- 账户命名空间统一：历史数据里手动录入的平台标识（cmb/wechat_pay…）
-- 回填为中文名，与解析器/新入库一致。执行前请先备份。
-- 适用于 SQLite 与 PostgreSQL。

UPDATE transactions SET account = '招商银行' WHERE account = 'cmb';
UPDATE transactions SET account = '工商银行' WHERE account = 'icbc';
UPDATE transactions SET account = '建设银行' WHERE account = 'ccb';
UPDATE transactions SET account = '农业银行' WHERE account = 'abc';
UPDATE transactions SET account = '中国银行' WHERE account = 'boc';
UPDATE transactions SET account = '交通银行' WHERE account = 'bocom';
UPDATE transactions SET account = '浦发银行' WHERE account = 'spdb';
UPDATE transactions SET account = '光大银行' WHERE account = 'ceb';
UPDATE transactions SET account = '中信银行' WHERE account = 'citic';
UPDATE transactions SET account = '云闪付' WHERE account = 'unionpay';
UPDATE transactions SET account = '支付宝' WHERE account = 'alipay';
UPDATE transactions SET account = '微信' WHERE account IN ('wechat_pay', 'wechat');
UPDATE transactions SET account = '美团' WHERE account = 'meituan';
UPDATE transactions SET account = '京东' WHERE account = 'jd';
UPDATE transactions SET account = '淘宝' WHERE account = 'taobao';
UPDATE transactions SET account = '现金' WHERE account = 'cash';

-- 验证：应返回 0 行（无残留平台标识）
-- SELECT DISTINCT account FROM transactions
--   WHERE account IN ('cmb','icbc','ccb','abc','boc','bocom','spdb','ceb',
--     'citic','unionpay','alipay','wechat_pay','wechat','meituan','jd',
--     'taobao','cash');
