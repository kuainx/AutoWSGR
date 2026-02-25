"""调度层 — 启动编排与任务调度。

提供一站式启动入口和 GameContext 构造：

- :func:`launch` — 加载配置 → 连接模拟器 → 启动游戏 → 返回就绪的 GameContext
- :class:`Launcher` — 可定制的启动器

典型用法::

    from autowsgr.scheduler import launch

    ctx = launch("user_settings.yaml")
    # ctx.ctrl 已连接, 游戏已在主页面
"""

from .launcher import Launcher, launch

__all__ = [
    "Launcher",
    "launch",
]
