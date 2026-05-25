"""WCL Analyzer 工具函数

从实际查询中总结的辅助功能：
- 专精识别：WCL的subType大部分为"Unknown"，必须用icon字段
- Boss阶段检测：通过Boss名称在伤害事件中的出现时间窗口划分
- 事件过滤：targetID服务端过滤无效，需客户端过滤
- 技能ID映射
"""

from collections import defaultdict
from .config import TANK_SPECS, SPEC_MAP, PIT_OF_SARON_BOSSES, DAMAGE_TYPE_MAP, HIT_TYPE_MAP


# ===== 专精识别 =====

def identify_spec(actor):
    """从masterData的actor识别专精

    WCL的subType字段大部分显示"Unknown"不可靠，
    正确做法是使用icon字段（如 "Druid-Guardian" 识别熊坦）。

    Args:
        actor: masterData.actors中的单个actor对象

    Returns:
        (spec_cn, is_tank) 专精中文名和是否坦克
    """
    icon = actor.get("icon", "")
    spec_cn = SPEC_MAP.get(icon, None)
    is_tank = icon in TANK_SPECS

    # 如果icon匹配不到，尝试subType兜底
    if not spec_cn:
        sub = actor.get("subType", "")
        if sub and sub != "Unknown":
            spec_cn = sub

    return spec_cn, is_tank


def find_tank_actors(actors):
    """从actor列表中找出所有坦克

    Args:
        actors: masterData.actors列表

    Returns:
        坦克actor列表，每个元素附带 spec_cn 和 is_tank
    """
    tanks = []
    for actor in actors:
        if actor.get("type") != "Player":
            continue
        spec_cn, is_tank = identify_spec(actor)
        if is_tank:
            tanks.append({
                **actor,
                "spec_cn": spec_cn,
                "is_tank": True,
            })
    return tanks


def find_players_by_spec(actors, spec_keyword):
    """从actor列表中按专精关键词查找玩家

    Args:
        actors: masterData.actors列表
        spec_keyword: icon中的关键词，如 "Guardian"、"Protection"

    Returns:
        匹配的player actor列表
    """
    results = []
    for actor in actors:
        if actor.get("type") != "Player":
            continue
        icon = actor.get("icon", "")
        if spec_keyword.lower() in icon.lower():
            spec_cn, is_tank = identify_spec(actor)
            results.append({
                **actor,
                "spec_cn": spec_cn,
                "is_tank": is_tank,
            })
    return results


# ===== 事件过滤 =====

def filter_events_by_target(events, target_id):
    """客户端过滤：按targetID过滤事件

    WCL API的targetID参数服务端过滤无效（返回0结果），
    必须获取全部事件后在客户端过滤。

    Args:
        events: get_all_events返回的事件列表
        target_id: 目标actor ID

    Returns:
        过滤后的事件列表
    """
    return [e for e in events if e.get("targetID") == target_id]


def filter_events_by_source(events, source_id):
    """客户端过滤：按sourceID过滤事件"""
    return [e for e in events if e.get("sourceID") == source_id]


def filter_events_by_time(events, start_time, end_time):
    """客户端过滤：按时间范围过滤事件

    Args:
        events: 事件列表
        start_time: 起始时间（相对偏移量ms）
        end_time: 结束时间（相对偏移量ms）
    """
    return [e for e in events if start_time <= e.get("timestamp", 0) < end_time]


# ===== Boss阶段检测 =====

def detect_boss_phases(events, actor_name_map, boss_names=None):
    """通过Boss名称在伤害事件中的出现时间窗口检测Boss阶段

    原理：Boss的伤害事件在时间轴上形成连续窗口，
    窗口之间即为小怪阶段。

    Args:
        events: DamageTaken事件列表（已过滤到特定目标）
        actor_name_map: {actor_id: actor_name} 映射
        boss_names: Boss名称字典 {boss_name: boss_number}
                    默认使用萨隆矿坑的Boss

    Returns:
        {
            "boss_phases": [{"boss": name, "start": ms, "end": ms, "number": int}],
            "trash_phases": [{"start": ms, "end": ms, "after_boss": int}],
        }
    """
    if boss_names is None:
        boss_names = PIT_OF_SARON_BOSSES

    # 按来源分组，找出Boss的伤害时间窗口
    source_events = defaultdict(list)
    for e in events:
        source_id = e.get("sourceID", 0)
        source_name = actor_name_map.get(source_id, f"NPC-{source_id}")
        source_events[source_name].append(e.get("timestamp", 0))

    boss_phases = []
    for boss_name, boss_number in boss_names.items():
        if boss_name in source_events and source_events[boss_name]:
            timestamps = source_events[boss_name]
            boss_phases.append({
                "boss": boss_name,
                "number": boss_number,
                "start": min(timestamps),
                "end": max(timestamps),
            })

    # 按开始时间排序
    boss_phases.sort(key=lambda x: x["start"])

    # 推导小怪阶段：Boss之间的间隔
    trash_phases = []
    for i in range(len(boss_phases) - 1):
        current_boss_end = boss_phases[i]["end"]
        next_boss_start = boss_phases[i + 1]["start"]
        if next_boss_start > current_boss_end:
            trash_phases.append({
                "start": current_boss_end,
                "end": next_boss_start,
                "after_boss": boss_phases[i]["number"],
                "before_boss": boss_phases[i + 1]["number"],
            })

    return {
        "boss_phases": boss_phases,
        "trash_phases": trash_phases,
    }


# ===== 伤害统计 =====

def calculate_damage_taken_stats(events, actor_name_map=None):
    """计算承伤统计

    Args:
        events: DamageTaken事件列表（已过滤到特定目标）
        actor_name_map: 可选，用于将sourceID映射为名称

    Returns:
        {
            "total": 总承伤,
            "raw": 实际掉血,
            "mitigated": 减伤量,
            "absorbed": 吸收量,
            "unmitigated": 未减免伤害,
            "mitigation_rate": 减伤率,
            "by_source": {来源: 伤害},
            "by_ability": {技能ID: 伤害},
            "by_hit_type": {命中类型: 次数},
            "hit_count": 命中次数,
        }
    """
    total = 0
    raw = 0
    mitigated = 0
    absorbed = 0
    unmitigated = 0
    by_source = defaultdict(int)
    by_ability = defaultdict(int)
    by_hit_type = defaultdict(int)

    for e in events:
        amount = e.get("amount", 0)
        mit = e.get("mitigated", 0)
        abs_amt = e.get("absorbed", 0)
        unmit = e.get("unmitigatedAmount", 0)
        hit_type = e.get("hitType", 1)
        ability_id = e.get("abilityGameID", 0)
        source_id = e.get("sourceID", 0)

        event_total = amount + mit
        total += event_total
        raw += amount
        mitigated += mit
        absorbed += abs_amt
        unmitigated += unmit

        if actor_name_map:
            source_name = actor_name_map.get(source_id, f"NPC-{source_id}")
            by_source[source_name] += event_total
        else:
            by_source[source_id] += event_total

        by_ability[ability_id] += event_total
        by_hit_type[hit_type] += 1

    mitigation_rate = mitigated / max(unmitigated, 1) * 100

    return {
        "total": total,
        "raw": raw,
        "mitigated": mitigated,
        "absorbed": absorbed,
        "unmitigated": unmitigated,
        "mitigation_rate": mitigation_rate,
        "by_source": dict(by_source),
        "by_ability": dict(by_ability),
        "by_hit_type": dict(by_hit_type),
        "hit_count": len(events),
    }


def build_actor_maps(master_data):
    """从masterData构建各种映射表

    Args:
        master_data: get_master_data()的返回值

    Returns:
        (actor_name_map, actor_icon_map, ability_map)
        - actor_name_map: {id: name}
        - actor_icon_map: {id: icon}
        - ability_map: {gameID: ability_info}
    """
    actors = master_data.get("actors", [])
    abilities = master_data.get("abilities", [])

    actor_name_map = {a["id"]: a["name"] for a in actors}
    actor_icon_map = {a["id"]: a.get("icon", "") for a in actors}
    ability_map = {a["gameID"]: a for a in abilities}

    return actor_name_map, actor_icon_map, ability_map


# ===== 时间格式化 =====

def format_duration(ms):
    """将毫秒时间差格式化为可读字符串"""
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m{secs:.0f}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins}m"


def format_dps(damage, duration_ms):
    """计算并格式化DPS"""
    if duration_ms <= 0:
        return "0/s"
    dps = damage / (duration_ms / 1000)
    if dps >= 1_000_000:
        return f"{dps/1_000_000:.1f}M/s"
    elif dps >= 1_000:
        return f"{dps/1_000:.1f}K/s"
    else:
        return f"{dps:.0f}/s"


def format_number(n):
    """格式化数字，添加千位分隔符"""
    return f"{n:,}"
