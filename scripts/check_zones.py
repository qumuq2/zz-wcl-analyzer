#!/usr/bin/env python3
"""查询WCL区域和遭遇信息

用法:
    python check_zones.py                 # 列出所有区域
    python check_zones.py --zone 47       # 查看指定区域的遭遇
"""

import argparse
from wcl_analyzer.client import WCLClient

def main():
    parser = argparse.ArgumentParser(description="查询WCL区域和遭遇信息")
    parser.add_argument("--zone", type=int, default=None, help="指定区域ID")
    args = parser.parse_args()

    client = WCLClient()

    if args.zone:
        zone = client.get_zone(args.zone)
        print(f"\n区域 {zone['id']}: {zone['name']}")
        print(f"遭遇:")
        for e in zone.get("encounters", []):
            print(f"  {e['id']}: {e['name']}")
    else:
        zones = client.get_zones()
        print(f"\n共 {len(zones)} 个区域:")
        for z in zones:
            encounters = z.get("encounters", [])
            encounter_names = ", ".join(e["name"] for e in encounters[:3])
            if len(encounters) > 3:
                encounter_names += f" ... (+{len(encounters)-3})"
            print(f"  Zone {z['id']}: {z['name']} ({len(encounters)} 遭遇) [{encounter_names}]")

if __name__ == "__main__":
    main()
