# polymarket-mm

Polymarket 流动性奖励做市机器人。默认**模拟盘**，真钱模式要显式打开。

## 它赚的是什么钱

Polymarket 每天给「挂在中间价附近的限价单」发 USDC 奖励（Liquidity Rewards）。
每分钟随机抽样一次，按每个人挂单的分数 Q 占比分奖金池，隔天 UTC 零点结算，单日不足 $1 不发。

- 分数公式：`S = ((v - s) / v)^2 * size`，v 是该市场的最大价差，s 是你离中间价的距离
- 双边挂单才拿全分，单边除以 3；中间价在 0.10 以下或 0.90 以上时只认双边
- 挂单方不收手续费，只有吃单方付

机器人做的事：从所有发奖励的市场里挑「奖金池大、对手挂单少、价格不乱跳」的，
在中间价上下各挂一笔买单（买 YES + 买 NO，等价于双边报价），价格一动就撤单重挂。

风险在于**被成交**：挂单被人吃掉后你就持有仓位，价格继续往不利方向走就亏钱。
奖励是确定的小钱，仓位亏损是不确定的大钱。所以资金上限、单市场上限、库存上限、日亏损熔断全部写死在 `pmm/config.py`。

## 安装

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

## 三种运行方式

```bash
python -m pmm.bot scan            # 只看：当前最值得挂单的市场排名，不下单
python -m pmm.bot paper --hours 8 # 模拟盘：用真实盘口模拟成交和奖励，写到 data/
python -m pmm.bot live  --hours 8 # 真钱，见下
```

模拟盘输出：`data/paper_log.csv` 每 30 秒一行，`data/paper_state.json` 当前持仓和累计奖励估算。
结束时打印汇总：`reward_est`（估算奖励）、`fills`（被成交次数）、`inventory_cost`（持仓成本）、`halted`（是否触发熔断）。

模拟盘的两条保守假设：
1. 挂单只有在盘口或成交记录**穿过**我们的价格时才算成交（排队靠前的乐观假设不采用）
2. 奖励份额最多按 50% 算（`max_share`），因为我们一挂，别的机器人也会来

## 真钱模式前提

1. 开户：polymarket.com 用邮箱或 Google 注册。2026 年 5 月后的新账户是 Deposit Wallet，新版 SDK `polymarket-client` 直接支持，**不要用旧的 py-clob-client**（对邮箱账户已失效）。
2. 地区：注册时它会自动检查。被封的 39 国包括美国、英国、法国、德国、日本、新加坡、台湾、泰国、澳大利亚等，完整名单见 help.polymarket.com「Geographic Restrictions」。禁止 VPN 绕过（ToS 2.1.4），违者冻结资金。
3. 充值：Deposit → 银行卡（MoonPay，最低约 $20）或从交易所提 USDC 到 Polygon 网络（最低 $2，一分钟到账）。
4. 导出私钥：Settings → Private Key → Start Export。这把钥匙等于账户里全部的钱。
5. 新开一个**专用账户**只放愿意全亏的钱，再把钥匙交给机器人。

环境变量（放在运行机器的 `.env` 或云环境设置里，**永远不要贴进聊天**）：

```
POLY_PRIVATE_KEY=0x...                 # 导出的私钥
POLY_WALLET=0x...                      # Polymarket 页面上显示的钱包地址
PMM_I_UNDERSTAND_REAL_MONEY=1          # 不设这个 live 直接拒绝启动
PMM_TOTAL_CAPITAL=100                  # 可选，覆盖默认上限
```

live 模式退出时（Ctrl-C 或到时）会撤掉所有挂单。它**没有在真实账户上跑过**，第一次请用 `PMM_TOTAL_CAPITAL=20` 并盯着看。

## 参数（pmm/config.py）

| 参数 | 默认 | 含义 |
|---|---|---|
| total_capital | 100 | 全部市场合计最多占用的 USDC |
| capital_per_market | 40 | 单市场两边合计 |
| max_markets | 3 | 同时做几个市场 |
| max_inventory_usd | 30 | 某一边持仓超过这个值就停挂那一边 |
| daily_loss_limit | 5 | 浮亏超过就全撤单停机 |
| quote_offset_frac | 0.5 | 挂单离中间价的距离，占最大价差的比例（0.5 → 分数 0.25） |
| max_share | 0.5 | 估算奖励时假设的份额上限 |
| max_book_spread_frac | 3.0 | 盘口价差超过最大价差的 3 倍就跳过（中间价不可信） |
| exclude_sports | true | 跳过体育盘（比赛中价格跳变） |
| max_hourly_jump | 0.10 | 过去一周任何一小时价格跳变超过 10 美分的市场跳过（新闻盘会把挂单打穿） |
| market_loss_limit | 3 | 单个市场浮亏超过就只停这个市场 |

## 回滚

本分支是孤儿分支，和网站代码零交集。不要了就 `git branch -D polymarket-mm`。

## 2026-10-01 模拟盘记录（三轮，共 12 小时采样）

| 轮次 | 采样 | 奖励估算 | 持仓浮盈亏 | 最大回撤 | 熔断 | 说明 |
|---|---|---|---|---|---|---|
| 1 | 2.0h | 0.70 | +0.57 | -7.6 | 14 分钟触发 | Haiku 发布市场一笔成交后跳 20 美分 |
| 2 | 1.8h | 0.93 | -1.50 | -5.2 | 触发 | AI czar 市场 30 秒内从 0.31 跳到 0.50 |
| 3 | 8.1h | 6.82 | +6.50 | -1.9 | 无 | 加了一周跳变过滤后，三个市场无一被打穿 |

第三轮的奖励按小时看：前两小时各 2.1，之后每小时 0.2 到 0.6。空着的奖励带两小时内就会有别的机器人跟进。
按稳态估，100 美元资金每天奖励约 8 到 12 美元（已按份额上限 50% 打折，真实到账只会更少）；一次新闻跳变就能亏掉一到两天。

已知待改：库存上限只在挂单时检查，连续两次成交可把单市场持仓推到 47 美元（设定 40）。应按剩余额度定单量。
