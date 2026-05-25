# zz-wcl-analyzer

基于 Warcraft Logs API 的魔兽世界大秘境日志本地查询分析工具。

从 [wcl-analyzer](https://github.com/qumuq2/wcl-analyzer) 改造而来，去掉部署相关代码，专注于本地直接查询和分析。

## 与原项目的区别

| | wcl-analyzer | zz-wcl-analyzer |
|---|---|---|
| 定位 | 部署为Web API服务 | 本地直接运行的查询分析工具 |
| HTTP库 | async/httpx (异步) | sync/requests (同步) |
| 使用方式 | curl/API调用 | python脚本命令行 |
| 部署 | 需要(Vercel/Render/Cloudflare) | 不需要，直接运行 |
| 新增功能 | - | 专精识别、Boss阶段检测、事件级承伤分析 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

WCL API凭证默认已内置，也可以通过环境变量覆盖：

```bash
export WCL_CLIENT_ID="your-client-id"
export WCL_CLIENT_SECRET="your-client-secret"
```

## 使用

### 1. 查询区域和副本信息

```bash
# 列出所有区域
python scripts/check_zones.py

# 查看指定区域的遭遇(副本)
python scripts/check_zones.py --zone 47
```

### 2. 搜索大秘境报告

```bash
# 搜索近3天所有M+报告
python scripts/search_reports.py

# 只看萨隆矿坑20层
python scripts/search_reports.py --encounter 10658 --level 20

# 只看有守护德的报告
python scripts/search_reports.py --spec Guardian
```

### 3. 查找特定坦克的通关记录

```bash
# 默认：萨隆矿坑 + 熊坦 + 近3天
python scripts/find_tank_runs.py

# 20层以上
python scripts/find_tank_runs.py --level 20

# 查防骑的记录
python scripts/find_tank_runs.py --spec Protection
```

### 4. 分析坦克承伤

```bash
# 查看报告中的玩家列表（确定坦克ID）
python scripts/analyze_tank.py --code cAkFBvnmDKrChNTd --list-players

# 分析单场战斗
python scripts/analyze_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank 1 --boss-damage --trash-damage

# 只看Boss 1承伤
python scripts/analyze_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank 1 --boss-only 1

# 从find_tank_runs的输出批量分析
python scripts/analyze_tank.py --from-json tank_runs.json --boss-damage --trash-damage
```

### 5. 端到端示例

```bash
# 自动搜索+分析萨隆矿坑熊坦
python examples/pos_bear_tank.py

# 指定层数和时间范围
python examples/pos_bear_tank.py --days 7 --level 20

# 直接分析指定报告
python examples/pos_bear_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank-id 1
```

## 代码结构

```
zz-wcl-analyzer/
├── wcl_analyzer/              # 核心库
│   ├── config.py              # 配置：API凭证、常量映射、副本/Boss/技能ID
│   ├── client.py              # WCL API客户端：OAuth认证、GraphQL查询、自动翻页
│   ├── analyzer.py            # 分析逻辑：承伤统计、Boss阶段检测、CD分析
│   └── utils.py               # 工具函数：专精识别、事件过滤、Boss阶段划分
├── scripts/                   # 命令行脚本
│   ├── check_zones.py         # 查询区域/副本信息
│   ├── search_reports.py      # 搜索报告
│   ├── find_tank_runs.py      # 查找坦克通关记录
│   └── analyze_tank.py        # 分析坦克承伤
├── examples/                  # 端到端示例
│   └── pos_bear_tank.py       # 萨隆矿坑熊坦分析示例
├── requirements.txt
└── README.md
```

## 关键经验（踩坑记录）

### 1. 专精识别必须用icon字段，不能用subType

WCL的`masterData.actors`中，`subType`字段大部分显示`"Unknown"`，不可靠。正确做法是使用`icon`字段，例如：
- `"Druid-Guardian"` = 熊坦
- `"Warrior-Protection"` = 防战
- `"Paladin-Protection"` = 防骑

### 2. Events API必须用fightIDs参数

WCL Events API用`startTime`/`endTime`绝对时间参数会返回0结果，必须使用`fightIDs`参数。事件的`timestamp`是相对于报告`startTime`的偏移量。

### 3. targetID过滤无效，需客户端过滤

Events API的`targetID`参数服务端过滤无效（返回0结果），必须获取全部事件后在客户端用`targetID`字段过滤。

### 4. Boss阶段划分方法

通过匹配伤害事件中`sourceID`对应的Boss名称，取各Boss伤害事件的min/max时间戳作为时间窗口边界，窗口间即为小怪阶段。

### 5. table返回的数据可能是字符串化JSON

WCL的`table` API有时返回字符串化的JSON而非对象，需要兼容两种格式：先尝试`json.loads`，再检查是否有`data`字段。

### 6. reports查询不支持encounterID参数

虽然GraphQL schema中`reports`查询有`encounterID`参数，但实际使用时似乎不起作用，需要在获取报告后逐个检查fights。

## 扩展到其他副本

本项目默认配置了萨隆矿坑的Boss和技能映射，扩展到其他副本只需：

1. 在`config.py`中添加副本的Boss名称映射
2. 在`config.py`中添加Boss技能ID映射
3. 分析时传入对应的`boss_names`和`skill_map`参数

示例：
```python
from wcl_analyzer.client import WCLClient
from wcl_analyzer.analyzer import analyze_full_tank_run

client = WCLClient()

# 自定义Boss名称映射
my_dungeon_bosses = {
    "Boss中文名1": 1,
    "Boss中文名2": 2,
    "Boss中文名3": 3,
}

result = analyze_full_tank_run(
    client, code, fight_id, tank_id, tank_name,
    boss_names=my_dungeon_bosses,
)
```
