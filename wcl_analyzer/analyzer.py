"""WCL 日志分析逻辑

基于原项目 app/analyzer.py 改造，同时融合了实际查询中新增的分析功能：
- 敌人技能分析（原项目保留）
- 敌人施法CD分析（原项目保留）
- Boss机制触发类型分析（原项目保留）
- 玩家承伤分析（原项目保留，新增事件级分析）
- Boss阶段承伤分析（新增：按Boss时间窗口分析承伤）
- 小怪阶段承伤分析（新增：Boss之间的过渡阶段分析）
"""

from collections import defaultdict
from .config import DAMAGE_TYPE_MAP, HIT_TYPE_MAP, PIT_OF_SARON_BOSS1_SKILLS
from .utils import (
    detect_boss_phases,
    calculate_damage_taken_stats,
    build_actor_maps,
    filter_events_by_target,
    format_duration,
    format_dps,
    format_number,
)


# ===== 原项目分析函数（保留） =====

def analyze_enemy_abilities(table_data, master_data=None):
    """分析敌人技能：伤害类型、数值、目标分布

    输入：table(DamageDone, Enemies) 的数据
    """
    entries = table_data.get("entries", [])
    actor_map = {}
    if master_data:
        for actor in master_data.get("actors", []):
            actor_map[actor["id"]] = actor

    result = []
    for entry in entries:
        abilities = []
        for ab in entry.get("abilities", []):
            ability_info = {
                "技能名称": ab.get("name", "未知"),
                "技能ID": ab.get("guid"),
                "伤害类型": DAMAGE_TYPE_MAP.get(ab.get("type"), f"未知({ab.get('type')})"),
                "总伤害": ab.get("total", 0),
                "减伤后总伤害": ab.get("totalReduced", 0),
                "图标": ab.get("icon", ""),
            }
            abilities.append(ability_info)

        targets = []
        for t in entry.get("targets", []):
            target_info = {
                "目标名称": t.get("name", "未知"),
                "目标职业": t.get("type", "未知"),
                "承受伤害": t.get("total", 0),
                "减伤后承受伤害": t.get("totalReduced", 0),
            }
            targets.append(target_info)

        enemy_info = {
            "敌人名称": entry.get("name", "未知"),
            "敌人ID": entry.get("id"),
            "游戏内ID": entry.get("guid"),
            "类型": entry.get("type", ""),
            "是否Boss": actor_map.get(entry.get("id"), {}).get("subType") == "Boss",
            "总伤害": entry.get("total", 0),
            "减伤后总伤害": entry.get("totalReduced", 0),
            "活跃时间(ms)": entry.get("activeTime", 0),
            "技能列表": abilities,
            "伤害目标": targets,
        }
        result.append(enemy_info)

    return {
        "敌人数量": len(result),
        "Boss": [e for e in result if e["是否Boss"]],
        "小怪": [e for e in result if not e["是否Boss"]],
    }


def analyze_enemy_casts(events, master_data=None, fight_start=0, fight_end=0):
    """分析敌人施法事件：技能CD规律、施法时间轴

    输入：events(Casts, Enemies) 的数据
    """
    casts_by_source_ability = defaultdict(list)
    for event in events:
        if event.get("type") != "cast":
            continue
        source_id = event.get("sourceID")
        ability_id = event.get("abilityGameID")
        timestamp = event.get("timestamp", 0)
        casts_by_source_ability[(source_id, ability_id)].append(timestamp)

    actor_map = {}
    ability_map = {}
    if master_data:
        for actor in master_data.get("actors", []):
            actor_map[actor["id"]] = actor
        for ab in master_data.get("abilities", []):
            ability_map[ab["gameID"]] = ab

    result = []
    for (source_id, ability_id), timestamps in casts_by_source_ability.items():
        timestamps.sort()
        intervals = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
        cd_analysis = _analyze_cd_pattern(intervals)

        actor_name = actor_map.get(source_id, {}).get("name", f"ID:{source_id}")
        ability_info = ability_map.get(ability_id, {})
        ability_name = ability_info.get("name", f"技能ID:{ability_id}")

        result.append({
            "施法者": actor_name,
            "施法者ID": source_id,
            "技能名称": ability_name,
            "技能ID": ability_id,
            "施法次数": len(timestamps),
            "首次施法(相对战斗开始ms)": timestamps[0] - fight_start if timestamps else None,
            "末次施法(相对战斗开始ms)": timestamps[-1] - fight_start if timestamps else None,
            "施法间隔(ms)": intervals if intervals else [],
            "CD分析": cd_analysis,
            "施法时间轴(相对战斗开始ms)": [t - fight_start for t in timestamps],
        })

    return {"技能数量": len(result), "分析结果": result}


def analyze_boss_mechanics(cast_events, damage_events, master_data=None,
                            fight_start=0, fight_end=0):
    """分析Boss机制：时间轴触发 vs 血量触发"""
    boss_ids = set()
    if master_data:
        for actor in master_data.get("actors", []):
            if actor.get("subType") == "Boss":
                boss_ids.add(actor["id"])

    casts_by_ability = defaultdict(list)
    for event in cast_events:
        if event.get("type") != "cast":
            continue
        source_id = event.get("sourceID")
        if source_id not in boss_ids:
            continue
        ability_id = event.get("abilityGameID")
        timestamp = event.get("timestamp", 0)
        casts_by_ability[(source_id, ability_id)].append(timestamp)

    ability_map = {}
    actor_map = {}
    if master_data:
        for actor in master_data.get("actors", []):
            actor_map[actor["id"]] = actor
        for ab in master_data.get("abilities", []):
            ability_map[ab["gameID"]] = ab

    fight_duration = fight_end - fight_start if fight_end and fight_start else 0

    result = []
    for (source_id, ability_id), timestamps in casts_by_ability.items():
        timestamps.sort()
        intervals = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
        cd_analysis = _analyze_cd_pattern(intervals)

        relative_times = []
        for t in timestamps:
            pct = round((t - fight_start) / fight_duration * 100, 1) if fight_duration > 0 else None
            relative_times.append({
                "时间(ms)": t - fight_start,
                "时间(秒)": round((t - fight_start) / 1000, 1),
                "战斗进度(%)": pct,
            })

        trigger_type = _determine_trigger_type(cd_analysis, relative_times)

        actor_name = actor_map.get(source_id, {}).get("name", f"ID:{source_id}")
        ability_info = ability_map.get(ability_id, {})
        ability_name = ability_info.get("name", f"技能ID:{ability_id}")

        result.append({
            "Boss": actor_name,
            "技能名称": ability_name,
            "技能ID": ability_id,
            "施法次数": len(timestamps),
            "触发类型": trigger_type,
            "CD分析": cd_analysis,
            "施法时间轴": relative_times,
        })

    return {"Boss技能数量": len(result), "分析结果": result}


def analyze_player_damage_taken(table_data, player_name=None, ability_name=None):
    """分析玩家承伤情况

    输入：table(DamageTaken) 的数据
    """
    entries = table_data.get("entries", [])

    result = []
    for entry in entries:
        name = entry.get("name", "")
        if player_name and player_name.lower() not in name.lower():
            continue

        abilities = []
        for ab in entry.get("abilities", []):
            if ability_name and ability_name.lower() not in ab.get("name", "").lower():
                continue
            ability_info = {
                "技能名称": ab.get("name", "未知"),
                "技能ID": ab.get("guid"),
                "伤害类型": DAMAGE_TYPE_MAP.get(ab.get("type"), f"未知({ab.get('type')})"),
                "总承受伤害": ab.get("total", 0),
                "减伤后总承受伤害": ab.get("totalReduced", 0),
                "命中次数": ab.get("hitCount", 0),
                "暴击次数": ab.get("critCount", 0),
                "图标": ab.get("icon", ""),
            }
            abilities.append(ability_info)

        sources = []
        for s in entry.get("targets", []):
            source_info = {
                "伤害来源": s.get("name", "未知"),
                "来源类型": s.get("type", "未知"),
                "造成伤害": s.get("total", 0),
                "减伤后造成伤害": s.get("totalReduced", 0),
            }
            sources.append(source_info)

        player_info = {
            "玩家名称": name,
            "玩家ID": entry.get("id"),
            "职业": entry.get("type", "未知"),
            "总承受伤害": entry.get("total", 0),
            "减伤后总承受伤害": entry.get("totalReduced", 0),
            "承受技能列表": abilities,
            "伤害来源": sources,
        }
        result.append(player_info)

    return {"玩家数量": len(result), "分析结果": result}


# ===== 新增：事件级承伤分析 =====

def analyze_boss_damage_taken(client, code, fight_id, tank_id, boss_names=None):
    """分析坦克在Boss战中的承伤详情

    通过Boss名称匹配伤害事件的source，按Boss时间窗口统计承伤。

    Args:
        client: WCLClient实例
        code: 报告代码
        fight_id: 战斗ID
        tank_id: 坦克actor ID
        boss_names: Boss名称字典，默认萨隆矿坑

    Returns:
        每个Boss阶段的承伤统计
    """
    # 获取masterData
    master_data = client.get_master_data(code)
    actor_name_map, actor_icon_map, ability_map = build_actor_maps(master_data)

    # 获取所有DamageTaken事件（targetID过滤无效，客户端过滤）
    all_events = client.get_all_events(code, [fight_id], "DamageTaken", max_pages=20)
    tank_events = filter_events_by_target(all_events, tank_id)

    if not tank_events:
        return {"error": f"未找到坦克ID {tank_id} 的承伤事件"}

    # 检测Boss阶段
    phases = detect_boss_phases(tank_events, actor_name_map, boss_names)

    # 按Boss阶段统计
    boss_results = {}
    for phase in phases["boss_phases"]:
        phase_events = filter_events_by_time(
            tank_events, phase["start"], phase["end"]
        )
        # 排除非Boss的伤害（只统计该Boss造成的伤害）
        boss_name = phase["boss"]
        boss_only_events = [
            e for e in phase_events
            if actor_name_map.get(e.get("sourceID", 0)) == boss_name
        ]
        stats = calculate_damage_taken_stats(boss_only_events, actor_name_map)
        duration_ms = phase["end"] - phase["start"]
        boss_results[boss_name] = {
            **stats,
            "duration_ms": duration_ms,
            "duration_str": format_duration(duration_ms),
            "dps_str": format_dps(stats["total"], duration_ms),
        }

    return {
        "boss_phases": phases["boss_phases"],
        "boss_damage": boss_results,
    }


def analyze_trash_damage_taken(client, code, fight_id, tank_id, boss_names=None):
    """分析坦克在小怪阶段（Boss之间）的承伤详情

    Args:
        client: WCLClient实例
        code: 报告代码
        fight_id: 战斗ID
        tank_id: 坦克actor ID
        boss_names: Boss名称字典

    Returns:
        每个小怪阶段的承伤统计
    """
    master_data = client.get_master_data(code)
    actor_name_map, actor_icon_map, ability_map = build_actor_maps(master_data)

    all_events = client.get_all_events(code, [fight_id], "DamageTaken", max_pages=20)
    tank_events = filter_events_by_target(all_events, tank_id)

    if not tank_events:
        return {"error": f"未找到坦克ID {tank_id} 的承伤事件"}

    phases = detect_boss_phases(tank_events, actor_name_map, boss_names)

    trash_results = {}
    for phase in phases["trash_phases"]:
        phase_events = filter_events_by_time(
            tank_events, phase["start"], phase["end"]
        )
        # 排除Boss造成的伤害
        boss_names_set = set(boss_names.keys()) if boss_names else set()
        trash_only_events = [
            e for e in phase_events
            if actor_name_map.get(e.get("sourceID", 0)) not in boss_names_set
        ]
        stats = calculate_damage_taken_stats(trash_only_events, actor_name_map)
        duration_ms = phase["end"] - phase["start"]
        after_boss = phase["after_boss"]
        trash_results[f"Boss{after_boss}后小怪"] = {
            **stats,
            "duration_ms": duration_ms,
            "duration_str": format_duration(duration_ms),
            "dps_str": format_dps(stats["total"], duration_ms),
        }

    return {
        "trash_phases": phases["trash_phases"],
        "trash_damage": trash_results,
    }


def analyze_full_tank_run(client, code, fight_id, tank_id, tank_name,
                          boss_names=None, skill_map=None):
    """完整分析一次大秘境中坦克的承伤

    一次性获取所有数据并完成分析，包括：
    - 基本信息（层数、时长、通关状态）
    - Boss阶段承伤
    - 小怪阶段承伤
    - 全局承伤时间线

    Args:
        client: WCLClient实例
        code: 报告代码
        fight_id: 战斗ID
        tank_id: 坦克actor ID
        tank_name: 坦克名称
        boss_names: Boss名称映射
        skill_map: 技能ID映射
    """
    # 获取基本信息
    fights = client.get_fights(code)
    fight = next((f for f in fights if f["id"] == fight_id), None)
    if not fight:
        return {"error": f"未找到战斗ID {fight_id}"}

    master_data = client.get_master_data(code)
    actor_name_map, actor_icon_map, ability_map = build_actor_maps(master_data)

    # 获取所有承伤事件
    all_events = client.get_all_events(code, [fight_id], "DamageTaken", max_pages=20)
    tank_events = filter_events_by_target(all_events, tank_id)

    if not tank_events:
        return {"error": f"未找到坦克 {tank_name} 的承伤事件"}

    # 检测Boss阶段
    phases = detect_boss_phases(tank_events, actor_name_map, boss_names)

    # 总承伤统计
    total_stats = calculate_damage_taken_stats(tank_events, actor_name_map)

    # Boss阶段统计
    boss_results = {}
    for phase in phases["boss_phases"]:
        boss_name = phase["boss"]
        boss_events = [
            e for e in tank_events
            if phase["start"] <= e.get("timestamp", 0) <= phase["end"]
            and actor_name_map.get(e.get("sourceID", 0)) == boss_name
        ]
        stats = calculate_damage_taken_stats(boss_events, actor_name_map)
        duration_ms = phase["end"] - phase["start"]

        # 技能分布（如果有技能映射，用映射名称）
        by_ability_detail = {}
        for aid, dmg in stats["by_ability"].items():
            skill_name = (skill_map or {}).get(aid, ability_map.get(aid, {}).get("name", f"技能{aid}"))
            by_ability_detail[skill_name] = {
                "damage": dmg,
                "pct": dmg / max(stats["total"], 1) * 100,
            }

        boss_results[boss_name] = {
            **stats,
            "by_ability_detail": by_ability_detail,
            "duration_ms": duration_ms,
            "duration_str": format_duration(duration_ms),
            "dps_str": format_dps(stats["total"], duration_ms),
        }

    # 小怪阶段统计
    trash_results = {}
    for phase in phases["trash_phases"]:
        boss_names_set = set((boss_names or {}).keys())
        trash_events = [
            e for e in tank_events
            if phase["start"] <= e.get("timestamp", 0) <= phase["end"]
            and actor_name_map.get(e.get("sourceID", 0)) not in boss_names_set
        ]
        stats = calculate_damage_taken_stats(trash_events, actor_name_map)
        duration_ms = phase["end"] - phase["start"]
        after_boss = phase["after_boss"]

        # 按怪物来源分布
        by_source_detail = {}
        for src, dmg in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            by_source_detail[src] = {
                "damage": dmg,
                "pct": dmg / max(stats["total"], 1) * 100,
            }

        trash_results[f"Boss{after_boss}后小怪"] = {
            **stats,
            "by_source_detail": by_source_detail,
            "duration_ms": duration_ms,
            "duration_str": format_duration(duration_ms),
            "dps_str": format_dps(stats["total"], duration_ms),
        }

    fight_duration_ms = fight["endTime"] - fight["startTime"]

    return {
        "report_code": code,
        "fight_id": fight_id,
        "tank_name": tank_name,
        "keystone_level": fight.get("keystoneLevel"),
        "kill": fight.get("kill"),
        "duration_ms": fight_duration_ms,
        "duration_str": format_duration(fight_duration_ms),
        "total_stats": total_stats,
        "boss_phases": phases["boss_phases"],
        "trash_phases": phases["trash_phases"],
        "boss_damage": boss_results,
        "trash_damage": trash_results,
    }


# ===== 内部辅助函数 =====

def _analyze_cd_pattern(intervals):
    """分析施法间隔，判断CD规律"""
    if not intervals:
        return {"判断": "施法次数不足，无法分析"}

    min_interval = min(intervals)
    max_interval = max(intervals)
    avg_interval = sum(intervals) / len(intervals)

    if len(intervals) > 1:
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = variance ** 0.5
        cv = std_dev / avg_interval if avg_interval > 0 else 0
    else:
        std_dev = 0
        cv = 0

    if cv < 0.1:
        cd_type = "固定CD"
        cd_value = round(avg_interval)
    elif cv < 0.25:
        cd_type = "近似固定CD"
        cd_value = round(avg_interval)
    else:
        cd_type = "非固定CD（可能受血量/阶段/触发条件影响）"
        cd_value = None

    return {
        "判断": cd_type,
        "估计CD(ms)": cd_value,
        "估计CD(秒)": round(cd_value / 1000, 1) if cd_value else None,
        "最短间隔(ms)": min_interval,
        "最长间隔(ms)": max_interval,
        "平均间隔(ms)": round(avg_interval),
        "间隔标准差(ms)": round(std_dev),
        "变异系数": round(cv, 3),
    }


def _determine_trigger_type(cd_analysis, relative_times):
    """判断技能触发类型"""
    judgment = cd_analysis.get("判断", "")
    if "固定CD" in judgment or "近似固定CD" in judgment:
        return "时间轴触发（CD规律稳定）"
    if len(relative_times) < 2:
        return "数据不足，无法判断"
    progress_points = [t["战斗进度(%)"] for t in relative_times if t.get("战斗进度(%)") is not None]
    if len(progress_points) >= 2:
        intervals = [progress_points[i+1] - progress_points[i] for i in range(len(progress_points)-1)]
        if intervals:
            cv = (sum((x - sum(intervals)/len(intervals))**2 for x in intervals) / len(intervals)) ** 0.5
            avg = sum(intervals) / len(intervals)
            if avg > 0 and cv / avg > 0.3:
                return "可能血量触发（施法间隔与战斗进度不均匀）"
    return "非固定CD（需结合战斗录像判断是否为血量触发）"


def filter_events_by_time(events, start_time, end_time):
    """按时间范围过滤事件"""
    return [e for e in events if start_time <= e.get("timestamp", 0) <= end_time]
