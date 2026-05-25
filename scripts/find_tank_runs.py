#!/usr/bin/env python3
"""查找指定副本和坦克专精的大秘境通关记录

用法:
    python find_tank_runs.py                                # 默认：萨隆矿坑 + 熊坦 + 近3天
    python find_tank_runs.py --dungeon 10658 --spec Guardian --level 20
    python find_tank_runs.py --spec Protection              # 查防骑
    python find_tank_runs.py --days 7 --level 22            # 近7天22层以上
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from wcl_analyzer.client import WCLClient
from wcl_analyzer.config import SEASON1_DUNGEONS
from wcl_analyzer.utils import find_tank_actors, find_players_by_spec, identify_spec

def main():
    parser = argparse.ArgumentParser(description="查找指定副本和坦克专精的大秘境记录")
    parser.add_argument("--dungeon", type=int, default=10658, help="副本遭遇ID (默认10658=萨隆矿坑)")
    parser.add_argument("--spec", type=str, default="Guardian", help="专精关键词 (默认Guardian=熊坦)")
    parser.add_argument("--level", type=int, default=None, help="最低层数")
    parser.add_argument("--days", type=int, default=3, help="搜索最近N天")
    parser.add_argument("--kill-only", action="store_true", help="只看通关记录")
    parser.add_argument("--max-results", type=int, default=10, help="最多返回结果数")
    args = parser.parse_args()

    client = WCLClient()
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_time = now - timedelta(days=args.days)
    start_ms = int(start_time.timestamp() * 1000)

    dungeon_name = SEASON1_DUNGEONS.get(args.dungeon, f"Encounter {args.dungeon}")
    print(f"搜索: {dungeon_name}, 专精含'{args.spec}', 近{args.days}天")

    # Step 1: 搜索排名获取报告代码
    print("\nStep 1: 通过排名获取报告列表...")
    try:
        class_name = _spec_to_class(args.spec)
        rankings = client.get_character_rankings(
            args.dungeon, class_name, args.spec, metric="dps"
        )
        ranking_list = rankings.get("rankings", [])
        print(f"  获取到 {len(ranking_list)} 条排名记录")

        # 过滤时间范围
        recent_rankings = []
        for r in ranking_list:
            start_ts = r.get("startTime", 0)
            if start_ts >= start_ms:
                recent_rankings.append(r)
        print(f"  近{args.days}天: {len(recent_rankings)} 条")
    except Exception as e:
        print(f"  排名查询失败: {e}")
        recent_rankings = []

    # Step 2: 翻页搜索M+报告
    print("\nStep 2: 搜索M+报告...")
    all_reports = client.search_reports_paginated(47, start_ms, max_pages=15)
    print(f"  找到 {len(all_reports)} 个报告")

    # Step 3: 逐个检查
    print("\nStep 3: 逐个检查报告...")
    matched_runs = []
    checked = 0

    for report in all_reports:
        code = report["code"]
        try:
            fights = client.get_fights(code)
            master_data = client.get_master_data(code)
        except Exception:
            continue

        actors = master_data.get("actors", [])

        # 查找匹配专精的玩家
        matched_players = find_players_by_spec(actors, args.spec)
        if not matched_players:
            continue

        # 查找匹配副本的战斗
        dungeon_fights = [f for f in fights if f.get("encounterID") == args.dungeon]

        for fight in dungeon_fights:
            # 层数过滤
            if args.level and (fight.get("keystoneLevel") or 0) < args.level:
                continue

            # 通关过滤
            if args.kill_only and not fight.get("kill"):
                continue

            duration = (fight["endTime"] - fight["startTime"]) / 1000
            for player in matched_players:
                matched_runs.append({
                    "report_code": code,
                    "fight_id": fight["id"],
                    "tank_name": player["name"],
                    "tank_id": player["id"],
                    "keystone_level": fight.get("keystoneLevel"),
                    "kill": fight.get("kill"),
                    "duration_s": duration,
                    "spec_cn": player.get("spec_cn", ""),
                })

        checked += 1
        if checked % 30 == 0:
            print(f"  已检查 {checked}/{len(all_reports)}, 匹配 {len(matched_runs)} 条")

        if len(matched_runs) >= args.max_results:
            break

    # 也检查排名来源的报告
    for r in recent_rankings:
        report_info = r.get("report", {})
        code = report_info.get("code") if isinstance(report_info, dict) else None
        if not code:
            continue
        # 避免重复
        if any(m["report_code"] == code for m in matched_runs):
            continue
        try:
            fights = client.get_fights(code)
            master_data = client.get_master_data(code)
        except Exception:
            continue

        actors = master_data.get("actors", [])
        matched_players = find_players_by_spec(actors, args.spec)
        dungeon_fights = [f for f in fights if f.get("encounterID") == args.dungeon]

        for fight in dungeon_fights:
            if args.level and (fight.get("keystoneLevel") or 0) < args.level:
                continue
            if args.kill_only and not fight.get("kill"):
                continue
            duration = (fight["endTime"] - fight["startTime"]) / 1000
            for player in matched_players:
                matched_runs.append({
                    "report_code": code,
                    "fight_id": fight["id"],
                    "tank_name": player["name"],
                    "tank_id": player["id"],
                    "keystone_level": fight.get("keystoneLevel"),
                    "kill": fight.get("kill"),
                    "duration_s": duration,
                    "spec_cn": player.get("spec_cn", ""),
                })

    # 输出结果
    print(f"\n=== 找到 {len(matched_runs)} 条匹配记录 ===")
    for run in matched_runs:
        ksl = run["keystone_level"]
        kill = "通关" if run["kill"] else "未通关"
        print(f"  {run['tank_name']}({run['spec_cn']}) | {dungeon_name} +{ksl} | "
              f"{run['duration_s']:.0f}s | 报告: {run['report_code']} Fight {run['fight_id']} | {kill}")

    # 保存JSON供后续分析使用
    output_file = "tank_runs.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(matched_runs, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {output_file}")


def _spec_to_class(spec_keyword):
    """将专精关键词映射到WCL职业名"""
    mapping = {
        "Guardian": "Druid",
        "Protection": "Warrior",  # 也可能是Paladin
        "Blood": "DeathKnight",
        "Brewmaster": "Monk",
        "Vengeance": "DemonHunter",
    }
    return mapping.get(spec_keyword, "Druid")


if __name__ == "__main__":
    main()
