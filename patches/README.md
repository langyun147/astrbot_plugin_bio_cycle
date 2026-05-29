# 进阶联动补丁

`astrbot_plugin_bio_cycle` 的**核心功能**与 **favorpro 亲密度门控**是开箱即用的，无需任何补丁
（bio_cycle 单向读取这些插件的数据，不改对方代码）。

但以下三项**深度联动**需要修改对应第三方插件的源码——因为要让对方插件**主动调用** bio_cycle 暴露的接口：

| 补丁 | 作用 | 依赖插件 |
|------|------|----------|
| `life_scheduler.patch` | 让每日生成的**日程内容随生理周期起伏**（经期偏居家休息、排卵期偏外出社交） | [life_scheduler](https://github.com/muyouzhi6/astrbot_plugin_life_scheduler) |
| `daily_sharing.patch` | 让**主动分享/动态**带上当前身体状态与好感关系（新增 `inject_persona_state` 开关） | [daily_sharing](https://github.com/siciyuanweilai/astrbot_plugin_daily_sharing) |
| `proactive_chat.patch` | 让**主动消息**带上时间/日程/生理周期/好感四层状态 | [proactive_chat](https://github.com/DBJD-CR/astrbot_plugin_proactive_chat) |
| `favorpro.patch` | 仅当你启用上面两个**主动链路**联动时需要：给 favorpro 增加只读好感锚接口 | [favorpro](https://github.com/Catfish872/astrbot_plugin_favourpro) |

> 这些补丁是**可选的**。不打补丁，bio_cycle 一样能让角色在对话中体现生理周期；打了补丁，连日程和主动消息也会随周期变化，拟真更完整。

## 如何应用

补丁内路径相对各插件根目录，请进入对应插件的安装目录后应用。以 life_scheduler 为例：

```bash
cd <AstrBot>/data/plugins/astrbot_plugin_life_scheduler
patch -p1 < <AstrBot>/data/plugins/astrbot_plugin_bio_cycle/patches/life_scheduler.patch
# 或者，如果该目录是 git 仓库：
git apply -p1 <...>/patches/life_scheduler.patch
```

其余补丁同理（favorpro 安装目录可能名为 `astrbot_plugin_favourpro`）。应用后**重启 AstrBot** 生效。

## 如果应用失败

第三方插件版本更新后，补丁的上下文行可能对不上导致应用失败。这是正常的——补丁本质只是
「在某插件里新增一个方法、并在某处追加几行调用」。打开 `.patch` 文件，按其中以 `+` 开头的新增
内容，手动把对应方法和调用加进该插件即可。每个补丁改动都很小（几十行），且都用 `try/except`
包裹、未装 bio_cycle 时自动降级，不会影响该插件原有功能。

## 联动接口契约（供二次开发参考）

bio_cycle 对外暴露两个稳定方法，上述补丁本质就是调用它们：

- `get_cycle_context() -> dict`：返回当前阶段、周期天序、身体状态、日程倾向（`schedule_hint`）。
  未启用/未设起点时返回 `{"enabled": False}`。life_scheduler 补丁用它。
- `build_external_cycle_anchor(session_key, *, purpose="active_share", favour=None, relationship=None) -> str`：
  返回可叠加进 system_prompt 的身体状态文本；传入 favour/relationship 时启用亲密度门控
  （够亲密才追加私密表达许可）。广播会话返回空串。主动链路补丁用它。
