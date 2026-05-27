"""WCL Analyzer 工具函数

从实际查询中总结的辅助功能：
- 专精识别：WCL的subType大部分为"Unknown"，必须用icon字段
- Boss阶段检测：通过Boss名称在伤害事件中的出现时间窗口划分
- 事件过滤：targetID服务端过滤无效，需客户端过滤
- 伤害类型解码：WCL使用位掩码表示伤害类型
- 技能维度统计：按技能聚合，含攻击间隔分析
"""

from collections import defaultdict
from .config import TANK_SPECS, SPEC_MAP, PIT_OF_SARON_BOSSES, DAMAGE_TYPE_BITMASK


# ===== 伤害类型解码 =====

def decode_damage_type(type_value):
    """将WCL的伤害类型位掩码解码为中文名称列表

    WCL的abilities.type字段是位掩码：
    - 单一类型：1=物理, 16=冰霜, 32=暗影 等
    - 组合类型：12=火焰+自然(4+8), 48=冰霜+暗影(16+32) 等

    Args:
        type_value: WCL返回的type值（可能是字符串或整数）

    Returns:
        伤害类型名称列表，如 ["物理"] 或 ["火焰", "自然"]
    """
    try:
        t = int(type_value)
    except (TypeError, ValueError):
        return ["未知"]

    if t == 0:
        return ["无类型"]

    types = []
    for bit, name in sorted(DAMAGE_TYPE_BITMASK.items()):
        if t & bit:
            types.append(name)

    return types if types else [f"未知({t})"]


def format_damage_type(type_value):
    """将伤害类型位掩码格式化为可读字符串

    Args:
        type_value: WCL返回的type值

    Returns:
        如 "物理" 或 "火焰|自然"
    """
    types = decode_damage_type(type_value)
    return "|".join(types)


# ===== 专精识别 =====

def identify_spec(actor):
    """从masterData的actor识别专精

    WCL的subType字段大部分显示"Unknown"不可靠，
    正确做法是使用icon字段（如 "Druid-Guardian" 识别熊坦）。
    """
    icon = actor.get("icon", "")
    spec_cn = SPEC_MAP.get(icon, None)
    is_tank = icon in TANK_SPECS

    if not spec_cn:
        sub = actor.get("subType", "")
        if sub and sub != "Unknown":
            spec_cn = sub

    return spec_cn, is_tank


def find_tank_actors(actors):
    """从actor列表中找出所有坦克"""
    tanks = []
    for actor in actors:
        if actor.get("type") != "Player":
            continue
        spec_cn, is_tank = identify_spec(actor)
        if is_tank:
            tanks.append({**actor, "spec_cn": spec_cn, "is_tank": True})
    return tanks


def find_players_by_spec(actors, spec_keyword):
    """从actor列表中按专精关键词查找玩家"""
    results = []
    for actor in actors:
        if actor.get("type") != "Player":
            continue
        icon = actor.get("icon", "")
        if spec_keyword.lower() in icon.lower():
            spec_cn, is_tank = identify_spec(actor)
            results.append({**actor, "spec_cn": spec_cn, "is_tank": is_tank})
    return results


# ===== 事件过滤 =====

def filter_events_by_target(events, target_id):
    """客户端过滤：按targetID过滤事件（WCL API的targetID参数无效）"""
    return [e for e in events if e.get("targetID") == target_id]

def filter_events_by_source(events, source_id):
    """客户端过滤：按sourceID过滤事件"""
    return [e for e in events if e.get("sourceID") == source_id]

def filter_events_by_time(events, start_time, end_time):
    """客户端过滤：按时间范围过滤事件"""
    return [e for e in events if start_time <= e.get("timestamp", 0) <= end_time]


# ===== Boss阶段检测 =====

def detect_boss_phases(events, actor_name_map, boss_names=None):
    """通过Boss名称在伤害事件中的出现时间窗口检测Boss阶段"""
    if boss_names is None:
        boss_names = PIT_OF_SARON_BOSSES

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

    boss_phases.sort(key=lambda x: x["start"])

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

    return {"boss_phases": boss_phases, "trash_phases": trash_phases}


# ===== 伤害统计 =====

def calculate_damage_taken_stats(events, actor_name_map=None):
    """计算承伤统计"""
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


# ===== 技能维度统计 =====

def analyze_skills(events, actor_name_map, ability_type_map, ability_map=None):
    """按技能维度分析承伤，包含伤害类型、攻击间隔等

    Args:
        events: DamageTaken事件列表（已过滤到特定目标+特定时间段）
        actor_name_map: {actor_id: actor_name} 映射
        ability_type_map: {ability_game_id: type_value} 映射（从masterData获取）
        ability_map: {ability_game_id: ability_info} 映射（可选，用于获取技能名）

    Returns:
        按来源+技能分组的分析结果列表，每个技能包含：
        - 来源名称
        - 技能名称/ID
        - 伤害类型（中文）
        - 总伤害、命中次数
        - max_unmitigated: 单次最大（减免前）
        - max_amount: 单次最大（减免后/实际承伤）
        - avg_amount: 单次平均（减免后/实际承伤）
        - 攻击间隔统计
        - 攻击模式判断
    """
    # 按(source_id, ability_id)分组
    grouped = defaultdict(list)
    for e in events:
        source_id = e.get("sourceID", 0)
        ability_id = e.get("abilityGameID", 0)
        grouped[(source_id, ability_id)].append(e)

    results = []
    for (source_id, ability_id), evts in grouped.items():
        evts_sorted = sorted(evts, key=lambda e: e.get("timestamp", 0))

        source_name = actor_name_map.get(source_id, f"NPC-{source_id}")

        # 技能名称：从ability_map获取，没有则显示ID
        if ability_map and ability_id in ability_map:
            ability_name = ability_map[ability_id].get("name", f"技能{ability_id}")
        else:
            ability_name = f"技能{ability_id}"

        # 伤害类型
        type_value = ability_type_map.get(ability_id, 0)
        damage_type_str = format_damage_type(type_value)

        # 伤害统计
        total_damage = 0
        total_amount = 0       # 实际承伤累计
        total_unmitigated = 0
        max_hit = 0            # 单次最大(amount + mitigated)
        max_unmitigated = 0    # 单次最大（减免前）
        max_amount = 0         # 单次最大（减免后/实际承伤）
        timestamps = []

        for e in evts_sorted:
            amount = e.get("amount", 0)          # 实际承伤（减免后）
            mit = e.get("mitigated", 0)           # 减免量
            unmit = e.get("unmitigatedAmount", 0) # 减免前
            event_total = amount + mit

            total_damage += event_total
            total_amount += amount
            total_unmitigated += unmit
            max_hit = max(max_hit, event_total)
            max_unmitigated = max(max_unmitigated, unmit)
            max_amount = max(max_amount, amount)
            timestamps.append(e.get("timestamp", 0))

        hit_count = len(evts_sorted)
        avg_hit = total_damage / max(hit_count, 1)
        avg_amount = total_amount / max(hit_count, 1)       # 单次平均（减免后）
        avg_unmitigated = total_unmitigated / max(hit_count, 1)

        # 攻击间隔分析
        intervals = []
        for i in range(1, len(timestamps)):
            interval = timestamps[i] - timestamps[i-1]
            if interval > 0:  # 忽略同一时刻的多次命中
                intervals.append(interval)

        interval_stats = _analyze_intervals(intervals, hit_count)

        skill_info = {
            "source_name": source_name,
            "ability_name": ability_name,
            "source_id": source_id,
            "ability_id": ability_id,
            "damage_type": damage_type_str,
            "total_damage": total_damage,
            "hit_count": hit_count,
            "max_unmitigated": max_unmitigated,  # 单次最大（减免前）
            "max_amount": max_amount,            # 单次最大（减免后）
            "avg_amount": avg_amount,            # 单次平均（减免后）
            # 保留旧字段兼容
            "max_hit": max_hit,
            "avg_hit": avg_hit,
            "avg_unmitigated": avg_unmitigated,
            "interval_stats": interval_stats,
        }
        results.append(skill_info)

    # 标注total_damage=0的技能（全是偏转/未命中）
    for r in results:
        if r["total_damage"] == 0:
            r["note"] = "全偏转/未命中(0伤害)"
    # 按总伤害降序排列
    results.sort(key=lambda x: -x["total_damage"])
    return results


def _analyze_intervals(intervals, hit_count):
    """分析攻击间隔，判断攻击模式

    Returns:
        包含间隔统计和攻击模式判断的字典
    """
    if not intervals:
        if hit_count <= 1:
            return {"pattern": "单次命中", "description": "仅命中1次"}
        return {"pattern": "瞬间多重", "description": f"同一时刻命中{hit_count}次（DoT/AoE tick）"}

    avg_interval = sum(intervals) / len(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)

    # 计算变异系数判断稳定性
    if len(intervals) > 1:
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = variance ** 0.5
        cv = std_dev / avg_interval if avg_interval > 0 else 0
    else:
        std_dev = 0
        cv = 0

    avg_interval_s = avg_interval / 1000
    min_interval_s = min_interval / 1000
    max_interval_s = max_interval / 1000

    # 判断攻击模式
    if avg_interval_s < 1.0:
        if cv < 0.3:
            pattern = "高频固定"
            description = f"高频攻击，约{1/avg_interval_s:.1f}次/秒，间隔稳定"
        else:
            pattern = "高频不固定"
            description = f"高频攻击，约{1/avg_interval_s:.1f}次/秒，间隔波动大"
    elif avg_interval_s < 2.5:
        if cv < 0.3:
            pattern = "快速固定"
            description = f"快速攻击，约{avg_interval_s:.1f}秒/次，间隔稳定"
        else:
            pattern = "快速不固定"
            description = f"快速攻击，约{avg_interval_s:.1f}秒/次，间隔波动大"
    elif avg_interval_s < 5.0:
        if cv < 0.25:
            pattern = "中速固定CD"
            description = f"中频技能，约{avg_interval_s:.1f}秒CD，规律施放"
        else:
            pattern = "中速不固定"
            description = f"中频技能，约{avg_interval_s:.1f}秒/次，间隔不规律"
    else:
        if cv < 0.25:
            pattern = "低频固定CD"
            description = f"长CD技能，约{avg_interval_s:.1f}秒CD，规律施放"
        else:
            pattern = "低频不固定"
            description = f"低频技能，约{avg_interval_s:.1f}秒/次，可能受触发条件影响"

    return {
        "pattern": pattern,
        "description": description,
        "avg_interval_ms": round(avg_interval),
        "avg_interval_s": round(avg_interval_s, 2),
        "min_interval_s": round(min_interval_s, 2),
        "max_interval_s": round(max_interval_s, 2),
        "cv": round(cv, 3),
    }


# ===== 构建映射表 =====

def build_actor_maps(master_data):
    """从masterData构建各种映射表

    Returns:
        (actor_name_map, actor_icon_map, ability_map, ability_type_map)
    """
    actors = master_data.get("actors", [])
    abilities = master_data.get("abilities", [])

    actor_name_map = {a["id"]: a["name"] for a in actors}
    actor_icon_map = {a["id"]: a.get("icon", "") for a in actors}
    ability_map = {a["gameID"]: a for a in abilities}
    # 伤害类型映射：abilityGameID -> type（位掩码）
    ability_type_map = {a["gameID"]: int(a.get("type", 0)) for a in abilities}

    return actor_name_map, actor_icon_map, ability_map, ability_type_map


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
