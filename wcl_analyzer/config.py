"""WCL Analyzer 配置 - API凭证、常量映射"""

import os

# ===== WCL OAuth 配置 =====
# 优先从环境变量读取，未设置时使用默认值
WCL_CLIENT_ID = os.getenv("WCL_CLIENT_ID", "a1cf7870-26b0-4c46-a9bc-864926c5aa80")
WCL_CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET", "KiHpDMhASovnzLNV6wtoiHuF2IHvevvH3PeUK0vu")
WCL_TOKEN_URL = "https://cn.warcraftlogs.com/oauth/token"
WCL_GRAPHQL_URL = "https://cn.warcraftlogs.com/api/v2/client"

# ===== 伤害类型映射 (WCL type field) =====
DAMAGE_TYPE_MAP = {
    1: "物理",
    2: "神圣",
    4: "火焰",
    8: "自然",
    16: "冰霜",
    32: "暗影",
    64: "奥术",
    128: "混乱",
    256: "瘟疫",
}

# ===== hitType 映射 =====
HIT_TYPE_MAP = {
    0: "未命中",
    1: "普通命中",
    2: "暴击",
    3: "吸收",
    4: "格挡",
    5: "躲闪",
    6: "招架",
    7: "偏转",
    8: "免疫",
    9: "未命中(抵抗)",
    10: "躲闪(部分)",
    11: "反射",
}

# ===== 大秘境区域ID (WCL Zone) =====
MPLUS_ZONES = {
    47: "Mythic+ Season 1",      # 12版本第一赛季
    43: "Mythic+ Season 2",      # (预留)
    45: "Mythic+ Season 3",      # (预留)
}

# ===== 大秘境副本 Encounter ID =====
# 12版本第一赛季 M+ 副本 (Zone 47)
SEASON1_DUNGEONS = {
    10658: "萨隆之渊(萨隆矿坑)",       # Pit of Saron
    361753: "执政团之座",              # Seat of the Triumvirate
    12915: "枢纽节点塞纳斯",           # The Nexus
    112526: "艾杰斯亚学院",            # Algeth'ar Academy
    12874: "迈萨拉洞窟",              # MOTHERLODE!!
    61209: "通天峰",                  # Skyreach
    12805: "风行者之塔",              # The Vortex Pinnacle
    12811: "魔导师平台",              # Magisters' Terrace
}

# ===== 职业专精识别 =====
# WCL masterData中 icon 字段格式: "ClassName-SpecName"
# 用于识别坦克专精（subType字段大部分为"Unknown"不可靠，必须用icon）
TANK_SPECS = {
    "Warrior-Protection": "防战",
    "Paladin-Protection": "防骑",
    "Druid-Guardian": "熊坦",
    "DeathKnight-Blood": "血DK",
    "Monk-Brewmaster": "酒仙",
    "DemonHunter-Vengeance": "复仇DH",
}

# 所有可识别专精的 icon -> 中文名 映射
SPEC_MAP = {
    # 坦克
    "Warrior-Protection": "防战",
    "Paladin-Protection": "防骑",
    "Druid-Guardian": "熊坦",
    "DeathKnight-Blood": "血DK",
    "Monk-Brewmaster": "酒仙",
    "DemonHunter-Vengeance": "复仇DH",
    # 治疗
    "Priest-Discipline": "戒律牧",
    "Priest-Holy": "神圣牧师",
    "Paladin-Holy": "奶骑",
    "Shaman-Restoration": "奶萨",
    "Monk-Mistweaver": "织雾",
    "Druid-Restoration": "奶德",
    "Evoker-Preservation": "恩护唤魔师",
    # DPS
    "Warrior-Arms": "武器战",
    "Warrior-Fury": "狂暴战",
    "Paladin-Retribution": "惩戒骑",
    "Hunter-BeastMastery": "兽王猎",
    "Hunter-Marksmanship": "射击猎",
    "Hunter-Survival": "生存猎",
    "Rogue-Assassination": "刺杀贼",
    "Rogue-Outlaw": "狂徒贼",
    "Rogue-Subtlety": "敏锐贼",
    "Priest-Shadow": "暗牧",
    "Shaman-Elemental": "元素萨",
    "Shaman-Enhancement": "增强萨",
    "Mage-Arcane": "奥法",
    "Mage-Fire": "火法",
    "Mage-Frost": "冰法",
    "Warlock-Affliction": "痛苦术",
    "Warlock-Demonology": "恶魔术",
    "Warlock-Destruction": "毁灭术",
    "Monk-Windwalker": "踏风",
    "Druid-Balance": "鸟德",
    "Druid-Feral": "猫德",
    "DeathKnight-Frost": "冰DK",
    "DeathKnight-Unholy": "邪DK",
    "DemonHunter-Havoc": "浩劫DH",
    "Evoker-Devastation": "湮灭唤魔师",
    "Evoker-Augmentation": "增辉唤魔师",
}

# ===== 萨隆矿坑 Boss 名称 =====
# 用于Boss阶段划分（通过伤害事件source名称匹配）
PIT_OF_SARON_BOSSES = {
    "熔炉之主加弗斯特": 1,    # Forgemaster Garfrost (Boss 1)
    "伊克": 2,                # Ick (Boss 2)
    "天灾领主泰兰努斯": 3,    # Scourgelord Tyrannus (Boss 3)
}

# ===== 萨隆矿坑 Boss 技能ID映射 =====
PIT_OF_SARON_BOSS1_SKILLS = {
    1261315: "主要攻击",
    1261546: "碎矿锤击(Orebreaker)",
    1261808: "辐射寒意(Radiating Chill)",
    1261847: "冰霜践踏(Cryostomp)",
    1272433: "矿石碎片(Ore Chunks)",
    1261799: "其他攻击",
    1261295: "其他低频技能",
}
