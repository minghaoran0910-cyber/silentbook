"""
V2-029: 数据库索引优化迁移脚本

添加索引列表：
- transactions: category, account, transaction_type, parsed_at + 3个复合索引
- assets: asset_type, status
- liabilities: liability_type, status
- accounts: purpose, status
- transfers: created_at
- analysis_results: analysis_type, created_at
- positions: position_type, status
- trade_records: trade_type, trade_date
- financial_goals: goal_type, status
- recurring_transactions: category, transaction_type, is_active
- backup_records: status, created_at

使用方式：
    python migrations/add_indexes.py

支持 SQLite 和 PostgreSQL。
"""

import os
import sys

# 添加 app 到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from sqlalchemy import text, inspect
from database import engine, Base


def get_existing_indexes(conn):
    """获取数据库中已存在的索引"""
    inspector = inspect(engine)
    existing = set()
    for table_name in inspector.get_table_names():
        for idx in inspector.get_indexes(table_name):
            existing.add(idx['name'])
    return existing


def add_indexes_sqlite():
    """SQLite 索引添加（CREATE INDEX IF NOT EXISTS）"""
    indexes = [
        # Transaction 表
        "CREATE INDEX IF NOT EXISTS ix_transactions_category ON transactions(category)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_account ON transactions(account)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_transaction_type ON transactions(transaction_type)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_parsed_at ON transactions(parsed_at)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_type_parsed ON transactions(transaction_type, parsed_at)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_category_parsed ON transactions(category, parsed_at)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_account_parsed ON transactions(account, parsed_at)",
        
        # Asset 表
        "CREATE INDEX IF NOT EXISTS ix_assets_asset_type ON assets(asset_type)",
        "CREATE INDEX IF NOT EXISTS ix_assets_status ON assets(status)",
        
        # Liability 表
        "CREATE INDEX IF NOT EXISTS ix_liabilities_liability_type ON liabilities(liability_type)",
        "CREATE INDEX IF NOT EXISTS ix_liabilities_status ON liabilities(status)",
        
        # Account 表
        "CREATE INDEX IF NOT EXISTS ix_accounts_purpose ON accounts(purpose)",
        "CREATE INDEX IF NOT EXISTS ix_accounts_status ON accounts(status)",
        
        # Transfer 表
        "CREATE INDEX IF NOT EXISTS ix_transfers_created_at ON transfers(created_at)",
        
        # AnalysisResult 表
        "CREATE INDEX IF NOT EXISTS ix_analysis_results_analysis_type ON analysis_results(analysis_type)",
        "CREATE INDEX IF NOT EXISTS ix_analysis_results_created_at ON analysis_results(created_at)",
        
        # Position 表
        "CREATE INDEX IF NOT EXISTS ix_positions_position_type ON positions(position_type)",
        "CREATE INDEX IF NOT EXISTS ix_positions_status ON positions(status)",
        
        # TradeRecord 表
        "CREATE INDEX IF NOT EXISTS ix_trade_records_trade_type ON trade_records(trade_type)",
        "CREATE INDEX IF NOT EXISTS ix_trade_records_trade_date ON trade_records(trade_date)",
        
        # FinancialGoal 表
        "CREATE INDEX IF NOT EXISTS ix_financial_goals_goal_type ON financial_goals(goal_type)",
        "CREATE INDEX IF NOT EXISTS ix_financial_goals_status ON financial_goals(status)",
        
        # RecurringTransaction 表
        "CREATE INDEX IF NOT EXISTS ix_recurring_transactions_category ON recurring_transactions(category)",
        "CREATE INDEX IF NOT EXISTS ix_recurring_transactions_transaction_type ON recurring_transactions(transaction_type)",
        "CREATE INDEX IF NOT EXISTS ix_recurring_transactions_is_active ON recurring_transactions(is_active)",
        
        # BackupRecord 表
        "CREATE INDEX IF NOT EXISTS ix_backup_records_status ON backup_records(status)",
        "CREATE INDEX IF NOT EXISTS ix_backup_records_created_at ON backup_records(created_at)",
    ]
    
    with engine.connect() as conn:
        for sql in indexes:
            try:
                conn.execute(text(sql))
                # 提取索引名
                idx_name = sql.split("IF NOT EXISTS ")[1].split(" ON")[0]
                print(f"  ✅ {idx_name}")
            except Exception as e:
                idx_name = sql.split("IF NOT EXISTS ")[1].split(" ON")[0]
                print(f"  ⚠️  {idx_name}: {e}")
        conn.commit()


def verify_indexes():
    """验证索引是否创建成功"""
    inspector = inspect(engine)
    total_indexes = 0
    print("\n📊 索引统计：")
    print("-" * 50)
    
    for table_name in sorted(inspector.get_table_names()):
        indexes = inspector.get_indexes(table_name)
        # 排除自动创建的主键索引
        user_indexes = [idx for idx in indexes if not idx['name'].startswith('pk_') and idx['name'] != 'sqlite_autoindex_' + table_name + '_1']
        if user_indexes:
            total_indexes += len(user_indexes)
            print(f"  {table_name}: {len(user_indexes)} 个索引")
            for idx in sorted(user_indexes, key=lambda x: x['name']):
                cols = ', '.join(idx['column_names'])
                unique = " (UNIQUE)" if idx['unique'] else ""
                print(f"    - {idx['name']}: [{cols}]{unique}")
    
    print("-" * 50)
    print(f"  总计: {total_indexes} 个用户索引")
    return total_indexes


def main():
    print("🔧 V2-029 数据库索引优化迁移")
    print("=" * 50)
    print(f"数据库: {engine.url}")
    print()
    
    print("📝 添加索引...")
    add_indexes_sqlite()
    
    print()
    verify_indexes()
    
    print("\n✅ 迁移完成！")


if __name__ == "__main__":
    main()
