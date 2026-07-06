# data/dead_root_store.py
"""死亡灵根存储——数据库优先 + JSON 文件兜底，确保灵根永不丢失"""
import json
import os
from pathlib import Path
from typing import Optional
from astrbot.api import logger


# JSON 兜底文件存储在 workspace 根目录的 dead_roots/ 下
def _get_dead_root_dir() -> Path:
    return Path(__file__).parent.parent / "dead_roots"


def _get_filepath(user_id: str) -> Path:
    """获取某个用户的兜底文件路径"""
    return _get_dead_root_dir() / f"{user_id}.json"


async def save_dead_root(db, user_id: str, root: str) -> bool:
    """保存死亡灵根（DB 优先，JSON 文件兜底）
    
    Args:
        db: DataBase 实例
        user_id: 玩家ID
        root: 灵根名称（如 "天灵根"）
    
    Returns:
        True 表示至少一种存储方式成功
    """
    db_success = False
    file_success = False

    # 1) 主力：写入 system_config 表
    try:
        await db.ext.set_system_config(f"dead_root_{user_id}", root)
        # 立即验证
        verified = await db.ext.get_system_config(f"dead_root_{user_id}")
        if verified == root:
            db_success = True
            logger.info(f"[灵根存储] DB 写入+验证成功: {user_id[:8]} -> {root}")
        else:
            logger.error(
                f"[灵根存储] DB 验证失败！期望={root}，实际={verified}，"
                f"user_id={user_id[:8]}，将使用文件兜底"
            )
    except Exception as e:
        logger.error(f"[灵根存储] DB 写入异常: {e}，user_id={user_id[:8]}", exc_info=True)

    # 2) 兜底：写入 JSON 文件（DB 失败或验证不通过时启用）
    if not db_success:
        try:
            dead_root_dir = _get_dead_root_dir()
            dead_root_dir.mkdir(parents=True, exist_ok=True)
            filepath = _get_filepath(user_id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"user_id": user_id, "spiritual_root": root}, f, ensure_ascii=False)
            file_success = True
            logger.info(f"[灵根存储] 文件兜底写入成功: {user_id[:8]} -> {root}")
        except Exception as e:
            logger.critical(f"[灵根存储] 文件兜底也失败了！user_id={user_id[:8]}，灵根 [{root}] 无法保存: {e}", exc_info=True)

    return db_success or file_success


async def get_dead_root(db, user_id: str) -> Optional[str]:
    """读取死亡灵根（DB 优先，JSON 文件兜底）
    
    Args:
        db: DataBase 实例
        user_id: 玩家ID
    
    Returns:
        灵根名称，若均无记录则返回 None
    """
    # 1) 主力：从 system_config 表读取
    try:
        root = await db.ext.get_system_config(f"dead_root_{user_id}")
        if root:
            logger.info(f"[灵根读取] DB 命中: {user_id[:8]} -> {root}")
            return root
    except Exception as e:
        logger.error(f"[灵根读取] DB 读取异常: {e}，user_id={user_id[:8]}，尝试文件兜底", exc_info=True)

    # 2) 兜底：从 JSON 文件读取
    try:
        filepath = _get_filepath(user_id)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            root = data.get("spiritual_root")
            if root:
                logger.info(f"[灵根读取] 文件兜底命中: {user_id[:8]} -> {root}")
                # 文件兜底命中了，同步回 DB
                try:
                    await db.ext.set_system_config(f"dead_root_{user_id}", root)
                    filepath.unlink()  # 清理兜底文件
                    logger.info(f"[灵根读取] 已将文件兜底数据同步回 DB，user_id={user_id[:8]}")
                except Exception:
                    pass
                return root
    except Exception as e:
        logger.error(f"[灵根读取] 文件兜底读取异常: {e}，user_id={user_id[:8]}", exc_info=True)

    logger.warning(f"[灵根读取] DB 和文件均无记录，user_id={user_id[:8]}")
    return None


async def clear_dead_root(db, user_id: str):
    """清除已消费的死亡灵根记录"""
    # 清理 DB
    try:
        await db.ext.set_system_config(f"dead_root_{user_id}", "")
    except Exception:
        pass
    
    # 清理文件兜底
    try:
        filepath = _get_filepath(user_id)
        if filepath.exists():
            filepath.unlink()
    except Exception:
        pass
