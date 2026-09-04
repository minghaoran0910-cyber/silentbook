-- 修复非法 transaction_type：响应模型只接受 income/expense，
-- 历史导入的 transfer（及未来可能的脏值）会导致整表查询 500。
-- 经核查存量 transfer 行全为资金流出（社保/投资/还款/自动攒），统一修成 expense。
-- 先备份再执行。

UPDATE transactions SET transaction_type = 'expense'
WHERE transaction_type NOT IN ('income', 'expense');

-- 验证：应返回 0 行
-- SELECT transaction_type, count(*) FROM transactions
--  GROUP BY transaction_type;
