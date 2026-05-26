#!/usr/bin/env python3
"""分析坦克在指定战斗中的承伤情况

用法:
    # 分析单场战斗
    python analyze_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank 1

    # 分析多场战斗
    python analyze_tank.py --runs "cAkFBvnmDKrChNTd:1:1,PH3WYhJfKyQxa7dv:5:1"

    # 从find_tank_runs的输出JSON分析
    python analyze_tank.py --from-json tank_runs.json --boss-damage --trash-damage

    # 只看Boss1承伤
    python analyze_tank.py --code cAkFBvnmDKrChNTd --fight 1 --tank 1 --boss-only 1

    # 查看报告中的玩家列表（确定tank ID）
    python analyze_tank.py --code cAkFBvnmDKrChNTd --list-players
"""

import argparse
import json
from wcl_analyzer.client import WCLClient
from wcl_analyzer.analyzer import analyze_full_tank_run
from wcl_analyzer.utils import (
    find_tank_actors, find_players_by_spec, identify_spec,
    build_actor_maps, format_number, format_duration, format_dps,
)
from wcl_analyzer.config import PIT_OF_SARON_BOSSES, PIT_OF_SARON_BOSS1_SKILLS, SEASON1_DUNGEONS


def _format_wan(value):
    """将伤害值格式化为万单位"""
    return f"{value / 10000:.0f}万"


def _print_skill_detail(sk, total_damage):
    """输出单个技能的详细信息"""
    pct = sk["total_damage"] / max(total_damage, 1) * 100
    print(f"    [{sk['damage_type']}] {sk['source_name']} - {sk['ability_name']}")
    print(f"      命中{sk['hit_count']}次 | 总伤害: {format_number(sk['total_damage'])} ({pct:.1f}%)")
    # 三维度伤害
    max_pre = sk.get("max_unmitigated", 0)
    max_post = sk.get("max_amount", 0)
    avg_post = sk.get("avg_amount", 0)
    print(f"      单次最大(减免前): {_format_wan(max_pre)} | "
          f"单次最大(减免后): {_format_wan(max_post)} | "
          f"单次平均(减免后): {_format_wan(avg_post)}")
    interval = sk["interval_stats"]
    if interval.get("avg_interval_s") is not None:
        print(f"      攻击间隔: {interval['avg_interval_s']:.2f}s "
              f"(最短{interval['min_interval_s']:.2f}s / 最长{interval['max_interval_s']:.2f}s)")
        print(f"      模式: {interval['pattern']} - {interval['description']}")


def main():
    parser = argparse.ArgumentParser(description="分析坦克承伤")
    parser.add_argument("--code", type=str, help="WCL报告代码")
    parser.add_argument("--fight", type=int, help="战斗ID")
    parser.add_argument("--tank", type=int, help="坦克actor ID")
    parser.add_argument("--runs", type=str, help="批量分析: code:fight:tank_id,...")
    parser.add_argument("--from-json", type=str, help="从find_tank_runs输出JSON读取")
    parser.add_argument("--list-players", action="store_true", help="列出报告中的玩家和专精")
    parser.add_argument("--boss-damage", action="store_true", help="输出Boss阶段承伤详情")
    parser.add_argument("--trash-damage", action="store_true", help="输出小怪阶段承伤详情")
    parser.add_argument("--boss-only", type=int, default=None, help="只看指定Boss编号(1/2/3)")
    args = parser.parse_args()

    client = WCLClient()

    if args.code and args.list_players:
        _list_players(client, args.code)
        return

    runs = []
    if args.from_json:
        with open(args.from_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            runs.append((item["report_code"], item["fight_id"], item["tank_id"], item["tank_name"]))
    elif args.runs:
        for part in args.runs.split(","):
            code, fight_id, tank_id = part.split(":")
            runs.append((code, int(fight_id), int(tank_id), f"Tank-{tank_id}"))
    elif args.code and args.fight and args.tank:
        runs.append((args.code, args.fight, args.tank, f"Tank-{args.tank}"))
    else:
        parser.print_help()
        return

    for code, fight_id, tank_id, tank_name in runs:
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
            continue

        if "error" in result:
            print(f"  错误: {result['error']}")
            continue

        dungeon = SEASON1_DUNGEONS.get(10658, "未知")
        ksl = result["keystone_level"]
        kill = "通关" if result["kill"] else "未通关"
        print(f"  {dungeon} +{ksl} | {result['duration_str']} | {kill}")

        ts = result["total_stats"]
        print(f"\n  --- 总承伤 ---")
        print(f"  总承伤: {format_number(ts['total'])} | 实际掉血: {format_number(ts['raw'])}")
        print(f"  减伤量: {format_number(ts['mitigated'])} | 减伤率: {ts['mitigation_rate']:.1f}%")

        # Boss阶段（技能维度+伤害类型）
        if args.boss_damage or args.boss_only:
            print(f"\n  --- Boss阶段承伤 ---")
            for boss_name, stats in result["boss_damage"].items():
                if args.boss_only:
                    boss_num = PIT_OF_SARON_BOSSES.get(boss_name)
                    if boss_num != args.boss_only:
                        continue
                print(f"\n  {boss_name} ({stats['duration_str']})")
                print(f"  总承伤: {format_number(stats['total'])} | DPS: {stats['dps_str']}")
                print(f"  减伤率: {stats['mitigation_rate']:.1f}%")

                # 技能详情
                if stats.get("skills"):
                    print(f"  技能详情:")
                    for sk in stats["skills"]:
                        _print_skill_detail(sk, stats["total"])

        # 小怪阶段（技能维度+攻击间隔）
        if args.trash_damage:
            print(f"\n  --- 小怪阶段承伤 ---")
            for phase_name, stats in result["trash_damage"].items():
                print(f"\n  {phase_name} ({stats['duration_str']})")
                print(f"  总承伤: {format_number(stats['total'])} | DPS: {stats['dps_str']}")

                # 技能详情
                if stats.get("skills"):
                    print(f"  技能详情（按伤害降序）:")
                    for sk in stats["skills"]:
                        _print_skill_detail(sk, stats["total"])


def _list_players(client, code):
    """列出报告中的玩家和专精"""
    master_data = client.get_master_data(code)
    actors = master_data.get("actors", [])

    print(f"\n报告 {code} 中的玩家:")
    print(f"{'ID':>4}  {'名称':<20}  {'icon':<25}  {'专精':<10}  {'坦克':>4}")
    print("-" * 70)

    for actor in actors:
        if actor.get("type") != "Player":
            continue
        spec_cn, is_tank = identify_spec(actor)
        print(f"{actor['id']:>4}  {actor['name']:<20}  {actor.get('icon', ''):<25}  "
              f"{spec_cn or '?':<10}  {'✓' if is_tank else '':>4}")


if __name__ == "__main__":
    main()
