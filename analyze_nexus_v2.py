#!/usr/bin/env python3
"""枢纽节点塞纳斯Boss详细技能分析 v2

改进：
1. 战斗窗口：起点=boss首次cast（进战斗），终点=末次DamageDone to boss（死亡）
2. 排除"Environment"伪Boss
3. 非Boss伤害来源做一致性过滤（≥50%场次才纳入，排除偶然拉怪）
4. Boss技能加粗显示
"""

import json
import time
from collections import defaultdict

from wcl_analyzer.client import WCLClient
from wcl_analyzer.boss_timeline import BossTimelineAnalyzer
from wcl_analyzer.utils import (
    build_actor_maps, filter_events_by_target, filter_events_by_time,
    analyze_skills, format_damage_type,
)

KNOWN_RUNS = [
    {"code": "7abzDXnKPwZhyJ21", "fight_id": 28, "tank_id": 707, "tank_name": "張義德", "ksl": 20},
    {"code": "hz2jmaWgq7t6JCBr", "fight_id": 5, "tank_id": 109, "tank_name": "琳琳大魔王", "ksl": 20},
    {"code": "8KGRg9dVy6T3PxmM", "fight_id": 15, "tank_id": 242, "tank_name": "Xiaofua", "ksl": 20},
    {"code": "vaJzZ4HQT13pm6gL", "fight_id": 15, "tank_id": 2, "tank_name": "泡泡鱼子", "ksl": 20},
]

EXCLUDED_BOSSES = {"Environment"}
BOSS_ORDER = ["卡斯雷瑟", "核心守卫奈萨拉", "洛萨克森"]


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


def analyze_single_run(client, analyzer, code, fight_id, tank_id, tank_name, ksl):
    """分析一场战斗中所有Boss"""
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
            # fallback: 用旧逻辑的end
            phase_end = phase_info["end"]

        duration_ms = phase_end - phase_start

        boss_phase_events = filter_events_by_time(tank_events, phase_start, phase_end)
        boss_only_events = [e for e in boss_phase_events if e.get("sourceID") == boss_id]
        env_events = [e for e in boss_phase_events if e.get("sourceID") != boss_id]

        boss_skills = analyze_skills(boss_only_events, actor_name_map, ability_type_map, ability_map)
        env_skills = analyze_skills(env_events, actor_name_map, ability_type_map, ability_map)

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


def generate_report(all_run_data):
    """生成Markdown报告"""
    total_runs = len(all_run_data)
    min_appear = max(2, total_runs // 2)

    source_appearance = defaultdict(lambda: defaultdict(set))
    for ri, rd in enumerate(all_run_data):
        for boss_name, bi in rd["boss_results"].items():
            for sk in bi["env_skills"]:
                source_appearance[boss_name][sk["source_name"]].add(ri)

    lines = []
    lines.append("# 枢纽节点塞纳斯 Boss技能分析\n")
    lines.append(f"> 数据来源：{total_runs}场+20层熊坦(Druid-Guardian)限时记录")
    lines.append(f"> 战斗窗口：起点=boss首次cast（进战斗），终点=boss末次受击+2s（死亡）")
    lines.append(f"> 伤害维度：单次最大(减免前) / 单次最大(减免后) / 单次平均(减免前) / 单次平均(减免后)")
    lines.append(f"> 一致性过滤：非Boss来源需在≥{min_appear}场出现才纳入\n")

    for boss_name in BOSS_ORDER:
        has_data = any(boss_name in rd["boss_results"] for rd in all_run_data)
        if not has_data:
            continue

        lines.append("---")
        lines.append(f"## {boss_name}\n")

        all_skills = defaultdict(list)
        boss_id = None

        for rd in all_run_data:
            if boss_name not in rd["boss_results"]:
                continue
            bi = rd["boss_results"][boss_name]
            boss_id = bi["boss_id"]

            for sk in bi["boss_skills"]:
                key = (sk["source_name"], sk["ability_name"], sk["damage_type"])
                all_skills[key].append(("boss", sk))

            for sk in bi["env_skills"]:
                src_name = sk["source_name"]
                if len(source_appearance[boss_name][src_name]) < min_appear:
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
                if mn == mx:
                    return _format_wan(mn)
                return f"{_format_wan(mn)}-{_format_wan(mx)}"

            def fmt_hits(vals):
                mn, mx = min(vals), max(vals)
                if mn == mx:
                    return str(mn)
                return f"{mn}-{mx}"

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

        lines.append("")

    # 野性之心使用总结
    lines.append("---\n")
    lines.append("## 三Boss野性之心使用总结\n")
    lines.append("| Boss | 起手建议 | 后续最佳窗口 | 窗口时长 | 窗口间隔 | 注意事项 |")
    lines.append("|------|---------|------------|---------|---------|---------|")
    lines.append("| 卡斯雷瑟 | ⚠️等Phase 2 | 奥术震击间隙 | 视战斗节奏 | ~3s | Phase 1不攻击坦克，小怪伤害为主 |")
    lines.append("| 核心守卫奈萨拉 | ✅易伤阶段 | 蚀光步伐后 | 5-6s | 11-37s | 窗口短需果断；小怪伤害高 |")
    lines.append("| 洛萨克森 | ⚠️等50s | 神圣诡计后 | 10-11s | ~56s | 近战减免前最大100万 |")

    lines.append("\n### ⚠️特别注意")
    lines.append("- **卡斯雷瑟**：Phase 1（boss首次受击前）几乎全受小怪伤害（影卫防御者+通量工程师占60%+），变猫期间小怪仍打你")
    lines.append("- **核心守卫奈萨拉**：大废止者+恐惧连枷占30%+伤害，恐惧连枷「近战」减免后单次12-24万很疼，变猫需注意")
    lines.append("- **洛萨克森**：环境伤害少（5-10%），Boss自身伤害占80%+，是最「纯粹」的Boss战")

    return "\n".join(lines)


def main():
    client = WCLClient()
    analyzer = BossTimelineAnalyzer(client)

    print("分析: 枢纽节点塞纳斯 (v2 - 精确战斗窗口)")

    all_run_data = []
    for run in KNOWN_RUNS:
        print(f"\n{'─'*40}")
        print(f"分析: {run['tank_name']}(+{run['ksl']}) ...")
        try:
            rd = analyze_single_run(
                client, analyzer,
                run["code"], run["fight_id"], run["tank_id"],
                run["tank_name"], run["ksl"]
            )
            if rd:
                all_run_data.append(rd)
                for bn in BOSS_ORDER:
                    if bn in rd["boss_results"]:
                        bi = rd["boss_results"][bn]
                        fight_start = rd["fight_start"]
                        offset_s = (bi["phase_start"] - fight_start) / 1000
                        offset_e = (bi["phase_end"] - fight_start) / 1000
                        print(f"  {bn}: offset {offset_s:.0f}s~{offset_e:.0f}s ({bi['duration_s']}s)")
                        print(f"    Boss技能: {len(bi['boss_skills'])}个, 其他来源: {len(bi['env_skills'])}个")
            time.sleep(0.5)
        except Exception as e:
            print(f"  分析失败: {e}")
            import traceback
            traceback.print_exc()

    if not all_run_data:
        print("无有效数据")
        return

    report = generate_report(all_run_data)

    output_path = "/tmp/nexus_report_v2.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存: {output_path}")

    json_path = "/tmp/nexus_analysis_v2.json"
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


if __name__ == "__main__":
    main()
