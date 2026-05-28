#!/usr/bin/env python3
"""通用M+副本Boss技能分析

用法:
    python3 analyze_dungeon.py <副本英文名>

支持的副本:
    saron     - 萨隆矿坑 (10658)
    nexus     - 枢纽节点塞纳斯 (12915)
    academy   - 艾杰斯亚学院 (112526)
    mesar     - 迈萨拉洞窟 (12874)
    vortex    - 通天峰 (61209)
    rookery   - 风行者之塔 (12805)
    magister  - 魔导师平台 (12811)
    consulate - 执政团之座 (361753)

也可直接 import 使用:
    from analyze_dungeon import analyze_dungeon, DUNGEON_CONFIGS
    analyze_dungeon("academy")
"""

import json
import sys
import time
from collections import defaultdict

from wcl_analyzer.client import WCLClient
from wcl_analyzer.boss_timeline import BossTimelineAnalyzer
from wcl_analyzer.utils import (
    build_actor_maps, filter_events_by_target, filter_events_by_time,
    analyze_skills, format_damage_type,
)

# ═══════════════════════════════════════════════════════════════
# 各副本配置：encounter_id, 显示名, +20层熊坦记录
# ═══════════════════════════════════════════════════════════════

DUNGEON_CONFIGS = {
    "saron": {
        "encounter_id": 10658,
        "name_cn": "萨隆矿坑",
        "runs": [
            # 待补充
        ],
    },
    "nexus": {
        "encounter_id": 12915,
        "name_cn": "枢纽节点塞纳斯",
        "runs": [
            {"code": "7abzDXnKPwZhyJ21", "fight_id": 28, "tank_id": 707, "tank_name": "張義德"},
            {"code": "hz2jmaWgq7t6JCBr", "fight_id": 5, "tank_id": 109, "tank_name": "琳琳大魔王"},
            {"code": "8KGRg9dVy6T3PxmM", "fight_id": 15, "tank_id": 242, "tank_name": "Xiaofua"},
            {"code": "vaJzZ4HQT13pm6gL", "fight_id": 15, "tank_id": 2, "tank_name": "泡泡鱼子"},
        ],
    },
    "academy": {
        "encounter_id": 112526,
        "name_cn": "艾杰斯亚学院",
        "runs": [
            {"code": "fDr2mFb4H8j3NvyW", "fight_id": 1, "tank_id": 2, "tank_name": "Rouka"},
            {"code": "C2QRz71ZnVxKJh98", "fight_id": 2, "tank_id": 172, "tank_name": "Surtakdru"},
            {"code": "kVCwY6QTM9Kfn3px", "fight_id": 7, "tank_id": 383, "tank_name": "Urusura"},
            {"code": "W8BjfXHmDdV6CNpv", "fight_id": 2, "tank_id": 1, "tank_name": "Бефи"},
        ],
    },
    "mesar": {
        "encounter_id": 12874,
        "name_cn": "迈萨拉洞窟",
        "runs": [
            {"code": "2YGjKt9MNTQkB6qh", "fight_id": 10, "tank_id": 123, "tank_name": "Northtale"},
            {"code": "r4zYKhGVt1Lyj7nF", "fight_id": 1, "tank_id": 2, "tank_name": "过去丶"},
            {"code": "ZFB91HyKdtQLC8kg", "fight_id": 64, "tank_id": 153, "tank_name": "嘎嘎鲍莉"},
        ],
    },
    "vortex": {
        "encounter_id": 61209,
        "name_cn": "通天峰",
        "runs": [
            {"code": "4q93RPVMLwX1TCpD", "fight_id": 3, "tank_id": 3, "tank_name": "Eroswinia"},
            {"code": "W8BjfXHmDdV6CNpv", "fight_id": 9, "tank_id": 1, "tank_name": "Бефи"},
            {"code": "CYZ7kwGAMdJzfh4v", "fight_id": 3, "tank_id": 187, "tank_name": "간디루"},
        ],
    },
    "rookery": {
        "encounter_id": 12805,
        "name_cn": "风行者之塔",
        "runs": [
            {"code": "7d1HnRhWXgTftMAK", "fight_id": 12, "tank_id": 1000, "tank_name": "Treediddy"},
            {"code": "6QNZpfcz8HWg31hT", "fight_id": 10, "tank_id": 1, "tank_name": "Jaxzdruid"},
        ],
    },
    "magister": {
        "encounter_id": 12811,
        "name_cn": "魔导师平台",
        "runs": [
            {"code": "W8BjfXHmDdV6CNpv", "fight_id": 7, "tank_id": 1, "tank_name": "Бефи"},
            # 更多记录待搜索
        ],
    },
    "consulate": {
        "encounter_id": 361753,
        "name_cn": "执政团之座",
        "runs": [
            # 待补充
        ],
    },
}

EXCLUDED_BOSSES = {"Environment"}

# ═══════════════════════════════════════════════════════════════
# 搜索+20层熊坦记录
# ═══════════════════════════════════════════════════════════════

def search_bear_runs(client, encounter_id, days=14, max_reports=200, min_bear_runs=5):
    """搜索指定副本的+20层熊坦记录

    Returns:
        list of {"code", "fight_id", "tank_id", "tank_name"}
    """
    import datetime
    from wcl_analyzer.utils import find_players_by_spec

    now = datetime.datetime.now()
    start_time = int((now - datetime.timedelta(days=days)).timestamp() * 1000)

    cursor = float(start_time)
    bear_runs = []
    checked_codes = set()

    for page in range(10):
        reports = client.search_reports(47, cursor, limit=100)
        if not reports:
            break

        for r in reports:
            code = r['code']
            if code in checked_codes:
                continue
            checked_codes.add(code)

            try:
                fights = client.get_fights(code)
                has_target = any(
                    f.get('encounterID') == encounter_id and f.get('keystoneLevel') == 20
                    for f in fights
                )
                if not has_target:
                    time.sleep(0.05)
                    continue

                master = client.get_master_data(code)
                # 找熊坦（兼容icon只显示"Druid"的情况）
                all_tanks = find_players_by_spec(master.get('actors', []), 'Guardian')
                druids = [a for a in master.get('actors', [])
                          if a.get('type') == 'Player' and a.get('icon') == 'Druid']
                all_cands = {t['id']: t for t in (all_tanks + druids)}

                for f in fights:
                    if f.get('encounterID') == encounter_id and f.get('keystoneLevel') == 20:
                        fid = f['id']
                        events = client.get_all_events(code, [fid], "DamageTaken", max_pages=3)
                        tank_dmg = {}
                        for e in events:
                            tid = e.get('targetID')
                            if tid in all_cands:
                                name = all_cands[tid]['name']
                                tank_dmg[name] = tank_dmg.get(name, 0) + e.get('amount', 0)

                        if tank_dmg:
                            main_tank = max(tank_dmg, key=tank_dmg.get)
                            tank_id = next(t['id'] for t in all_cands.values() if t['name'] == main_tank)
                            total = sum(tank_dmg.values())
                            if total > 30000000:  # 至少30M承伤
                                bear_runs.append({
                                    'code': code, 'fight_id': fid,
                                    'tank_id': tank_id, 'tank_name': main_tank,
                                })
                                print(f"  找到: {main_tank} code={code} fight={fid}")

                        time.sleep(0.3)
                time.sleep(0.1)
            except Exception as e:
                pass

            if len(checked_codes) >= max_reports:
                break
            if len(bear_runs) >= min_bear_runs:
                break

        if not reports or len(bear_runs) >= min_bear_runs:
            break
        cursor = float(reports[-1]['startTime'])

    return bear_runs


# ═══════════════════════════════════════════════════════════════
# 核心分析逻辑
# ═══════════════════════════════════════════════════════════════

def _format_wan(value):
    return f"{value / 10000:.0f}万"


def get_boss_death_time(client, code, fight_id, boss_id):
    """用DamageDone to boss确定boss死亡时间"""
    dmg_to_boss = client.get_all_events(
        code, [fight_id], "DamageDone", target_id=boss_id, max_pages=30
    )
    if not dmg_to_boss:
        return None
    last_dmg = max(e.get("timestamp", 0) for e in dmg_to_boss)
    return last_dmg + 2000  # +2s缓冲


def analyze_single_run(client, analyzer, code, fight_id, tank_id, tank_name, ksl=20):
    """分析一场战斗中所有Boss的承伤"""
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
    boss_phases_old = data["boss_phases"]
    fight_start = data["fight_start"]

    boss_results = {}
    for boss_name, phase_info in boss_phases_old.items():
        if boss_name in EXCLUDED_BOSSES:
            continue

        boss_id = phase_info["boss_id"]

        # 起点：boss首次cast（进战斗时刻）
        boss_casts = [c for c in cast_events if c.get("sourceID") == boss_id]
        if boss_casts:
            phase_start = min(c.get("timestamp", 0) for c in boss_casts)
        else:
            phase_start = phase_info["start"]

        # 终点：boss死亡（末次DamageDone to boss + 2s）
        death_time = get_boss_death_time(client, code, fight_id, boss_id)
        if death_time:
            phase_end = death_time
        else:
            phase_end = phase_info["end"]

        duration_ms = phase_end - phase_start

        boss_phase_events = filter_events_by_time(tank_events, phase_start, phase_end)
        boss_only_events = [e for e in boss_phase_events if e.get("sourceID") == boss_id]
        env_events = [e for e in boss_phase_events if e.get("sourceID") != boss_id]

        boss_skills = analyze_skills(boss_only_events, actor_name_map, ability_type_map, ability_map)
        env_skills = analyze_skills(env_events, actor_name_map, ability_type_map, ability_map)

        boss_results[boss_name] = {
            "duration_ms": duration_ms,
            "duration_s": round(duration_ms / 1000, 1),
            "boss_id": boss_id,
            "boss_skills": boss_skills,
            "env_skills": env_skills,
            "boss_only_count": len(boss_only_events),
            "env_count": len(env_events),
            "phase_start": phase_start,
            "phase_end": phase_end,
        }

        time.sleep(0.5)

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
        "fight_start": fight_start,
    }


# ═══════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════

def generate_report(all_run_data, dungeon_name):
    """生成Markdown格式的Boss技能分析报告"""
    total_runs = len(all_run_data)
    min_appear = max(2, total_runs // 2 + 1)

    # 收集Boss名称，按首次出现顺序
    boss_order = []
    seen_bosses = set()
    for rd in all_run_data:
        for bn in rd["boss_results"]:
            if bn not in seen_bosses:
                boss_order.append(bn)
                seen_bosses.add(bn)

    # 一致性统计：非Boss来源在各场中的出现次数
    source_appearance = defaultdict(lambda: defaultdict(set))
    for ri, rd in enumerate(all_run_data):
        for boss_name, bi in rd["boss_results"].items():
            for sk in bi["env_skills"]:
                source_appearance[boss_name][sk["source_name"]].add(ri)

    lines = []
    lines.append(f"# {dungeon_name} Boss技能分析\n")
    lines.append(f"> 数据来源：{total_runs}场+20层熊坦(Druid-Guardian)限时记录")
    lines.append(f"> 战斗窗口：起点=boss首次cast（进战斗），终点=boss末次受击+2s（死亡）")
    lines.append(f"> 伤害维度：单次最大(减免前) / 单次最大(减免后) / 单次平均(减免前) / 单次平均(减免后)")
    lines.append(f"> 一致性过滤：非Boss来源需在≥{min_appear}场出现才纳入\n")

    for boss_name in boss_order:
        boss_run_count = sum(1 for rd in all_run_data if boss_name in rd["boss_results"])

        lines.append("---")
        lines.append(f"## {boss_name}\n")

        all_skills = defaultdict(list)
        for rd in all_run_data:
            if boss_name not in rd["boss_results"]:
                continue
            bi = rd["boss_results"][boss_name]

            for sk in bi["boss_skills"]:
                key = (sk["source_name"], sk["ability_name"], sk["damage_type"])
                all_skills[key].append(("boss", sk))

            for sk in bi["env_skills"]:
                src_name = sk["source_name"]
                # 一致性过滤
                threshold = min(min_appear, max(2, boss_run_count // 2 + 1))
                if len(source_appearance[boss_name][src_name]) < threshold:
                    continue
                key = (sk["source_name"], sk["ability_name"], sk["damage_type"])
                all_skills[key].append(("env", sk))

        if not all_skills:
            lines.append("无数据\n")
            continue

        table_rows = []
        total_dmg_all = 0
        for (src, abl, dtype), entries in all_skills.items():
            is_boss_src = entries[0][0] == "boss"
            skills = [e[1] for e in entries]

            total_dmg = sum(s["total_damage"] for s in skills)
            total_dmg_all += total_dmg
            hit_counts = [s["hit_count"] for s in skills]
            max_pre = [s["max_unmitigated"] for s in skills]
            max_post = [s["max_amount"] for s in skills]
            avg_pre = [s["avg_unmitigated"] for s in skills]
            avg_post = [s["avg_amount"] for s in skills]
            note = skills[0].get("note", "")

            def fmt_range(vals):
                mn, mx = min(vals), max(vals)
                return _format_wan(mn) if mn == mx else f"{_format_wan(mn)}-{_format_wan(mx)}"

            def fmt_hits(vals):
                mn, mx = min(vals), max(vals)
                return str(mn) if mn == mx else f"{mn}-{mx}"

            pattern = skills[0].get("interval_stats", {}).get("description", "")
            if not pattern:
                avg_int = skills[0].get("interval_stats", {}).get("avg_interval_s")
                if avg_int and avg_int < 3:
                    pattern = f"快速攻击，约{avg_int:.1f}秒/次"
                elif avg_int:
                    pattern = f"约{avg_int:.1f}秒/次"

            table_rows.append({
                "is_boss": is_boss_src,
                "source": src,
                "ability": abl,
                "dtype": dtype,
                "total_dmg": total_dmg,
                "hits": fmt_hits(hit_counts),
                "max_pre": fmt_range(max_pre),
                "max_post": fmt_range(max_post),
                "avg_pre": fmt_range(avg_pre),
                "avg_post": fmt_range(avg_post),
                "pattern": pattern,
                "note": note,
            })

        table_rows.sort(key=lambda x: -x["total_dmg"])

        lines.append("| 技能 | 来源 | 类型 | 伤害占比 | 命中次数 | 单次最大(减免前) | 单次最大(减免后) | 单次平均(减免前) | 单次平均(减免后) | 攻击模式 |")
        lines.append("|------|------|------|---------|---------|----------------|----------------|----------------|----------------|---------|")

        for r in table_rows:
            pct = r["total_dmg"] / max(total_dmg_all, 1) * 100
            pct_str = f"{pct:.0f}%" if pct >= 1 else f"{pct:.1f}%"

            if r["is_boss"]:
                ability = f"**{r['ability']}**"
                source = f"**{r['source']}**"
                dtype = f"**{r['dtype']}**"
                hits = f"**{r['hits']}**"
                max_pre = f"**{r['max_pre']}**"
                max_post = f"**{r['max_post']}**"
                avg_pre = f"**{r['avg_pre']}**"
                avg_post = f"**{r['avg_post']}**"
                pct_str = f"**{pct_str}**"
            else:
                ability = r["ability"]
                source = r["source"]
                dtype = r["dtype"]
                hits = r["hits"]
                max_pre = r["max_pre"]
                max_post = r["max_post"]
                avg_pre = r["avg_pre"]
                avg_post = r["avg_post"]

            note_suffix = f" {r['note']}" if r["note"] else ""
            lines.append(
                f"| {ability} | {source} | {dtype} | {pct_str} | {hits} | "
                f"{max_pre} | {max_post} | {avg_pre} | {avg_post} | {r['pattern']}{note_suffix} |"
            )

        lines.append(f"\n*该Boss共{boss_run_count}场数据*\n")

    return "\n".join(lines), boss_order


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def analyze_dungeon(dungeon_key, search=False, search_days=14, output_dir="/tmp"):
    """分析指定副本

    Args:
        dungeon_key: 副本短名 (如 "academy")
        search: 是否自动搜索+20层熊坦记录（忽略配置中的runs）
        search_days: 搜索天数范围
        output_dir: 报告输出目录

    Returns:
        (report_text, boss_order, all_run_data)
    """
    if dungeon_key not in DUNGEON_CONFIGS:
        print(f"未知副本: {dungeon_key}")
        print(f"支持的副本: {', '.join(DUNGEON_CONFIGS.keys())}")
        return None, None, None

    config = DUNGEON_CONFIGS[dungeon_key]
    dungeon_name = config["name_cn"]
    encounter_id = config["encounter_id"]

    client = WCLClient()
    analyzer = BossTimelineAnalyzer(client)

    # 获取runs列表
    if search:
        print(f"搜索: {dungeon_name}(+20层熊坦, {search_days}天内)...")
        runs = search_bear_runs(client, encounter_id, days=search_days, min_bear_runs=5)
        if not runs:
            print("未找到有效记录")
            return None, None, None
        # 打印找到的记录，方便后续写入配置
        print(f"\n找到{len(runs)}条记录，可添加到DUNGEON_CONFIGS['{dungeon_key}']['runs']:")
        for r in runs:
            print(f"  {{'code': '{r['code']}', 'fight_id': {r['fight_id']}, "
                  f"'tank_id': {r['tank_id']}, 'tank_name': '{r['tank_name']}'}},")
    else:
        runs = config["runs"]

    if not runs:
        print(f"配置中无runs，请先搜索: python3 analyze_dungeon.py {dungeon_key} --search")
        return None, None, None

    # 逐场分析
    print(f"\n分析: {dungeon_name} ({len(runs)}场+20层熊坦)")
    all_run_data = []

    for run in runs:
        print(f"\n{'─'*40}")
        print(f"分析: {run['tank_name']} ...")
        try:
            rd = analyze_single_run(
                client, analyzer,
                run["code"], run["fight_id"], run["tank_id"],
                run["tank_name"], ksl=20,
            )
            if rd:
                all_run_data.append(rd)
                for bn, bi in rd["boss_results"].items():
                    offset_s = (bi["phase_start"] - rd["fight_start"]) / 1000
                    offset_e = (bi["phase_end"] - rd["fight_start"]) / 1000
                    print(f"  {bn}: offset {offset_s:.0f}s~{offset_e:.0f}s ({bi['duration_s']}s)")
                    print(f"    Boss技能: {len(bi['boss_skills'])}个, 其他来源: {len(bi['env_skills'])}个")
            time.sleep(0.5)
        except Exception as e:
            print(f"  分析失败: {e}")
            import traceback
            traceback.print_exc()

    if not all_run_data:
        print("无有效数据")
        return None, None, None

    # 生成报告
    report, boss_order = generate_report(all_run_data, dungeon_name)

    # 保存
    import os
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"{dungeon_name}Boss技能分析.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存: {report_path}")

    # 保存原始数据
    json_path = os.path.join(output_dir, f"{dungeon_key}_analysis.json")
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
            }
        save_data.append({
            "code": rd["code"],
            "fight_id": rd["fight_id"],
            "tank_name": rd["tank_name"],
            "keystone_level": rd["keystone_level"],
            "boss_results": boss_results,
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"原始数据: {json_path}")

    return report, boss_order, all_run_data


def main():
    if len(sys.argv) < 2:
        print("用法: python3 analyze_dungeon.py <副本英文名> [--search] [--days N]")
        print(f"支持的副本: {', '.join(DUNGEON_CONFIGS.keys())}")
        sys.exit(1)

    dungeon_key = sys.argv[1]
    search = "--search" in sys.argv

    search_days = 14
    for i, arg in enumerate(sys.argv):
        if arg == "--days" and i + 1 < len(sys.argv):
            search_days = int(sys.argv[i + 1])

    analyze_dungeon(dungeon_key, search=search, search_days=search_days)


if __name__ == "__main__":
    main()
