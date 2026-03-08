# AutoWSGR TODO 清单

> 自动整理于 2026-02-21，按优先级分类。仅包含新架构 (`autowsgr/`) 和项目配置中的 TODO；
> 旧架构 (`autowsgr_legacy/`) 的 TODO 将随迁移逐步替代，不再单独跟踪。

---


## 🟡 P1 — 功能增强（已可运行但不够完善）

| # | 位置 | 描述 |
|---|------|------|
| 5 | [`autowsgr/combat/handlers.py#L349`](../autowsgr/combat/handlers.py#L349) | **战果结算可靠性**：`_handle_result()` 需增强可靠性（等待/重试机制） |
| 6 | [`autowsgr/combat/engine.py#L361`](../autowsgr/combat/engine.py#L361) | **掉落舰船 OCR 识别**：`_get_ship_drop()` 当前返回 `None`，需接入 OCR 识别掉落舰船名 |


---

## 旧架构待迁移项（仅供参考）

以下 TODO 存在于 `autowsgr_legacy/` 中，在迁移到新架构时一并处理：

| 位置 | 描述 |
|------|------|
| `autowsgr_legacy/configs.py#L191-L193` | 浴室数 / 修理位置数可自动获取 |
| `autowsgr_legacy/configs.py#L386` | 检查逻辑待验证 |
| `autowsgr_legacy/timer/timer.py#L278` | 重新登录逻辑留空 |
| `autowsgr_legacy/timer/controllers/android_controller.py#L383` | 图片列表嵌套列表支持 |
| `autowsgr_legacy/timer/controllers/os_controller.py#L116` | Windows 版本返回语言检查 |
| `autowsgr_legacy/timer/backends/ocr_backend.py#L338` | OCR 参数调优 |
| `autowsgr_legacy/timer/backends/ocr_backend.py#L381` | 单独训练 OCR 模型 |
| `autowsgr_legacy/game/build.py#L57` | 获取建造舰船名称 |
| `autowsgr_legacy/game/get_game_info.py#L263` | 精确血量检测 |
| `autowsgr_legacy/game/get_game_info.py#L297` | 结算时检测逻辑 |
| `autowsgr_legacy/fight/decisive_battle.py#L331` | 修理策略：中破/大破控制 |
| `autowsgr_legacy/fight/decisive_battle.py#L369` | 提高 OCR 单数字识别率 |
| `autowsgr_legacy/fight/decisive_battle.py#L774` | 缺少磁盘报错 |
| `autowsgr_legacy/fight/common.py#L495` | 处理其他设备登录 |
| `autowsgr_legacy/fight/common.py#L693` | 跳过开幕支援动画 |
