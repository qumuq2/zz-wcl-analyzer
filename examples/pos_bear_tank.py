#!/usr/bin/env python3
"""萨隆矿坑熊坦承伤分析 - 端到端示例

用法:
    python pos_bear_tank.py
    python pos_bear_tank.py --days 7 --level 20
    python pos_bear_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank-id 1
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from wcl_analyzer.client import WCLClient
from wcl_analyzer.analyzer import analyze_full_tank_run
from wcl_analyzer.utils import (
    find_players_by_spec, build_actor_maps, format_number,
    identify_spec,
)
from wcl_analyzer.config import (
    PIT_OF_SARON_BOSSES, PIT_OF_SARON_BOSS1_SKILLS, SEASON1_DUNGEONS
)

def main():
    parser = argparse.ArgumentParser(description="萨隆矿坑熊坦承伤分析")
    parser.add_argument("--days", type=int, default=3, help="搜索最近N天")
    parser.add_argument("--level", type=int, default=None, help="最低层数")
    parser.add_argument("--code", type=str, help="直接指定报告代码")
    parser.add_argument("--fight", type=int, help="直接指定战斗ID")
    parser.add_argument("--tank-id", type=int, help="直接指定坦克ID")
    parser.add_argument("--max-runs", type=int, default=5, help="最多分析几场")
    args = parser.parse_args()

    client = WCLClient()

    if args.code and args.fight and args.tank_id:
        _analyze_single(client, args.code, args.fight, args.tank_id, f"Tank-{args.tank_id}")
        return

    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_time = now - timedelta(days=args.days)
    start_ms = int(start_time.timestamp() * 1000)

    print(f"搜索近{args.days}天萨隆矿坑守护德通关记录...")

    print("\n1. 查询守护德排名...")
    try:
        rankings = client.get_character_rankings(10658, "Druid", "Guardian", metric="dps")
        ranking_list = rankings.get("rankings", [])
        recent = []
        for r in ranking_list:
            if r.get("startTime", 0) >= start_ms:
                report = r.get("report", {})
                code = report.get("code") if isinstance(report, dict) else None
                if code:
                    recent.append({"code": code, "name": r.get("name", "?")})
        print(f"   近{args.days}天: {len(recent)} 条排名")
    except Exception as e:
        print(f"   排名查询失败: {e}")
        recent = []

    print("\n2. 逐个检查报告中的通关记录...")
    bear_runs = []

    for item in recent:
        code = item["code"]
        try:
            fights = client.get_fights(code)
            master_data = client.get_master_data(code)
        except Exception:
            continue

        pos_fights = [f for f in fights if f.get("encounterID") == 10658 and f.get("kill")]
        if not pos_fights:
            continue
        if args.level:
            pos_fights = [f for f in pos_fights if (f.get("keystoneLevel") or 0) >= args.level]

        actors = master_data.get("actors", [])
        guardians = find_players_by_spec(actors, "Guardian")

        for fight in pos_fights:
            for guardian in guardians:
                bear_runs.append({
                    "code": code,
                    "fight_id": fight["id"],
                    "tank_id": guardian["id"],
                    "tank_name": guardian["name"],
                    "keystone_level": fight.get("keystoneLevel"),
                    "duration_s": (fight["endTime"] - fight["startTime"]) / 1000,
                })

    print(f"   找到 {len(bear_runs)} 条通关记录")
    if not bear_runs:
        print("\n没有找到符合条件的记录。")
        return

    print(f"\n3. 分析前 {min(args.max_runs, len(bear_runs))} 场...")
    for run in bear_runs[:args.max_runs]:
        _analyze_single(client, run["code"], run["fight_id"],
                        run["tank_id"], run["tank_name"])


def _analyze_single(client, code, fight_id, tank_id, tank_name):
    """分析单场战斗 - Boss和小怪分别输出，互不对比"""
    print(f"\n{'='*60}")
    print(f"分析: {tank_name} (报告 {code}, Fight {fight_id})")

    try:
        result = analyze_full_tank_run(
            client, code, fight_id, tank_id, tank_name,
            boss_names=PIT_OF_SARON_BOSSES,
            skill_map=PIT_OF_SARON_BOSS1_SKILLS,
        )
    except Exception as e:
        print(f"  分析失败: {e}")
        return

    if "error" in result:
        print(f"  错误: {result['error']}")
        return

    ksl = result["keystone_level"]
    kill = "通关" if result["kill"] else "未通关"
    print(f"  萨隆矿坑 +{ksl} | {result['duration_str']} | {kill}")

    # === Boss 1 承伤分析 ===
    boss1_name = "熔炉之主加弗斯特"
    if boss1_name in result["boss_damage"]:
        b1 = result["boss_damage"][boss1_name]
        print(f"\n  ═══ Boss 1 ({boss1_name}) 承伤 ═══")
        print(f"  时长: {b1['duration_str']} | 总承伤: {format_number(b1['total'])} | DPS: {b1['dps_str']}")
        print(f"  减伤率: {b1['mitigation_rate']:.1f}%")

        if b1.get("skills"):
            print(f"\n  技能详情:")
            for sk in b1["skills"]:
                pct = sk["total_damage"] / max(b1["total"], 1) * 100
                print(f"  [{sk['damage_type']}] {sk.get('ability_name', sk['ability_id'])} (ID:{sk['ability_id']})")
                print(f"    命中{sk['hit_count']}次 | 总伤害: {format_number(sk['total_damage'])} ({pct:.1f}%)")
                print(f"    单次最大(未减免): {format_number(sk['max_unmitigated'])} | 平均: {format_number(sk['avg_unmitigated'])}")
                interval = sk["interval_stats"]
                if interval.get("avg_interval_s") is not None:
                    print(f"    攻击间隔: {interval['avg_interval_s']:.2f}s "
                          f"(最短{interval['min_interval_s']:.2f}s / 最长{interval['max_interval_s']:.2f}s)")
                    print(f"    模式: {interval['description']}")

    # === Boss 2后小怪 承伤分析 ===
    trash_key = "Boss2后小怪"
    if trash_key in result["trash_damage"]:
        t2 = result["trash_damage"][trash_key]
        print(f"\n  ═══ Boss 2后小怪 承伤 ═══")
        print(f"  时长: {t2['duration_str']} | 总承伤: {format_number(t2['total'])} | DPS: {t2['dps_str']}")

        if t2.get("skills"):
            print(f"\n  技能详情（按伤害降序）:")
            for sk in t2["skills"]:
                pct = sk["total_damage"] / max(t2["total"], 1) * 100
                print(f"  [{sk['damage_type']}] {sk['source_name']} - {sk.get('ability_name', sk['ability_id'])} (ID:{sk['ability_id']})")
                print(f"    命中{sk['hit_count']}次 | 总伤害: {format_number(sk['total_damage'])} ({pct:.1f}%)")
                print(f"    单次最大(未减免): {format_number(sk['max_unmitigated'])} | 平均(未减免): {format_number(sk['avg_unmitigated'])}")
                interval = sk["interval_stats"]
                if interval.get("avg_interval_s") is not None:
                    print(f"    攻击间隔: {interval['avg_interval_s']:.2f}s "
                          f"(最短{interval['min_interval_s']:.2f}s / 最长{interval['max_interval_s']:.2f}s)")
                print(f"    模式: {interval['description']}")


if __name__ == "__main__":
    main()
