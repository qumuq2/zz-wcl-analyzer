"""WCL API 客户端 - 同步版本，基于requests

从原项目app/wcl_client.py的async/httpx版本改造为sync/requests，
并融入了实际查询中积累的经验：
- 必须用fightIDs参数获取events，startTime/endTime绝对时间会返回0结果
- targetID过滤无效，需客户端过滤
- 事件timestamp是相对于报告startTime的偏移量
- table返回的数据可能是字符串化JSON，需兼容处理
"""

import time
import json
import requests
from .config import WCL_CLIENT_ID, WCL_CLIENT_SECRET, WCL_TOKEN_URL, WCL_GRAPHQL_URL


class WCLClient:
    """Warcraft Logs API 客户端，自动管理token刷新"""

    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or WCL_CLIENT_ID
        self.client_secret = client_secret or WCL_CLIENT_SECRET
        self._token = None
        self._token_expires = 0

    def _ensure_token(self):
        """确保有有效的access token"""
        if self._token and time.time() < self._token_expires - 60:
            return
        resp = requests.post(
            WCL_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600)

    def query(self, query_str, variables=None):
        """执行GraphQL查询，返回data部分"""
        self._ensure_token()
        payload = {"query": query_str}
        if variables:
            payload["variables"] = variables
        resp = requests.post(
            WCL_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        if "errors" in result:
            raise ValueError(f"GraphQL Error: {result['errors']}")
        return result["data"]

    # ===== 报告查询 =====

    def get_report_info(self, code):
        """获取报告基本信息"""
        query = """
        query($code: String!) {
            reportData {
                report(code: $code) {
                    code title owner { name } startTime endTime
                    zone { id name }
                }
            }
        }
        """
        result = self.query(query, {"code": code})
        return result["reportData"]["report"]

    def get_fights(self, code, keystone_level=None):
        """获取战斗列表，可选按大秘境层数过滤"""
        if keystone_level is not None:
            fight_arg = f"(keystoneLevel: {keystone_level})"
        else:
            fight_arg = ""
        query = f"""
        query($code: String!) {{
            reportData {{
                report(code: $code) {{
                    fights{fight_arg} {{
                        id encounterID kill difficulty name
                        startTime endTime bossPercentage fightPercentage
                        keystoneLevel size gameZone {{ id name }}
                    }}
                }}
            }}
        }}
        """
        result = self.query(query, {"code": code})
        return result["reportData"]["report"]["fights"]

    def get_master_data(self, code, translate=True):
        """获取报告的主数据（actors + abilities）

        注意：subType字段大部分显示"Unknown"不可靠，
        应使用icon字段识别专精（如 "Druid-Guardian" 识别熊坦）
        """
        query = """
        query($code: String!, $translate: Boolean) {
            reportData {
                report(code: $code) {
                    masterData(translate: $translate) {
                        actors { id name type subType gameID server icon }
                        abilities { name gameID type icon }
                    }
                }
            }
        }
        """
        result = self.query(query, {"code": code, "translate": translate})
        return result["reportData"]["report"]["masterData"]

    # ===== 汇总表查询 =====

    def get_table(self, code, fight_ids, data_type, hostility_type=None):
        """获取汇总表数据

        Args:
            code: 报告代码
            fight_ids: 战斗ID列表
            data_type: 数据类型 (DamageDone, DamageTaken, Healing, Casts 等)
            hostility_type: 敌我类型 (Enemies, Friendlies)
        """
        hostility_arg = f", hostilityType: {hostility_type}" if hostility_type else ""
        fight_ids_str = str(fight_ids)
        query = f"""
        query($code: String!) {{
            reportData {{
                report(code: $code) {{
                    table(fightIDs: {fight_ids_str}, dataType: {data_type}{hostility_arg})
                }}
            }}
        }}
        """
        result = self.query(query, {"code": code})
        table = result["reportData"]["report"]["table"]
        # table可能是字符串化JSON或直接就是数据
        if isinstance(table, str):
            try:
                table = json.loads(table)
            except json.JSONDecodeError:
                pass
        if isinstance(table, dict) and "data" in table:
            return table["data"]
        return table

    # ===== 事件查询 =====

    def get_events(self, code, fight_ids, data_type, hostility_type=None,
                   source_id=None, target_id=None, ability_id=None,
                   start_time=None, end_time=None, limit=10000):
        """获取事件数据（单页）

        重要注意事项：
        - 必须用fightIDs参数，startTime/endTime绝对时间会返回0结果
        - targetID过滤无效，需客户端过滤
        - 事件timestamp是相对于报告startTime的偏移量

        Returns:
            (events_list, next_page_timestamp)
        """
        args = [f"fightIDs: {fight_ids}", f"dataType: {data_type}", f"limit: {limit}"]
        if hostility_type:
            args.append(f"hostilityType: {hostility_type}")
        if source_id is not None:
            args.append(f"sourceID: {source_id}")
        if target_id is not None:
            args.append(f"targetID: {target_id}")
        if ability_id is not None:
            args.append(f"abilityID: {ability_id}")
        if start_time is not None:
            args.append(f"startTime: {start_time}")
        if end_time is not None:
            args.append(f"endTime: {end_time}")

        args_str = ", ".join(args)
        query = f"""
        query($code: String!) {{
            reportData {{
                report(code: $code) {{
                    events({args_str}) {{
                        data nextPageTimestamp
                    }}
                }}
            }}
        }}
        """
        result = self.query(query, {"code": code})
        events_data = result["reportData"]["report"]["events"]
        return events_data["data"], events_data.get("nextPageTimestamp")

    def get_all_events(self, code, fight_ids, data_type, hostility_type=None,
                       source_id=None, target_id=None, ability_id=None,
                       start_time=None, end_time=None, max_pages=50):
        """获取所有事件数据（自动翻页）

        注意：targetID过滤服务端不生效，即使传了target_id也返回所有事件，
        需要在客户端用 filter_events_by_target() 过滤。
        """
        all_events = []
        next_ts = start_time
        for page in range(max_pages):
            events, next_ts = self.get_events(
                code, fight_ids, data_type, hostility_type,
                source_id, target_id, ability_id,
                start_time=next_ts, end_time=end_time, limit=10000
            )
            all_events.extend(events)
            if not next_ts or len(events) == 0:
                break
        return all_events

    # ===== 报告搜索 =====

    def search_reports(self, zone_id, start_time, limit=100):
        """搜索指定区域和时间范围内的报告

        Args:
            zone_id: 区域ID (如47=Mythic+ Season 1)
            start_time: 开始时间的毫秒时间戳
            limit: 每页数量
        """
        query = """
        query($zoneID: Int!, $startTime: Float!, $limit: Int) {
            reportData {
                reports(zoneID: $zoneID, startTime: $startTime, limit: $limit) {
                    data {
                        code startTime title owner { name }
                    }
                }
            }
        }
        """
        result = self.query(query, {
            "zoneID": zone_id,
            "startTime": float(start_time),
            "limit": limit,
        })
        return result["reportData"]["reports"]["data"]

    def search_reports_paginated(self, zone_id, start_time, max_pages=10, limit=100):
        """翻页搜索所有报告

        Args:
            zone_id: 区域ID
            start_time: 起始时间戳(ms)
            max_pages: 最大翻页次数
            limit: 每页数量

        Returns:
            所有报告的列表
        """
        all_reports = []
        cursor = float(start_time)
        for page in range(max_pages):
            reports = self.search_reports(zone_id, cursor, limit)
            if not reports:
                break
            all_reports.extend(reports)
            last_time = reports[-1]["startTime"]
            if last_time <= cursor:
                break
            cursor = float(last_time)
        return all_reports

    # ===== 排名查询 =====

    def get_character_rankings(self, encounter_id, class_name, spec_name,
                               difficulty=10, metric="dps"):
        """查询角色排名

        Args:
            encounter_id: 遭遇ID (如10658=萨隆矿坑)
            class_name: 职业名 (如 "Druid")
            spec_name: 专精名 (如 "Guardian")
            difficulty: 难度 (10=Mythic Keystone)
            metric: 指标 (dps, hps, kpsi)
        """
        query = f"""
        query {{
            worldData {{
                encounter(id: {encounter_id}) {{
                    characterRankings(
                        className: "{class_name}"
                        specName: "{spec_name}"
                        difficulty: {difficulty}
                        metric: {metric}
                    )
                }}
            }}
        }}
        """
        result = self.query(query)
        data = result["worldData"]["encounter"]["characterRankings"]
        # WCL有时返回字符串化JSON
        if isinstance(data, str):
            data = json.loads(data)
        return data

    # ===== 区域信息查询 =====

    def get_zones(self):
        """获取所有区域和遭遇信息"""
        query = """
        query {
            worldData {
                zones {
                    id name
                    encounters { id name }
                }
            }
        }
        """
        result = self.query(query)
        return result["worldData"]["zones"]

    def get_zone(self, zone_id):
        """获取指定区域信息"""
        query = """
        query($zoneId: Int!) {
            worldData {
                zone(id: $zoneId) {
                    id name
                    encounters { id name }
                }
            }
        }
        """
        result = self.query(query, {"zoneId": zone_id})
        return result["worldData"]["zone"]


# 全局客户端实例
wcl_client = WCLClient()
