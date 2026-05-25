"""Boss时间轴类型判断 + 安全窗口分析

核心功能：
- 判断Boss是时间轴Boss还是百分比Boss（改进的CV对比法）
- 分析安全窗口（常规/次级）
- 过滤坦克承伤为0的无效记录

使用方法：
    from wcl_analyzer.boss_timeline import BossTimelineAnalyzer
    analyzer = BossTimelineAnalyzer(client)
    result = analyzer.analyze_boss(code, fight_id, tank_id)
"""

from collections import defaultdict
from .utils import (
    build_actor_maps, filter_events_by_target,
    format_duration, format_number, format_damage_type,
    analyze_skills, _analyze_intervals,
)


class BossTimelineAnalyzer:
    """Boss时间轴分析与安全窗口检测"""

    def __init__(self, client):
        self.client = client

    def get_boss_fight_data(self, code, fight_id, tank_id):
        """获取一场Boss战中坦克的所有相关数据

        Returns:
            dict or None: 如果坦克承伤为0则返回None
        """
        master_data = self.client.get_master_data(code)
        fights = self.client.get_fights(code)
        fight = next((f for f in fights if f["id"] == fight_id), None)
        if not fight:
            return None

        actor_name_map, actor_icon_map, ability_map, ability_type_map = build_actor_maps(master_data)

        # 获取承伤事件
        all_events = self.client.get_all_events(code, [fight_id], "DamageTaken", max_pages=20)
        tank_events = filter_events_by_target(all_events, tank_id)

        # 关键过滤：坦克承伤为0的记录无效
        if not tank_events:
            return None

        # 获取敌方施法事件
        cast_events = self.client.get_all_events(code, [fight_id], "Casts",
                                                  hostility_type="Enemies", max_pages=20)

        # 识别Boss
        boss_actors = {}
        for actor in master_data.get("actors", []):
            if actor.get("subType") == "Boss":
                boss_actors[actor["id"]] = actor["name"]

        # 检测Boss阶段（基于对坦克的承伤）
        boss_phases = {}
        for boss_id, boss_name in boss_actors.items():
            boss_dmg = [e for e in tank_events if e.get("sourceID") == boss_id]
            if not boss_dmg:
                continue
            ts_list = [e.get("timestamp", 0) for e in boss_dmg]
            # 也用施法事件扩展边界
            boss_casts = [c for c in cast_events if c.get("sourceID") == boss_id]
            for c in boss_casts:
                ts_list.append(c.get("timestamp", 0))
            boss_phases[boss_name] = {
                "boss_id": boss_id,
                "start": min(ts_list),
                "end": max(ts_list),
            }

        return {
            "code": code,
            "fight_id": fight_id,
            "fight": fight,
            "fight_start": fight["startTime"],
            "fight_end": fight["endTime"],
            "tank_events": tank_events,
            "cast_events": cast_events,
            "boss_phases": boss_phases,
            "actor_name_map": actor_name_map,
            "ability_map": ability_map,
            "ability_type_map": ability_type_map,
            "ability_name_map": {a["gameID"]: a.get("name", f"技能{a['gameID']}")
                                 for a in master_data.get("abilities", [])},
        }

    def determine_boss_type(self, boss_casts_by_run):
        """判断Boss类型：时间轴 vs 百分比

        改进方法：同时计算绝对时间CV和归一化CV。

        Args:
            boss_casts_by_run: {
                ability_name: [(run_name, first_cast_s, fight_duration_s), ...]
            }

        Returns:
            dict with judgment, avg_abs_cv, avg_norm_cv, etc.
        """
        ability_scores = {}

        for aname, run_data in boss_casts_by_run.items():
            if len(run_data) < 2:
                continue

            first_casts = [r[1] for r in run_data]
            durations = [r[2] for r in run_data]
            # 过滤掉duration为0的
            valid = [(r[1], r[2]) for r in run_data if r[2] > 0]
            if len(valid) < 2:
                continue
            first_casts = [v[0] for v in valid]
            durations = [v[1] for v in valid]
            normalized = [fc / dur for fc, dur in zip(first_casts, durations)]

            abs_mean = sum(first_casts) / len(first_casts)
            abs_std = (sum((x - abs_mean)**2 for x in first_casts) / len(first_casts)) ** 0.5
            abs_cv = abs_std / abs_mean if abs_mean > 0 else 0

            norm_mean = sum(normalized) / len(normalized)
            norm_std = (sum((x - norm_mean)**2 for x in normalized) / len(normalized)) ** 0.5
            norm_cv = norm_std / norm_mean if norm_mean > 0 else 0

            ability_scores[aname] = {
                "abs_cv": round(abs_cv, 3),
                "norm_cv": round(norm_cv, 3),
                "abs_std_s": round(abs_std, 2),
                "norm_std_pct": round(norm_std * 100, 2),
            }

        if not ability_scores:
            return {"judgment": "数据不足", "boss_type": None}

        timeline_skills = sum(1 for s in ability_scores.values() if s["abs_cv"] < s["norm_cv"])
        pct_skills = sum(1 for s in ability_scores.values() if s["abs_cv"] >= s["norm_cv"])
        total = len(ability_scores)

        avg_abs_cv = sum(s["abs_cv"] for s in ability_scores.values()) / total
        avg_norm_cv = sum(s["norm_cv"] for s in ability_scores.values()) / total

        if avg_abs_cv < avg_norm_cv * 0.8:
            boss_type = "时间轴"
            judgment = f"时间轴Boss（绝对CV={avg_abs_cv:.3f} < 归一化CV={avg_norm_cv:.3f}）"
        elif avg_norm_cv < avg_abs_cv * 0.8:
            boss_type = "百分比"
            judgment = f"百分比Boss（归一化CV={avg_norm_cv:.3f} < 绝对CV={avg_abs_cv:.3f}）"
        else:
            boss_type = "时间轴" if avg_abs_cv < avg_norm_cv else "百分比"
            judgment = f"偏向{boss_type}（绝对CV={avg_abs_cv:.3f}, 归一化CV={avg_norm_cv:.3f}）"

        return {
            "judgment": judgment,
            "boss_type": boss_type,
            "avg_abs_cv": round(avg_abs_cv, 3),
            "avg_norm_cv": round(avg_norm_cv, 3),
            "timeline_skills": timeline_skills,
            "pct_skills": pct_skills,
            "ability_scores": ability_scores,
        }

    def find_safe_windows(self, damage_events, phase_start, phase_end, min_gap_ms=3000):
        """查找安全窗口

        Args:
            damage_events: Boss对坦克的伤害事件列表
            phase_start: Boss阶段开始时间（ms）
            phase_end: Boss阶段结束时间（ms）
            min_gap_ms: 最小间隙（ms），默认3000

        Returns:
            按时长降序排列的安全窗口列表
        """
        if not damage_events:
            return []

        sorted_events = sorted(damage_events, key=lambda e: e.get("timestamp", 0))
        timestamps = [e.get("timestamp", 0) for e in sorted_events]

        windows = []

        if timestamps[0] - phase_start > min_gap_ms:
            windows.append({
                "duration_s": round((timestamps[0] - phase_start) / 1000, 1),
                "start_offset_s": 0.0,
                "timing": "Boss战开始阶段",
            })

        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i-1]
            if gap > min_gap_ms:
                windows.append({
                    "duration_s": round(gap / 1000, 1),
                    "start_offset_s": round((timestamps[i-1] - phase_start) / 1000, 1),
                    "timing": f"战斗约{round((timestamps[i-1] - phase_start) / 1000):.0f}s时",
                })

        if phase_end - timestamps[-1] > min_gap_ms:
            windows.append({
                "duration_s": round((phase_end - timestamps[-1]) / 1000, 1),
                "start_offset_s": round((timestamps[-1] - phase_start) / 1000, 1),
                "timing": "Boss战结束阶段",
            })

        windows.sort(key=lambda w: -w["duration_s"])
        return windows

    def find_secondary_safe_windows(self, damage_events, phase_start, phase_end,
                                     ignore_ability_ids, min_gap_ms=3000):
        """查找次级安全窗口（忽略指定DoT技能后）

        Args:
            ignore_ability_ids: 要忽略的技能ID集合

        Returns:
            dict with windows and ignored damage info
        """
        filtered = [e for e in damage_events if e.get("abilityGameID") not in ignore_ability_ids]
        ignored = [e for e in damage_events if e.get("abilityGameID") in ignore_ability_ids]

        ignored_raw = sum(e.get("amount", 0) for e in ignored)
        ignored_mitigated = sum(e.get("mitigated", 0) for e in ignored)
        ignored_pre = ignored_raw + ignored_mitigated
        ignored_unmitigated = sum(e.get("unmitigatedAmount", 0) for e in ignored)

        windows = self.find_safe_windows(filtered, phase_start, phase_end, min_gap_ms)

        return {
            "windows": windows,
            "ignored": {
                "ability_ids": list(ignore_ability_ids),
                "pre_mitigation": ignored_pre,
                "post_mitigation": ignored_raw,
                "unmitigated": ignored_unmitigated,
                "hit_count": len(ignored),
            },
        }

    def annotate_windows(self, windows, boss_casts, phase_start, ability_name_map):
        """给安全窗口标注Boss行为，按时间排序并计算间隔"""
        if not windows:
            return windows

        sorted_w = sorted(windows, key=lambda w: w.get("start_offset_s", 0))

        for w in sorted_w:
            ws_abs = phase_start + w["start_offset_s"] * 1000
            we_abs = ws_abs + w["duration_s"] * 1000
            casts_in = [c for c in boss_casts if ws_abs <= c.get("timestamp", 0) <= we_abs]
            if casts_in:
                summary = defaultdict(int)
                for c in casts_in:
                    aid = c.get("abilityGameID", 0)
                    summary[ability_name_map.get(aid, f"技能{aid}")] += 1
                w["boss_action"] = "; ".join(f"{n}×{c}" for n, c in summary.items())
            else:
                w["boss_action"] = "无施法记录"

        for i in range(1, len(sorted_w)):
            prev_end = sorted_w[i-1]["start_offset_s"] + sorted_w[i-1]["duration_s"]
            curr_start = sorted_w[i]["start_offset_s"]
            sorted_w[i]["gap_from_prev_s"] = round(curr_start - prev_end, 1)

        return sorted_w

    def get_boss_casts_by_ability(self, boss_casts, phase_start, ability_name_map):
        """按技能分组Boss施法事件，用于Boss类型判断

        Returns:
            {ability_name: [first_cast_s, ...]}
        """
        casts_by_ability = defaultdict(list)
        for c in boss_casts:
            aid = c.get("abilityGameID", 0)
            ts = c.get("timestamp", 0) - phase_start
            aname = ability_name_map.get(aid, f"技能{aid}")
            casts_by_ability[aname].append(ts / 1000)  # 转为秒
        return dict(casts_by_ability)
