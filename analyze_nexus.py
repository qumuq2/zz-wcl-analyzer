#!/usr/bin/env python3
"""分析枢纽节点塞纳斯(Nexus)所有Boss的详细技能承伤

用法:
    cd /tmp/zz-wcl-analyzer && python3 analyze_nexus.py
    cd /tmp/zz-wcl-analyzer && python3 analyze_nexus.py --min-level 20 --max-runs 4
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
    analyze_skills, format_number, format_duration, format_dps,
)

# 枢纽节点塞纳斯 encounter ID
NEXUS_ENCOUNTER_ID = 12915
NEXUS_NAME = "枢纽节点塞纳斯"

# 坦克专精icon
TANK_ICONS = [
    "Warrior-Protection", "Paladin-Protection", "DeathKnight-Blood",
    "Monk-Brewmaster", "DemonHunter-Vengeance", "Druid-Guardian",
]


def _format_wan(value):
    """将伤害值格式化为万单位"""
    return f"{value / 10000:.0f}万"


def find_bear_runs(client, encounter_id, min_level=20, days=7, max_runs=6):
    """搜索指定副本的熊坦限时通关记录"""
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_ms = int((now - timedelta(days=days)).timestamp() * 1000)

    reports = client.search_reports_paginated(47, start_ms, max_pages=15, limit=100)
    print(f"  搜索到 {len(reports)} 份报告")

    runs = []
    for i, report in enumerate(reports):
        code = report["code"]
        try:
            fights = client.get_fights(code)
        except Exception:
            continue

        target_fights = [f for f in fights
                        if f.get("encounterID") == encounter_id
                        and f.get("kill")
                        and (f.get("keystoneLevel") or 0) >= min_level]

        if not target_fights:
            continue

        try:
            master_data = client.get_master_data(code)
        except Exception:
            continue

        # 只找熊坦
        bear_tanks = [a for a in master_data.get("actors", [])
                      if a.get("type") == "Player" and a.get("icon") == "Druid-Guardian"]

        for fight in target_fights:
            duration = fight["endTime"] - fight["startTime"]
            if duration > 2400000:  # 超过40分钟不算限时
                continue

            for tank in bear_tanks:
                runs.append({
                    "code": code,
                    "fight_id": fight["id"],
                    "tank_id": tank["id"],
                    "tank_name": tank["name"],
                    "tank_spec": "Druid-Guardian",
                    "keystone_level": fight.get("keystoneLevel", 0),
                    "duration_s": round(duration / 1000, 1),
                })

        if len(runs) >= max_runs * 2:
            break

        # API限流
        time.sleep(0.5)

    print(f"  找到 {len(runs)} 条熊坦记录")

    # 优先选不同层数的，优先高层数
    level_groups = defaultdict(list)
    for run in runs:
        level_groups[run["keystone_level"]].append(run)

    selected = []
    for level in sorted(level_groups.keys(), reverse=True):
        selected.append(level_groups[level][0])
        if len(selected) >= max_runs:
            break

    return selected[:max_runs]


def analyze_boss_skills_detailed(client, analyzer, code, fight_id, tank_id, tank_name, ksl):
    """对一场战斗中所有Boss做详细技能分析"""
    data = analyzer.get_boss_fight_data(code, fight_id, tank_id)
    if data is None:
        print(f"    {tank_name}(+{ksl}): 坦克承伤为0，跳过")
        return None

    actor_name_map = data["actor_name_map"]
    ability_map = data["ability_map"]
    ability_type_map = data["ability_type_map"]
    ability_name_map = data["ability_name_map"]
    tank_events = data["tank_events"]
    cast_events = data["cast_events"]
    boss_phases = data["boss_phases"]

    boss_results = {}
    for boss_name, phase_info in boss_phases.items():
        boss_id = phase_info["boss_id"]
        phase_start = phase_info["start"]
        phase_end = phase_info["end"]
        duration_ms = phase_end - phase_start

        # Boss对坦克的承伤事件（包含环境伤害）
        # 用时间窗口过滤，这样可以捕获非Boss来源的环境伤害
        boss_phase_events = [e for e in tank_events
                            if phase_start <= e.get("timestamp", 0) <= phase_end]

        # 纯Boss来源的承伤
        boss_only_events = [e for e in boss_phase_events
                           if e.get("sourceID") == boss_id]

        # 其他来源（环境伤害等）
        env_events = [e for e in boss_phase_events
                     if e.get("sourceID") != boss_id]

        # Boss技能维度分析
        boss_skills = analyze_skills(boss_only_events, actor_name_map, ability_type_map, ability_map)

        # 环境伤害维度分析
        env_skills = analyze_skills(env_events, actor_name_map, ability_type_map, ability_map)

        # Boss施法事件
        boss_casts = [c for c in cast_events if c.get("sourceID") == boss_id]

        # 按施法分组
        casts_by_ability = defaultdict(list)
        for c in boss_casts:
            aid = c.get("abilityGameID", 0)
            ts = c.get("timestamp", 0)
            aname = ability_name_map.get(aid, f"技能{aid}")
            casts_by_ability[aname].append((ts - phase_start) / 1000)

        boss_results[boss_name] = {
            "duration_ms": duration_ms,
            "duration_s": round(duration_ms / 1000, 1),
            "boss_id": boss_id,
            "boss_skills": boss_skills,
            "env_skills": env_skills,
            "boss_casts_by_ability": dict(casts_by_ability),
            "boss_only_count": len(boss_only_events),
            "env_count": len(env_events),
            "phase_start": phase_start,
            "phase_end": phase_end,
        }

    return {
        "code": code,
        "fight_id": fight_id,
        "tank_name": tank_name,
        "keystone_level": ksl,
        "boss_results": boss_results,
        "ability_name_map": ability_name_map,
        "actor_name_map": actor_name_map,
        "cast_events": cast_events,
        "tank_events": tank_events,
    }


def print_boss_detail(run_data):
    """打印一场战斗的Boss详细技能分析"""
    ksl = run_data["keystone_level"]
    tank = run_data["tank_name"]
    ability_name_map = run_data["ability_name_map"]

    for boss_name, info in run_data["boss_results"].items():
        dur = info["duration_s"]
        print(f"\n  === {boss_name} ({dur}s) - {tank}(+{ksl}) ===")

        # Boss技能
        if info["boss_skills"]:
            total_dmg = sum(s["total_damage"] for s in info["boss_skills"])
            print(f"  Boss承伤总计: {_format_wan(total_dmg)} | 命中: {info['boss_only_count']}次")
            print(f"  技能详情:")
            for sk in info["boss_skills"]:
                pct = sk["total_damage"] / max(total_dmg, 1) * 100
                max_pre = sk.get("max_unmitigated", 0)
                avg_pre = sk.get("avg_unmitigated", 0)
                max_post = sk.get("max_amount", 0)
                avg_post = sk.get("avg_amount", 0)
                print(f"    [{sk['damage_type']}] {sk['source_name']} - {sk['ability_name']}")
                print(f"      命中{sk['hit_count']}次 | 总伤害: {_format_wan(sk['total_damage'])} ({pct:.1f}%)")
                print(f"      减免前: 最大{_format_wan(max_pre)} / 平均{_format_wan(avg_pre)}")
                print(f"      减免后: 最大{_format_wan(max_post)} / 平均{_format_wan(avg_post)}")
                ist = sk["interval_stats"]
                if ist.get("avg_interval_s") is not None:
                    print(f"      间隔: {ist['avg_interval_s']:.2f}s (最短{ist['min_interval_s']:.2f}s / 最长{ist['max_interval_s']:.2f}s) [{ist['pattern']}]")

        # 环境伤害
        if info["env_skills"]:
            env_total = sum(s["total_damage"] for s in info["env_skills"])
            print(f"\n  环境伤害总计: {_format_wan(env_total)} | 命中: {info['env_count']}次")
            for sk in info["env_skills"]:
                pct = sk["total_damage"] / max(env_total, 1) * 100
                max_pre = sk.get("max_unmitigated", 0)
                avg_pre = sk.get("avg_unmitigated", 0)
                max_post = sk.get("max_amount", 0)
                avg_post = sk.get("avg_amount", 0)
                print(f"    [{sk['damage_type']}] {sk['source_name']} - {sk['ability_name']}")
                print(f"      命中{sk['hit_count']}次 | 总伤害: {_format_wan(sk['total_damage'])} ({pct:.1f}%)")
                print(f"      减免前: 最大{_format_wan(max_pre)} / 平均{_format_wan(avg_pre)}")
                print(f"      减免后: 最大{_format_wan(max_post)} / 平均{_format_wan(avg_post)}")
                ist = sk["interval_stats"]
                if ist.get("avg_interval_s") is not None:
                    print(f"      间隔: {ist['avg_interval_s']:.2f}s [{ist['pattern']}]")

        # Boss施法时间轴
        if info["boss_casts_by_ability"]:
            print(f"\n  Boss施法时间轴:")
            for aname, timestamps in sorted(info["boss_casts_by_ability"].items(), key=lambda x: x[1][0] if x[1] else 0):
                if len(timestamps) >= 2:
                    intervals = [round(timestamps[i+1] - timestamps[i], 1) for i in range(len(timestamps)-1)]
                    print(f"    {aname}: 首次{timestamps[0]:.1f}s | 间隔{intervals}")
                else:
                    print(f"    {aname}: {timestamps[0]:.1f}s (仅1次)")


def main():
    parser = argparse.ArgumentParser(description="分析枢纽节点塞纳斯Boss详细技能")
    parser.add_argument("--min-level", type=int, default=20, help="最低层数")
    parser.add_argument("--max-runs", type=int, default=4, help="每个Boss最多分析几场")
    parser.add_argument("--days", type=int, default=7, help="搜索最近几天")
    args = parser.parse_args()

    client = WCLClient()
    analyzer = BossTimelineAnalyzer(client)

    print(f"{'='*60}")
    print(f"分析: {NEXUS_NAME} (Encounter {NEXUS_ENCOUNTER_ID})")
    print(f"{'='*60}")

    # 搜索熊坦记录
    runs = find_bear_runs(client, NEXUS_ENCOUNTER_ID,
                          min_level=args.min_level,
                          days=args.days,
                          max_runs=args.max_runs)

    if not runs:
        print("  未找到符合条件的熊坦记录")
        return

    print(f"\n  选取 {len(runs)} 场记录:")
    for run in runs:
        print(f"    {run['tank_name']}(+{run['keystone_level']}) {run['duration_s']}s")

    # 逐场分析
    all_run_data = []
    for run in runs:
        print(f"\n{'─'*40}")
        print(f"分析: {run['tank_name']}(+{run['keystone_level']}) ...")
        try:
            run_data = analyze_boss_skills_detailed(
                client, analyzer,
                run["code"], run["fight_id"], run["tank_id"],
                run["tank_name"], run["keystone_level"]
            )
            if run_data:
                all_run_data.append(run_data)
                print_boss_detail(run_data)
            time.sleep(0.5)
        except Exception as e:
            print(f"  分析失败: {e}")
            import traceback
            traceback.print_exc()

    # 保存原始数据
    output_file = f"/tmp/nexus_analysis_{args.min_level}plus.json"
    with open(output_file, "w", encoding="utf-8") as f:
        # 只保存可序列化的部分
        save_data = []
        for rd in all_run_data:
            boss_results = {}
            for bn, bi in rd["boss_results"].items():
                boss_results[bn] = {
                    "duration_s": bi["duration_s"],
                    "boss_id": bi["boss_id"],
                    "boss_only_count": bi["boss_only_count"],
                    "env_count": bi["env_count"],
                    "boss_skills": bi["boss_skills"],
                    "env_skills": bi["env_skills"],
                    "boss_casts_by_ability": bi["boss_casts_by_ability"],
                }
            save_data.append({
                "code": rd["code"],
                "fight_id": rd["fight_id"],
                "tank_name": rd["tank_name"],
                "keystone_level": rd["keystone_level"],
                "boss_results": boss_results,
            })
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n原始数据已保存: {output_file}")

    # Boss类型判断 + 安全窗口分析
    print(f"\n{'='*60}")
    print("Boss类型判断 & 安全窗口分析")
    print(f"{'='*60}")

    for boss_name in all_run_data[0]["boss_results"].keys() if all_run_data else []:
        print(f"\n--- {boss_name} ---")
        boss_casts_by_ability = defaultdict(list)

        for rd in all_run_data:
            if boss_name not in rd["boss_results"]:
                continue
            bi = rd["boss_results"][boss_name]
            run_name = f"{rd['tank_name']}(+{rd['keystone_level']})"
            for aname, timestamps in bi["boss_casts_by_ability"].items():
                for ts in timestamps:
                    boss_casts_by_ability[aname].append((run_name, ts, bi["duration_s"]))

        # Boss类型判断
        type_result = analyzer.determine_boss_type(boss_casts_by_ability)
        print(f"  类型: {type_result['judgment']}")

        # 安全窗口分析
        for rd in all_run_data:
            if boss_name not in rd["boss_results"]:
                continue
            bi = rd["boss_results"][boss_name]
            run_name = f"{rd['tank_name']}(+{rd['keystone_level']})"

            # Boss承伤事件
            boss_dmg = [e for e in rd["tank_events"]
                       if e.get("sourceID") == bi["boss_id"]
                       and bi["phase_start"] <= e.get("timestamp", 0) <= bi["phase_end"]]

            boss_casts = [c for c in rd["cast_events"] if c.get("sourceID") == bi["boss_id"]]

            safe_windows = analyzer.find_safe_windows(boss_dmg, bi["phase_start"], bi["phase_end"])
            safe_windows = analyzer.annotate_windows(
                safe_windows, boss_casts, bi["phase_start"], rd["ability_name_map"]
            )

            if safe_windows:
                print(f"  {run_name} 安全窗口:")
                for w in safe_windows:
                    print(f"    {w['start_offset_s']}s处 {w['duration_s']}s [{w['boss_action']}]")
            else:
                # 次级安全窗口
                dmg_by_ability = defaultdict(lambda: {"total": 0, "count": 0})
                for e in boss_dmg:
                    aid = e.get("abilityGameID", 0)
                    amt = e.get("amount", 0)
                    mit = e.get("mitigated", 0)
                    dmg_by_ability[aid]["total"] += amt + mit
                    dmg_by_ability[aid]["count"] += 1

                dot_candidates = [(aid, s["total"]/s["count"], s)
                                  for aid, s in dmg_by_ability.items() if s["count"] >= 5]
                if dot_candidates:
                    dot_candidates.sort(key=lambda x: x[1])
                    ignore_id = dot_candidates[0][0]
                    ignore_name = rd["ability_name_map"].get(ignore_id, f"技能{ignore_id}")
                    secondary = analyzer.find_secondary_safe_windows(
                        boss_dmg, bi["phase_start"], bi["phase_end"], {ignore_id}
                    )
                    sec_windows = analyzer.annotate_windows(
                        secondary["windows"], boss_casts, bi["phase_start"], rd["ability_name_map"]
                    )
                    print(f"  {run_name} 无常规窗口(忽略{ignore_name}后):")
                    for w in sec_windows:
                        print(f"    {w['start_offset_s']}s处 {w['duration_s']}s [{w['boss_action']}]")


if __name__ == "__main__":
    main()
