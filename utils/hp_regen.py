# utils/hp_regen.py
"""
战斗HP随时间恢复工具
- HP会根据灵根品质（修炼速度倍率）自动恢复
- 灵根越好，回血越快
- 支持在任意 handler/manager 中调用，自动创建所需的依赖
"""

import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig
    from ..models import Player
    from ..config_manager import ConfigManager
    from ..data.data_manager import DataBase


async def regenerate_player_hp(
    player: "Player",
    config: "AstrBotConfig",
    config_manager: "ConfigManager",
    db: Optional["DataBase"] = None
) -> int:
    """
    根据离线时间计算并恢复玩家战斗HP

    HP恢复公式：
        恢复量 = 经过分钟数 × 基础恢复量/分钟 × 灵根速度倍率
        最终HP = min(当前HP + 恢复量, 最大HP)

    Args:
        player: 玩家对象
        config: AstrBotConfig（插件配置，含HP_REGEN_BASE_PER_MINUTE）
        config_manager: ConfigManager（配置管理器，用于读取灵根速度）
        db: 数据库连接（可选，传入则自动持久化）

    Returns:
        int: 本次恢复的HP量
    """
    from ..core.cultivation_manager import CultivationManager

    now = int(time.time())

    # 获取基础恢复速率（每分钟）
    base_regen = float(config.get("HP_REGEN_BASE_PER_MINUTE", 5.0))

    # 获取灵根速度倍率（内部创建 CultivationManager）
    cultivation_manager = CultivationManager(config, config_manager)
    root_speed = cultivation_manager.get_spiritual_root_speed(player)

    # 计算最大HP（与 combat_manager 一致: experience // 2）
    max_hp = player.experience // 2

    # 如果当前HP已满，只更新时间戳
    if player.hp >= max_hp:
        player.last_hp_regen_time = now
        if db:
            await db.ext.update_player_hp_regen_time(player.user_id, now)
        return 0

    # 首次恢复：初始化时间戳
    if player.last_hp_regen_time == 0:
        player.last_hp_regen_time = now
        if db:
            await db.ext.update_player_hp_regen_time(player.user_id, now)
        return 0

    # 计算经过分钟数
    elapsed_seconds = now - player.last_hp_regen_time
    if elapsed_seconds < 60:
        return 0  # 不足1分钟不恢复

    elapsed_minutes = elapsed_seconds / 60.0

    # 计算恢复量
    regen_amount = int(elapsed_minutes * base_regen * root_speed)

    if regen_amount <= 0:
        return 0

    # 更新HP（不超过上限）
    old_hp = player.hp
    player.hp = min(old_hp + regen_amount, max_hp)
    player.last_hp_regen_time = now

    actual_regen = player.hp - old_hp

    # 持久化
    if db and actual_regen > 0:
        await db.ext.update_player_hp_mp(player.user_id, player.hp, player.mp)
        await db.ext.update_player_hp_regen_time(player.user_id, now)

    return actual_regen
