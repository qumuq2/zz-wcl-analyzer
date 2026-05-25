#!/usr/bin/env python3
"""分析所有8个大秘境副本的Boss类型和野性之心使用时机

用法:
    python analyze_all_dungeons.py
    python analyze_all_dungeons.py --min-level 12 --max-runs 3
"""

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from wcl_analyzer.client import WCLClient
from wcl_analyzer.boss_timeline import BossTimelineAnalyzer
from wcl_analyzer.utils import (
    build_actor_maps, filter_events_by_target, find_players_by_spec,
)

# 大秘境S1赛季8个副本
DUNGEONS = {
    361753: "执政团之座",
    12915: "枢纽节点塞纳斯",
    112526: "艾杰斯亚学院",
    10658: "萨隆矿坑",
    12874: "迈萨拉洞窟",
    61209: "通天峰",
    12805: "风行者之塔",
    12811: "魔导师平台",
}

# 坦克专精icon列表
TANK_ICONS = [
    "Warrior-Protection", "Paladin-Protection", "DeathKnight-Blood",
    "Monk-Brewmaster", "DemonHunter-Vengeance", "Druid-Guardian",
]

# 野性之心CD
HEART_OF_WILD_CD = 120  # 秒


def find_tank_runs(client, encounter_id, min_level=12, days=3, max_runs=5):
    """搜索指定副本的坦克限时通关记录"""
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_ms = int((now - timedelta(days=days)).timestamp() * 1000)

    reports = client.search_reports_paginated(47, start_ms, max_pages=10, limit=100)

    runs = []
    for report in reports:
        code = report["code"]
        try:
            fights = client.get_fights(code)
        except:
            continue

        target_fights = [f for f in fights
                        if f.get("encounterID") == encounter_id
                        and f.get("kill")
                        and (f.get("keystoneLevel") or 0) >= min_level]

        if not target_fights:
            continue

        try:
            master_data = client.get_master_data(code)
        except:
            continue

        actors = master_data.get("actors", [])
        tanks = [a for a in actors
                 if a.get("type") == "Player" and a.get("icon") in TANK_ICONS]

        for fight in target_fights:
            # 限时判断（大约33-40分钟，大秘境限时因副本而异）
            duration = fight["endTime"] - fight["startTime"]
            if duration > 2400000:  # 超过40分钟不算限时
                continue

            for tank in tanks:
                runs.append({
                    "code": code,
                    "fight_id": fight["id"],
                    "tank_id": tank["id"],
                    "tank_name": tank["name"],
                    "tank_spec": tank.get("icon", ""),
                    "keystone_level": fight.get("keystoneLevel", 0),
                    "duration_s": round(duration / 1000, 1),
                })

        if len(runs) >= max_runs:
            break

    return runs[:max_runs]


def identify_dungeon_bosses(client, code, fight_id, fight_start, fight_end):
    """识别一场战斗中属于该副本的Boss列表"""
    master_data = client.get_master_data(code)
    all_events = client.get_all_events(code, [fight_id], "DamageTaken", max_pages=20)

    actors = master_data.get("actors", [])
    boss_actors = {a["id"]: a["name"] for a in actors if a.get("subType") == "Boss"}

    # 只保留在此fight中有伤害事件的Boss
    fight_events = [e for e in all_events
                    if fight_start <= e.get("timestamp", 0) <= fight_end]

    active_bosses = {}
    for boss_id, boss_name in boss_actors.items():
        boss_events = [e for e in fight_events if e.get("sourceID") == boss_id]
        if boss_events:
            active_bosses[boss_id] = boss_name

    return active_bosses


def analyze_dungeon(client, analyzer, encounter_id, dungeon_name,
                    min_level=12, max_runs=3):
    """分析一个副本的所有Boss"""
    print(f"\n{'='*60}")
    print(f"分析: {dungeon_name} (Encounter {encounter_id})")
    print(f"{'='*60}")

    # 搜索坦克通关记录
    runs = find_tank_runs(client, encounter_id, min_level=min_level, max_runs=max_runs*2)

    if not runs:
        print(f"  未找到符合条件的记录")
        return None

    # 优先选择不同层数的记录
    level_groups = defaultdict(list)
    for run in runs:
        level_groups[run["keystone_level"]].append(run)

    selected_runs = []
    for level in sorted(level_groups.keys(), reverse=True):
        selected_runs.append(level_groups[level][0])
        if len(selected_runs) >= max_runs:
            break

    # 补充不同层数
    if len(selected_runs) < max_runs:
        for level in sorted(level_groups.keys()):
            if not any(r["keystone_level"] == level for r in selected_runs):
                selected_runs.append(level_groups[level][0])
            if len(selected_runs) >= max_runs:
                break

    print(f"  选取 {len(selected_runs)} 场记录:")
    for run in selected_runs:
        print(f"    {run['tank_name']}({run['tank_spec']}) +{run['keystone_level']}层 {run['duration_s']}s")

    # 获取Boss列表（从第一场记录中识别）
    first_run = selected_runs[0]
    fights = client.get_fights(first_run["code"])
    fight = next((f for f in fights if f["id"] == first_run["fight_id"]), None)

    if not fight:
        return None

    boss_names = identify_dungeon_bosses(
        client, first_run["code"], first_run["fight_id"],
        fight["startTime"], fight["endTime"]
    )
    print(f"  Boss列表: {list(boss_names.values())}")

    # 对每个Boss分析
    boss_results = {}
    for boss_id, boss_name in boss_names.items():
        print(f"\n  --- Boss: {boss_name} ---")

        # 收集跨场次数据
        all_boss_data = []
        boss_casts_by_ability = defaultdict(list)  # aname -> [(run_name, first_cast_s, duration_s)]

        for run in selected_runs:
            data = analyzer.get_boss_fight_data(run["code"], run["fight_id"], run["tank_id"])
            if data is None:
                print(f"    {run['tank_name']}: 坦克承伤为0，跳过")
                continue

            # 找该Boss的阶段
            if boss_name not in data["boss_phases"]:
                print(f"    {run['tank_name']}: 未找到该Boss数据")
                continue

            phase = data["boss_phases"][boss_name]
            phase_start = phase["start"]
            phase_end = phase["end"]
            duration_s = round((phase_end - phase_start) / 1000, 1)

            # Boss对坦克的承伤
            boss_dmg = [e for e in data["tank_events"] if e.get("sourceID") == boss_id]

            # Boss施法
            boss_casts = [c for c in data["cast_events"] if c.get("sourceID") == boss_id]

            # 按技能分组施法（用于Boss类型判断）
            casts_by_ability = analyzer.get_boss_casts_by_ability(
                boss_casts, phase_start, data["ability_name_map"]
            )

            # 收集首次施法时间
            run_name = f"{run['tank_name']}(+{run['keystone_level']})"
            for aname, timestamps in casts_by_ability.items():
                if timestamps:
                    boss_casts_by_ability[aname].append((run_name, timestamps[0], duration_s))

            # 安全窗口
            safe_windows = analyzer.find_safe_windows(boss_dmg, phase_start, phase_end)
            safe_windows = analyzer.annotate_windows(
                safe_windows, boss_casts, phase_start, data["ability_name_map"]
            )

            # 如果无安全窗口，找次级安全窗口
            secondary = None
            if not safe_windows:
                # 找伤害最低的DoT类技能
                dmg_by_ability = defaultdict(lambda: {"total": 0, "count": 0, "raw": 0, "mit": 0, "unmit": 0})
                for e in boss_dmg:
                    aid = e.get("abilityGameID", 0)
                    amt = e.get("amount", 0)
                    mit = e.get("mitigated", 0)
                    unmit = e.get("unmitigatedAmount", 0)
                    dmg_by_ability[aid]["total"] += amt + mit
                    dmg_by_ability[aid]["count"] += 1
                    dmg_by_ability[aid]["raw"] += amt
                    dmg_by_ability[aid]["mit"] += mit
                    dmg_by_ability[aid]["unmit"] += unmit

                # 找平均单次伤害最低且命中次数多的技能（DoT特征）
                dot_candidates = []
                for aid, stats in dmg_by_ability.items():
                    if stats["count"] >= 5:  # 至少命中5次
                        avg = stats["total"] / stats["count"]
                        dot_candidates.append((aid, avg, stats))

                if dot_candidates:
                    dot_candidates.sort(key=lambda x: x[1])  # 按平均伤害升序
                    ignore_id = dot_candidates[0][0]
                    ignore_name = data["ability_name_map"].get(ignore_id, f"技能{ignore_id}")

                    secondary = analyzer.find_secondary_safe_windows(
                        boss_dmg, phase_start, phase_end, {ignore_id}
                    )
                    sec_windows = analyzer.annotate_windows(
                        secondary["windows"], boss_casts, phase_start, data["ability_name_map"]
                    )
                    secondary["windows"] = sec_windows
                    secondary["ability_name"] = ignore_name

            all_boss_data.append({
                "run_name": run_name,
                "duration_s": duration_s,
                "boss_dmg_count": len(boss_dmg),
                "boss_casts_count": len(boss_casts),
                "safe_windows": safe_windows,
                "secondary": secondary,
            })
            print(f"    {run_name}: {duration_s}s | 承伤{len(boss_dmg)} | 施法{len(boss_casts)} | 窗口{len(safe_windows)}")

        # Boss类型判断
        boss_type_result = analyzer.determine_boss_type(boss_casts_by_ability)
        print(f"    类型: {boss_type_result['judgment']}")

        boss_results[boss_name] = {
            "boss_type": boss_type_result["boss_type"],
            "boss_type_detail": boss_type_result,
            "runs": all_boss_data,
        }

    return {
        "encounter_id": encounter_id,
        "bosses": boss_results,
    }


def main():
    parser = argparse.ArgumentParser(description="分析所有8个大秘境副本")
    parser.add_argument("--min-level", type=int, default=12, help="最低层数")
    parser.add_argument("--max-runs", type=int, default=3, help="每个Boss最多分析几场")
    parser.add_argument("--output", type=str, default="all_dungeons_analysis.json",
                       help="输出文件名")
    args = parser.parse_args()

    client = WCLClient()
    analyzer = BossTimelineAnalyzer(client)

    all_results = {}

    for encounter_id, dungeon_name in DUNGEONS.items():
        try:
            result = analyze_dungeon(client, analyzer, encounter_id, dungeon_name,
                                    min_level=args.min_level, max_runs=args.max_runs)
            if result:
                all_results[dungeon_name] = result
        except Exception as e:
            print(f"\n  分析 {dungeon_name} 失败: {e}")
            import traceback
            traceback.print_exc()

    # 保存结果
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n\n结果已保存到 {args.output}")


if __name__ == "__main__":
    main()
