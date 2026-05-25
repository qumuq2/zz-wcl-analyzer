#!/usr/bin/env python3
"""萨隆矿坑熊坦承伤分析 - 端到端示例

这个脚本演示了完整的分析流程：
1. 搜索近3天有守护德的萨隆矿坑报告
2. 筛选通关记录
3. 分析Boss 1承伤和Boss 2后小怪承伤

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

    # 如果直接指定了报告，直接分析
    if args.code and args.fight and args.tank_id:
        _analyze_single(client, args.code, args.fight, args.tank_id, f"Tank-{args.tank_id}")
        return

    # 否则搜索
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_time = now - timedelta(days=args.days)
    start_ms = int(start_time.timestamp() * 1000)

    print(f"搜索近{args.days}天萨隆矿坑守护德通关记录...")

    # Step 1: 通过排名获取报告
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
                    recent.append({
                        "code": code,
                        "name": r.get("name", "?"),
                        "server": r.get("server", "?"),
                        "score": r.get("total", 0),
                    })
        print(f"   近{args.days}天: {len(recent)} 条排名")
    except Exception as e:
        print(f"   排名查询失败: {e}")
        recent = []

    # Step 2: 检查每个报告
    print("\n2. 逐个检查报告中的通关记录...")
    bear_runs = []

    for item in recent:
        code = item["code"]
        try:
            fights = client.get_fights(code)
            master_data = client.get_master_data(code)
        except Exception:
            continue

        # 找萨隆矿坑通关记录
        pos_fights = [
            f for f in fights
            if f.get("encounterID") == 10658 and f.get("kill")
        ]

        if not pos_fights:
            continue

        # 层数过滤
        if args.level:
            pos_fights = [f for f in pos_fights if (f.get("keystoneLevel") or 0) >= args.level]

        # 找守护德
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
        print("\n没有找到符合条件的记录。尝试降低层数要求或扩大时间范围。")
        return

    # Step 3: 分析前N场
    print(f"\n3. 分析前 {min(args.max_runs, len(bear_runs))} 场...")
    for run in bear_runs[:args.max_runs]:
        _analyze_single(client, run["code"], run["fight_id"],
                        run["tank_id"], run["tank_name"])


def _analyze_single(client, code, fight_id, tank_id, tank_name):
    """分析单场战斗"""
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

    # Boss 1 承伤
    boss1_name = "熔炉之主加弗斯特"
    if boss1_name in result["boss_damage"]:
        b1 = result["boss_damage"][boss1_name]
        print(f"\n  --- Boss 1 ({boss1_name}) 承伤 ---")
        print(f"  时长: {b1['duration_str']}")
        print(f"  总承伤: {format_number(b1['total'])} | DPS: {b1['dps_str']}")
        print(f"  实际掉血: {format_number(b1['raw'])} | 减伤: {format_number(b1['mitigated'])}")
        print(f"  减伤率: {b1['mitigation_rate']:.1f}%")
        if b1.get("by_ability_detail"):
            print(f"  技能分布:")
            for skill, detail in sorted(b1["by_ability_detail"].items(), key=lambda x: -x[1]["damage"]):
                print(f"    {skill}: {format_number(detail['damage'])} ({detail['pct']:.1f}%)")

    # Boss 2后小怪承伤
    trash_key = "Boss2后小怪"
    if trash_key in result["trash_damage"]:
        t2 = result["trash_damage"][trash_key]
        print(f"\n  --- Boss 2后小怪 承伤 ---")
        print(f"  时长: {t2['duration_str']}")
        print(f"  总承伤: {format_number(t2['total'])} | DPS: {t2['dps_str']}")
        if t2.get("by_source_detail"):
            print(f"  怪物来源:")
            for source, detail in sorted(t2["by_source_detail"].items(), key=lambda x: -x[1]["damage"])[:8]:
                print(f"    {source}: {format_number(detail['damage'])} ({detail['pct']:.1f}%)")


if __name__ == "__main__":
    main()
