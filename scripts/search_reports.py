#!/usr/bin/env python3
"""搜索指定条件下的大秘境报告

用法:
    python search_reports.py                          # 搜索近3天所有M+报告
    python search_reports.py --days 7                 # 搜索近7天
    python search_reports.py --zone 47                # 指定区域ID
    python search_reports.py --encounter 10658        # 只看萨隆矿坑
    python search_reports.py --level 20               # 只看20层
    python search_reports.py --spec Guardian          # 只看有守护德的
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from wcl_analyzer.client import WCLClient
from wcl_analyzer.config import SEASON1_DUNGEONS, MPLUS_ZONES
from wcl_analyzer.utils import find_players_by_spec

def main():
    parser = argparse.ArgumentParser(description="搜索WCL大秘境报告")
    parser.add_argument("--days", type=int, default=3, help="搜索最近N天的报告")
    parser.add_argument("--zone", type=int, default=47, help="区域ID (默认47=M+ S1)")
    parser.add_argument("--encounter", type=int, default=None, help="副本遭遇ID，如10658=萨隆矿坑")
    parser.add_argument("--level", type=int, default=None, help="大秘境层数过滤")
    parser.add_argument("--spec", type=str, default=None, help="专精关键词，如Guardian/Protection")
    parser.add_argument("--kill", action="store_true", help="只看通关的")
    parser.add_argument("--limit", type=int, default=100, help="每页数量")
    args = parser.parse_args()

    client = WCLClient()
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    start_time = now - timedelta(days=args.days)
    start_ms = int(start_time.timestamp() * 1000)

    print(f"搜索范围: {start_time.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"区域: Zone {args.zone}")

    # 搜索报告
    all_reports = client.search_reports_paginated(args.zone, start_ms, limit=args.limit)
    print(f"找到 {len(all_reports)} 个报告，逐个检查...")

    results = []
    for i, report in enumerate(all_reports):
        code = report["code"]

        # 获取战斗列表
        try:
            fights = client.get_fights(code, keystone_level=args.level)
        except Exception:
            continue

        # 过历encounter
        if args.encounter:
            fights = [f for f in fights if f.get("encounterID") == args.encounter]

        # 过历kill
        if args.kill:
            fights = [f for f in fights if f.get("kill")]

        if not fights:
            continue

        # 检查专精
        spec_info = None
        if args.spec:
            try:
                master_data = client.get_master_data(code)
                actors = master_data.get("actors", [])
                matching = find_players_by_spec(actors, args.spec)
                if not matching:
                    continue
                spec_info = [{"name": m["name"], "id": m["id"], "spec": m.get("spec_cn", m.get("icon", ""))} for m in matching]
            except Exception:
                continue

        result = {
            "code": code,
            "title": report.get("title", ""),
            "fights": fights,
        }
        if spec_info:
            result["matched_specs"] = spec_info

        results.append(result)

        if (i + 1) % 20 == 0:
            print(f"  已检查 {i+1}/{len(all_reports)} 个报告，匹配 {len(results)} 个")

    print(f"\n=== 找到 {len(results)} 个匹配报告 ===")
    for r in results:
        print(f"\n报告: {r['code']} - {r['title']}")
        for f in r["fights"]:
            dungeon = SEASON1_DUNGEONS.get(f.get("encounterID"), f.get("name", "未知"))
            ksl = f.get("keystoneLevel", "?")
            kill = "✓" if f.get("kill") else "✗"
            duration = (f["endTime"] - f["startTime"]) / 1000
            print(f"  Fight {f['id']}: {dungeon} +{ksl} {kill} {duration:.0f}s")
        if r.get("matched_specs"):
            for s in r["matched_specs"]:
                print(f"  玩家: {s['name']} ({s['spec']})")


if __name__ == "__main__":
    main()
