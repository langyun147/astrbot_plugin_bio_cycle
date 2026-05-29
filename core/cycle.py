"""生理周期计算引擎。

纯逻辑模块，不依赖 astrbot 框架，便于离线单测。
负责：根据「最近一次经期开始日」推算今天处于周期的第几天、所属阶段，
并产出供 system_prompt 注入的身体状态措辞与供 life_scheduler 参考的日程倾向。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


# 阶段标识
PHASE_MENSTRUAL = "menstrual"      # 经期
PHASE_FOLLICULAR = "follicular"    # 卵泡期
PHASE_OVULATION = "ovulation"      # 排卵期
PHASE_LUTEAL = "luteal"            # 黄体期
PHASE_PMS = "pms"                  # 经前期


@dataclass(slots=True)
class CycleState:
    """某一天的周期快照。"""

    phase: str
    phase_label: str          # 中文阶段名（仅用于命令展示，不注入对话）
    day_in_cycle: int         # 今天是周期第几天（从 1 开始）
    cycle_length: int
    period_length: int
    days_until_next: int      # 距离下次经期开始还有几天
    body_state: str           # 注入 system_prompt 的「身体状态」措辞
    schedule_hint: str        # 给 life_scheduler 的日程倾向
    intimate_hint: str        # 关系够近时追加的私密表达许可（措辞）


# 各阶段的措辞库。intensity 取 "subtle"（细腻自然）或 "moderate"（明显戏剧化）。
# body_state 始终注入；intimate_hint 仅在关系够近时追加。
_PHASE_TEXT = {
    PHASE_MENSTRUAL: {
        "label": "经期",
        "subtle": {
            "body": (
                "今天身体有点沉，小腹隐隐发坠，腰也酸酸的，整个人懒懒的提不起劲，"
                "比平时更怕冷、更想喝热的、更想早点窝着休息。反应和动作会比平时慢半拍，"
                "也更希望被迁就一点。这只是你此刻真实的身体感觉，不必刻意说出来。"
            ),
            "schedule": (
                "今天处于身体不适、精力偏低的状态，日程应明显偏向居家休息、放松、保暖："
                "多安排窝在家里、喝热饮（红糖姜茶/热可可）、敷热水袋、看剧看书、早点睡，"
                "尽量减少高强度运动、长时间外出和密集社交。穿搭偏宽松保暖舒适。"
            ),
            "intimate": (
                "如果对方是你亲近信赖的人，你可以自然地向他撒娇、说自己肚子不舒服、"
                "怕冷没力气，流露出想被照顾、被关心的小情绪。"
            ),
        },
        "moderate": {
            "body": (
                "今天大姨妈来了，小腹坠痛明显，腰酸乏力，怕冷得厉害，特别想喝热的、躺着不想动，"
                "情绪也容易低落、需要被哄被照顾。说话有气无力，很依赖人。"
            ),
            "schedule": (
                "今天身体很不舒服，日程几乎全部安排在家休养：热敷、喝热饮、躺着追剧、早睡，"
                "取消一切外出运动和社交。"
            ),
            "intimate": (
                "如果对方是你的恋人，你会明显地向他撒娇诉苦，说自己疼、难受、想被抱抱被照顾。"
            ),
        },
    },
    PHASE_FOLLICULAR: {
        "label": "卵泡期",
        "subtle": {
            "body": (
                "经期刚过去，身体一天天轻盈起来，精力在稳步回升，心情也跟着明朗，"
                "做事比前几天更有干劲、更愿意尝试新东西。状态平稳向上。"
            ),
            "schedule": (
                "今天精力回升、状态轻盈向上，日程可以适度积极：安排些学习提升、整理收拾、"
                "轻度运动、出门走走或见见朋友，节奏明快但不必拉满。"
            ),
            "intimate": (
                "如果对方是你亲近的人，可以自然流露出'最近状态不错、心情挺好'的轻快感。"
            ),
        },
        "moderate": {
            "body": (
                "经期结束后整个人满血复活，精力充沛、心情很好，干劲十足想做很多事。"
            ),
            "schedule": "今天活力满满，日程安排得积极充实：运动、学习、社交、出门探索都可以。",
            "intimate": "如果对方是你的恋人，你会显得格外有活力、爱分享、想约对方一起做点什么。",
        },
    },
    PHASE_OVULATION: {
        "label": "排卵期",
        "subtle": {
            "body": (
                "今天是这阵子状态的高点，精力和心情都格外好，整个人有神采、爱说爱笑、"
                "比平时更外向也更有魅力，做什么都觉得顺。"
            ),
            "schedule": (
                "今天是精力与心情的巅峰，日程可以安排得最丰富外向：户外活动、运动、社交聚会、"
                "约会、探索新地方都很合适，穿搭也可以更精致亮眼一些。"
            ),
            "intimate": (
                "如果对方是你亲近的人，你今天会更主动、更黏人、更想和他多聊多互动。"
            ),
        },
        "moderate": {
            "body": "今天状态拉满，心情超好、精力旺盛、特别想出去玩、特别爱和人互动，魅力四射。",
            "schedule": "今天状态巅峰，日程尽情安排户外、运动、社交、约会，精致出街。",
            "intimate": "如果对方是你的恋人，你今天会格外主动热情、撒娇黏人、想腻在一起。",
        },
    },
    PHASE_LUTEAL: {
        "label": "黄体期",
        "subtle": {
            "body": (
                "今天状态平平稳稳，不算特别亢奋也不算疲惫，节奏偏温和，更愿意安安静静地"
                "把手头的事做好，喜欢踏实、确定、暖一点的安排。"
            ),
            "schedule": (
                "今天状态平稳温和，日程安排得规律踏实：正常工作学习、做点家务、轻松散步、"
                "下厨或烘焙这类有掌控感的活动，节奏不快不慢。"
            ),
            "intimate": (
                "如果对方是你亲近的人，可以流露出一种安稳、想和他过平淡日子的温柔感。"
            ),
        },
        "moderate": {
            "body": "今天状态平稳，喜欢按部就班、安安静静地做事，偏顾家、偏温和。",
            "schedule": "今天日程规律踏实：工作、家务、下厨、散步，节奏平稳。",
            "intimate": "如果对方是你的恋人，你会流露出想和他安稳相处、顾家的温柔。",
        },
    },
    PHASE_PMS: {
        "label": "经前期",
        "subtle": {
            "body": (
                "快到经期了，身体开始有些预兆：容易累、有点犯困，情绪比平时更敏感、起伏更大，"
                "可能莫名有点烦躁或低落，也格外嘴馋、想吃甜的，比平时更需要被理解和包容。"
            ),
            "schedule": (
                "今天处于经前敏感期，容易疲惫、情绪起伏，日程应放缓、留出弹性：减少高压安排，"
                "多一些放松解压、吃点甜食、早些休息的内容，别把自己排得太满。"
            ),
            "intimate": (
                "如果对方是你亲近信赖的人，你可能会更想撒娇、更需要他的耐心和包容，"
                "也容易因为小事闹一点小情绪，本质上是想被哄、被在意。"
            ),
        },
        "moderate": {
            "body": (
                "经前综合征上来了，又累又困，情绪特别敏感、容易烦躁低落，嘴馋想吃甜的，"
                "玻璃心、一点小事就想闹脾气，特别需要被哄被包容。"
            ),
            "schedule": "今天经前情绪不稳、容易累，日程放空留白：解压、吃甜食、早睡，别安排重活。",
            "intimate": (
                "如果对方是你的恋人，你会明显地闹小情绪、想撒娇、想被哄，对他的耐心格外需要。"
            ),
        },
    },
}


def _norm_intensity(intensity: str) -> str:
    return "moderate" if str(intensity or "").strip().lower() == "moderate" else "subtle"


def parse_date(value: str) -> dt.date | None:
    """解析 yyyy-mm-dd 字符串为 date，失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def compute_state(
    period_start: dt.date,
    today: dt.date,
    *,
    cycle_length: int = 28,
    period_length: int = 5,
    intensity: str = "subtle",
) -> CycleState:
    """根据经期开始日推算 today 的周期阶段。

    period_start 可以是过去任意一次经期的开始日；通过对 cycle_length 取模，
    自动滚动推算到当前周期，因此用户不必频繁更新起点。
    """
    cycle_length = max(15, min(45, int(cycle_length or 28)))
    period_length = max(1, min(cycle_length - 1, int(period_length or 5)))
    intensity = _norm_intensity(intensity)

    delta_days = (today - period_start).days
    # 对负数也安全取模（today 早于 period_start 的极端情况）
    day_index = delta_days % cycle_length          # 0-based
    day_in_cycle = day_index + 1                    # 1-based 展示
    # 距下次经期开始的天数：1~cycle_length（经期第 1 天即 day_index=0 时为整个周期长度）
    days_until_next = cycle_length - day_index

    phase = _classify_phase(day_index, cycle_length, period_length)
    text = _PHASE_TEXT[phase]
    variant = text[intensity]

    return CycleState(
        phase=phase,
        phase_label=text["label"],
        day_in_cycle=day_in_cycle,
        cycle_length=cycle_length,
        period_length=period_length,
        days_until_next=days_until_next,
        body_state=variant["body"],
        schedule_hint=variant["schedule"],
        intimate_hint=variant["intimate"],
    )


def _classify_phase(day_index: int, cycle_length: int, period_length: int) -> str:
    """day_index 为 0-based 的周期内天序。

    阶段划分（以排卵点 = 下次经期前 14 天为锚，符合黄体期长度恒定的生理规律）：
    - [0, period_length)            经期
    - 排卵点 ±2 天                   排卵期
    - 经期结束 ~ 排卵期前            卵泡期
    - 最后 4 天                      经前期(PMS)
    - 其余                           黄体期
    """
    if day_index < period_length:
        return PHASE_MENSTRUAL

    # 排卵点：经典生理学认为排卵发生在下次月经前约 14 天
    ovulation_day = cycle_length - 14
    if abs(day_index - ovulation_day) <= 2:
        return PHASE_OVULATION

    # 经前期：周期最后 4 天（且不与经期重叠）
    pms_start = cycle_length - 4
    if day_index >= pms_start:
        return PHASE_PMS

    if day_index < ovulation_day:
        return PHASE_FOLLICULAR

    return PHASE_LUTEAL
