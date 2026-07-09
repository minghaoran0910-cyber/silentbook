# SilentBook 资产管理模块设计

## 数据模型

### Asset（资产）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| name | str | 资产名称（如"招商银行储蓄卡"） |
| asset_type | str | 类型：cash/savings/fund/stock/bond/property/other |
| account | str | 所属机构 |
| current_value | float | 当前价值 |
| initial_value | float | 初始投入 |
| currency | str | 币种（默认CNY） |
| liquidity | str | 流动性：high/medium/low |
| status | str | 状态：active/frozen/closed |
| notes | str | 备注 |
| updated_at | datetime | 最后更新时间 |

### Liability（负债）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| name | str | 负债名称（如"京东白条"） |
| liability_type | str | 类型：credit_card/loan/mortgage/other |
| total_amount | float | 总额 |
| current_amount | float | 当前待还 |
| interest_rate | float | 利率 |
| due_date | date | 到期日 |
| status | str | 状态：active/paid/overdue |
| notes | str | 备注 |
| updated_at | datetime | 最后更新时间 |

## 页面

### /assets 页面
- 资产总览卡片（总资产、总负债、净资产）
- 资产列表（可编辑）
- 负债列表（可编辑）
- 添加资产/负债表单
- 资产分类饼图（用 CSS 简单实现）

### 首页更新
- 净资产 = 总资产 - 总负债
- 统计卡片加上"总资产""总负债"
