"""生理周期拟真插件主类。

为电子伴侣注入真实的生理周期节律，影响其身体状态、情绪语气；
并深度联动 life_scheduler（日程）与 favorpro（亲密度门控）。

注入优先级 priority=-10：排在 life_scheduler / time_prompt(默认 0) 之后、
favorpro(-20) 之前注入，保证身体状态出现在日程/时间锚点之后、好感度指令之前。
"""

from __future__ import annotations

import datetime as dt

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register, StarTools

from .core.cycle import CycleState, compute_state, parse_date
from .core.store import CycleStore


@register(
    "astrbot_plugin_bio_cycle",
    "langyun147",
    "为电子伴侣注入真实的生理周期，自然影响身体状态、情绪语气，并联动日程与好感度系统",
    "1.0.0",
    "",
)
class BioCyclePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = StarTools.get_data_dir()
        self.store = CycleStore(data_dir / "cycle_data.json")
        self._favorpro = None
        self._favorpro_lookup_failed = False

    # ==================== 配置读取 ====================

    def _cfg(self, key: str, default):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    @property
    def character_name(self) -> str:
        return str(self._cfg("character_name", "晚宁") or "晚宁")

    @property
    def intensity(self) -> str:
        return str(self._cfg("intensity", "subtle") or "subtle")

    @property
    def enabled(self) -> bool:
        # 全局开关（配置）与运行时开关（store）都为真才生效
        return bool(self._cfg("enable", True)) and self.store.enabled

    # ==================== 时间 / 状态 ====================

    def _timezone(self):
        if ZoneInfo is None:
            return None
        tz_name = "Asia/Shanghai"
        try:
            cfg = self.context.get_config()
            configured = cfg.get("timezone") if cfg else None
            if configured:
                tz_name = str(configured)
            return ZoneInfo(tz_name)
        except Exception:
            try:
                return ZoneInfo("Asia/Shanghai")
            except Exception:
                return None

    def _today(self) -> dt.date:
        tz = self._timezone()
        return (dt.datetime.now(tz) if tz else dt.datetime.now()).date()

    def _current_state(self) -> CycleState | None:
        """计算今天的周期快照；未设定经期开始日则返回 None。"""
        start = parse_date(self.store.period_start)
        if start is None:
            return None
        return compute_state(
            start,
            self._today(),
            cycle_length=self.store.cycle_length,
            period_length=self.store.period_length,
            intensity=self.intensity,
        )

    # ==================== favorpro 亲密度门控 ====================

    def _find_favorpro(self):
        """查找 favorpro 插件实例，遵循本仓库既定的跨插件发现模式。"""
        if self._favorpro is not None:
            return self._favorpro
        if self._favorpro_lookup_failed:
            return None
        try:
            for plugin in self.context.get_all_stars():
                p_id = str(getattr(plugin, "id", "") or "")
                p_name = str(getattr(plugin, "name", "") or "")
                if "favorpro" not in p_id.lower() and "favorpro" not in p_name.lower():
                    continue
                inst = (
                    getattr(plugin, "instance", None)
                    or getattr(plugin, "star_instance", None)
                    or getattr(plugin, "star_cls", None)
                )
                if inst is not None:
                    self._favorpro = inst
                    return inst
        except Exception as e:
            logger.debug(f"[bio_cycle] 查找 favorpro 失败: {e}")
        self._favorpro_lookup_failed = True
        return None

    def _is_intimate(self, event: AstrMessageEvent | None) -> bool:
        """通过 favorpro 判断当前对话者是否亲近到可以流露私密生理状态。

        关系含恋人类关键词 且 好感度达到阈值，才返回 True。
        favorpro 不存在 / 取不到状态时，保守返回 False（只在语气上体现，不主动提私密细节）。
        """
        if event is None:
            return False
        fav = self._find_favorpro()
        if fav is None:
            return False
        try:
            raw_user_id = str(event.get_sender_id() or "").strip()
            user_id = fav.manager.normalize_identifier(raw_user_id)
            session_id = fav._get_session_id(event) if hasattr(fav, "_get_session_id") else None
            fallback = (
                fav._identity_fallback_keys(raw_user_id, fav._get_raw_session_id(event))
                if hasattr(fav, "_identity_fallback_keys")
                else None
            )
            state = fav.manager.get_user_state(user_id, session_id, fallback)
        except Exception as e:
            logger.debug(f"[bio_cycle] 读取 favorpro 状态失败: {e}")
            return False

        return self._intimate_by_state(state.get("favour", 0), state.get("relationship", ""))

    def _intimate_by_state(self, favour, relationship) -> bool:
        """根据好感度与关系判断是否够亲密到可以流露私密生理状态。

        亲密度门控的单一来源：被动对话(_is_intimate) 与主动链路
        (build_external_cycle_anchor) 都走这里，保证判定一致。
        """
        try:
            favour = int(favour)
        except (TypeError, ValueError):
            favour = 0
        relationship = str(relationship or "")
        threshold = int(self._cfg("intimacy_favour_threshold", 60) or 60)
        keywords = self._intimacy_keywords()
        rel_ok = any(kw and kw in relationship for kw in keywords)
        return rel_ok and favour >= threshold

    def _intimacy_keywords(self) -> list[str]:
        raw = self._cfg(
            "intimacy_relationship_keywords",
            ["男友", "男朋友", "老公", "恋人", "对象", "情侣", "爱人", "亲密"],
        )
        if isinstance(raw, str):
            items = [s.strip() for s in raw.replace("，", ",").split(",")]
        elif isinstance(raw, (list, tuple)):
            items = [str(s).strip() for s in raw]
        else:
            items = []
        return [s for s in items if s]

    # ==================== 注入文案构造 ====================

    def _build_prompt(self, state: CycleState, intimate: bool) -> str:
        lines = [
            "[身体节律 · 仅供你体会的内在状态]",
            state.body_state,
        ]
        if intimate and state.intimate_hint:
            lines.append(state.intimate_hint)
        lines.append(
            "请把以上身体感受自然融入你的语气、精力和反应里，不要生硬地报告或解释，"
            "也不要因此跳出角色。"
        )
        return "\n".join(lines)

    @staticmethod
    def _append_system_prompt(req: ProviderRequest, text: str) -> None:
        current = getattr(req, "system_prompt", "") or ""
        if current:
            req.system_prompt = f"{current.rstrip()}\n\n{text.strip()}"
        else:
            req.system_prompt = text.strip()

    # ==================== LLM 请求钩子 ====================

    @filter.on_llm_request(priority=-10)
    async def inject_cycle(self, event: AstrMessageEvent, req: ProviderRequest):
        """把当前生理阶段的身体状态注入 system_prompt。"""
        try:
            if not self.enabled:
                return
            state = self._current_state()
            if state is None:
                return
            intimate = self._is_intimate(event)
            self._append_system_prompt(req, self._build_prompt(state, intimate))
        except Exception as e:
            logger.error(f"[bio_cycle] 注入生理周期状态失败: {e}")

    # ==================== 对外公共 API ====================

    def get_cycle_context(self) -> dict:
        """供 life_scheduler 等外部插件读取当前周期上下文。

        返回结构稳定；未启用或未设定起点时返回 {"enabled": False}。
        """
        if not self.enabled:
            return {"enabled": False}
        state = self._current_state()
        if state is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "phase": state.phase,
            "phase_label": state.phase_label,
            "day_in_cycle": state.day_in_cycle,
            "cycle_length": state.cycle_length,
            "period_length": state.period_length,
            "days_until_next": state.days_until_next,
            "body_state": state.body_state,
            "schedule_hint": state.schedule_hint,
        }

    def build_external_cycle_anchor(
        self,
        session_key: str | None = None,
        *,
        purpose: str = "active_share",
        favour=None,
        relationship=None,
    ) -> str:
        """供绕过 on_llm_request 的主动推送链路（daily_sharing / proactive_chat 等）复用。

        与 inject_cycle 注入的身体状态同源；不依赖 event。
        调用方可传入对方的 favour/relationship（通常从 favorpro 取）以启用亲密度门控：
        够亲密时主动消息也能自然撒娇、说不舒服；不传则只注入身体状态、不含私密表达许可。
        未启用 / 未设定起点 / 广播会话时返回空串（优雅降级）。

        Args:
            session_key: 会话标识；为 "qzone_broadcast" 等广播会话时返回空串。
            purpose: 调用场景标记，目前不改变输出，保留以便未来区分。
            favour: 可选，对方好感度（私聊场景由调用方从 favorpro 取得）。
            relationship: 可选，对方关系描述。
        """
        try:
            if not self.enabled:
                return ""
            if session_key == "qzone_broadcast":
                return ""
            state = self._current_state()
            if state is None:
                return ""
            intimate = False
            if favour is not None or relationship is not None:
                intimate = self._intimate_by_state(favour, relationship)
            return self._build_prompt(state, intimate=intimate)
        except Exception as e:
            logger.debug(f"[bio_cycle] 构建外部周期锚失败: {e}")
            return ""

    # ==================== 管理员命令 ====================

    def _format_status(self, state: CycleState | None) -> str:
        if state is None:
            return (
                f"{self.character_name}还没有设定生理周期起点。\n"
                "管理员可用：/周期 设定 2026-05-20 （或 /周期 设定 今天）"
            )
        return (
            f"🌙 {self.character_name}的生理周期\n"
            f"当前阶段：{state.phase_label}\n"
            f"周期第 {state.day_in_cycle} / {state.cycle_length} 天\n"
            f"经期长度：{state.period_length} 天\n"
            f"距下次经期：约 {state.days_until_next} 天\n"
            f"状态开关：{'开启' if self.enabled else '关闭'}"
        )

    @filter.command("周期")
    async def cycle_cmd(self, event: AstrMessageEvent, action: str | None = None, value: str | None = None):
        """生理周期管理。用法：
        /周期                查看当前阶段（所有人可查看）
        /周期 设定 2026-05-20  设定最近一次经期开始日（管理员，支持「今天」）
        /周期 长度 28         设定平均周期天数（管理员）
        /周期 经期 5          设定经期持续天数（管理员）
        /周期 开启 | 关闭      运行时开关（管理员）
        """
        action = (action or "").strip()

        # 无参数：查看状态（所有人可用）
        if not action or action in ("查看", "状态", "show"):
            yield event.plain_result(self._format_status(self._current_state()))
            return

        # 其余子命令均需管理员
        if event.role != "admin":
            yield event.plain_result("错误：该操作仅限管理员使用。")
            return

        if action in ("设定", "设置", "set"):
            async for r in self._cmd_set_start(event, value):
                yield r
        elif action in ("长度", "周期长度", "length"):
            async for r in self._cmd_set_cycle_length(event, value):
                yield r
        elif action in ("经期", "经期长度", "period"):
            async for r in self._cmd_set_period_length(event, value):
                yield r
        elif action in ("开启", "打开", "on", "enable"):
            self.store.set("enabled", True)
            yield event.plain_result(f"已开启{self.character_name}的生理周期。")
        elif action in ("关闭", "停用", "off", "disable"):
            self.store.set("enabled", False)
            yield event.plain_result(f"已关闭{self.character_name}的生理周期。")
        else:
            yield event.plain_result(
                "未知操作。可用：查看 / 设定 / 长度 / 经期 / 开启 / 关闭"
            )

    async def _cmd_set_start(self, event: AstrMessageEvent, value: str | None):
        value = (value or "").strip()
        if value in ("今天", "today", ""):
            target = self._today() if value else None
            if target is None:
                yield event.plain_result("请提供经期开始日，格式 yyyy-mm-dd，或用「今天」。")
                return
        else:
            target = parse_date(value)
            if target is None:
                yield event.plain_result("日期格式错误，请使用 yyyy-mm-dd，例如 2026-05-20。")
                return
        self.store.set_period_start(target.isoformat())
        yield event.plain_result(
            f"已将{self.character_name}的经期开始日设为 {target.isoformat()}。\n\n"
            + self._format_status(self._current_state())
        )

    async def _cmd_set_cycle_length(self, event: AstrMessageEvent, value: str | None):
        try:
            n = int(str(value or "").strip())
            if not (15 <= n <= 45):
                raise ValueError
        except ValueError:
            yield event.plain_result("周期天数需为 15~45 之间的整数。")
            return
        self.store.set("cycle_length", n)
        yield event.plain_result(
            f"已将平均周期设为 {n} 天。\n\n" + self._format_status(self._current_state())
        )

    async def _cmd_set_period_length(self, event: AstrMessageEvent, value: str | None):
        try:
            n = int(str(value or "").strip())
            if not (1 <= n <= 10):
                raise ValueError
        except ValueError:
            yield event.plain_result("经期天数需为 1~10 之间的整数。")
            return
        self.store.set("period_length", n)
        yield event.plain_result(
            f"已将经期长度设为 {n} 天。\n\n" + self._format_status(self._current_state())
        )

    async def terminate(self):
        self.store.save()


