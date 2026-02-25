"""启动器 — 构造就绪的 AndroidController + GameContext。

从零开始完成从配置加载到游戏就绪的全部流程::

    配置加载 → 日志初始化 → 设备连接 → 游戏启动 → 构造 GameContext

使用方式::

    from autowsgr.scheduler.launcher import launch

    ctx = launch("user_settings.yaml")
    # ctx.ctrl  → 已连接的 ADBController
    # ctx.config → UserConfig
    # ctx.ocr   → OCREngine (已初始化)
    # 游戏已在主页面

如需更精细控制，可直接使用 :class:`Launcher`::

    launcher = Launcher(config_path="user_settings.yaml")
    launcher.load_config()
    launcher.connect()
    ctx = launcher.build_context()
    launcher.ensure_ready(ctx)
"""

from __future__ import annotations

from pathlib import Path

from autowsgr.context import GameContext
from autowsgr.emulator import ADBController
from autowsgr.infra import ConfigManager, UserConfig
from autowsgr.infra.logger import get_logger, setup_logger
from autowsgr.vision import EasyOCREngine, OCREngine

_log = get_logger("scheduler")


class Launcher:
    """可定制的启动器。

    分步骤构造 ``AndroidController`` + ``GameContext``，
    每一步可独立调用，便于单元测试或自定义流程。

    Parameters
    ----------
    config_path:
        用户配置文件路径 (YAML)。可以为 ``None``，
        此时必须通过 ``set_config`` 手动传入 :class:`UserConfig`。
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path else None
        self._config: UserConfig | None = None
        self._ctrl: ADBController | None = None
        self._ocr: OCREngine | None = None

    # ── 配置 ──

    def load_config(self) -> UserConfig:
        """从 YAML 加载配置并初始化日志。"""
        if self._config_path is None:
            raise ValueError("config_path 未指定，请在构造时传入或调用 set_config")
        _log.info("[Launcher] 加载配置: {}", self._config_path)
        self._config = ConfigManager.load(self._config_path)
        setup_logger(self._config.log.dir, self._config.log.level)
        return self._config

    def set_config(self, config: UserConfig) -> None:
        """手动设置配置（替代 :meth:`load_config`）。"""
        self._config = config

    @property
    def config(self) -> UserConfig:
        if self._config is None:
            raise RuntimeError("配置未加载，请先调用 load_config() 或 set_config()")
        return self._config

    # ── 设备连接 ──

    def connect(self) -> ADBController:
        """创建并连接 ADBController。

        Returns
        -------
        ADBController
            已建立连接的设备控制器。
        """
        cfg = self.config
        _log.info("[Launcher] 连接设备 (serial={})", cfg.emulator.serial or "auto")
        self._ctrl = ADBController(
            serial=cfg.emulator.serial,
            config=cfg.emulator,
        )
        self._ctrl.connect()
        return self._ctrl

    @property
    def ctrl(self) -> ADBController:
        if self._ctrl is None:
            raise RuntimeError("设备未连接，请先调用 connect()")
        return self._ctrl

    # ── OCR ──

    def create_ocr(self) -> OCREngine:
        """根据配置创建 OCR 引擎。"""
        cfg = self.config
        _log.info("[Launcher] 创建 OCR 引擎 (backend={})", cfg.ocr.backend.value)
        # 目前仅支持 EasyOCR，后续可按 cfg.ocr.backend 分发
        self._ocr = EasyOCREngine.create(gpu=cfg.ocr.gpu)
        return self._ocr

    # ── 构造 GameContext ──

    def build_context(self) -> GameContext:
        """构造 GameContext（基础设施 + 默认游戏状态）。

        必须在 :meth:`connect` 之后调用。
        若未手动调用 :meth:`create_ocr`，会自动初始化 OCR。

        Returns
        -------
        GameContext
            已注入 ``ctrl``、``config``、``ocr`` 的上下文。
        """
        if self._ocr is None:
            self.create_ocr()

        ctx = GameContext(
            ctrl=self.ctrl,
            config=self.config,
            ocr=self._ocr,
        )
        _log.info("[Launcher] GameContext 已构建")
        return ctx

    # ── 游戏启动 ──

    def ensure_ready(self, ctx: GameContext) -> None:
        """确保游戏已启动并位于主页面。

        Parameters
        ----------
        ctx:
            已构建的 GameContext（内部使用 ``ctx.ctrl``）。
        """
        from autowsgr.ops.startup import ensure_game_ready
        from autowsgr.types import GameAPP

        app = ctx.config.account.game_app
        _log.info("[Launcher] 确保游戏就绪 (app={})", app.value)
        ensure_game_ready(ctx.ctrl, app)

    # ── 一步到位 ──

    def launch(self) -> GameContext:
        """一步完成: 加载配置 → 连接 → 构造上下文 → 启动游戏。

        Returns
        -------
        GameContext
            完全就绪的游戏上下文。
        """
        self.load_config()
        self.connect()
        ctx = self.build_context()
        self.ensure_ready(ctx)
        _log.info("[Launcher] 启动完成，游戏已就绪")
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════


def launch(config_path: str | Path) -> GameContext:
    """一站式启动入口。

    加载配置 → 连接模拟器 → 启动游戏 → 返回就绪的 :class:`GameContext`。

    Parameters
    ----------
    config_path:
        用户配置文件路径 (YAML)。

    Returns
    -------
    GameContext
        ``ctx.ctrl`` 已连接、游戏已在主页面。

    Examples
    --------
    ::

        from autowsgr.scheduler import launch

        ctx = launch("user_settings.yaml")
        # 直接使用 ctx 进行后续操作
    """
    return Launcher(config_path).launch()
