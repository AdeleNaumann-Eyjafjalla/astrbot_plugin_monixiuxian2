# data/dead_root_store.py
"""死亡遗产存储——数据库优先 + JSON 文件兜底，确保灵根/灵石/物品永不丢失"""
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from astrbot.api import logger


# JSON 兜底文件存储在 workspace 根目录的 dead_roots/ 下
def _get_dead_root_dir() -> Path:
    return Path(__file__).parent.parent / "dead_roots"


def _get_filepath(user_id: str) -> Path:
    """获取某个用户的兜底文件路径"""
    return _get_dead_root_dir() / f"{user_id}.json"


def _extract_player_legacy(player) -> dict:
    """从玩家对象中提取可继承的数据
    
    Returns:
        dict: 包含 spiritual_root, gold, storage_ring_items, techniques, 
              weapon, armor, main_technique
    """
    import json as _json
    
    legacy = {
        "spiritual_root": getattr(player, "spiritual_root", "未知"),
        "gold": getattr(player, "gold", 0),
    }
    
    # 储物戒物品（已购买的物品都在这里）
    try:
        storage_raw = getattr(player, "storage_ring_items", "{}")
        legacy["storage_ring_items"] = _json.loads(storage_raw) if isinstance(storage_raw, str) else storage_raw
    except Exception:
        legacy["storage_ring_items"] = {}
    
    # 已装备的功法列表
    try:
        techniques_raw = getattr(player, "techniques", "[]")
        legacy["techniques"] = _json.loads(techniques_raw) if isinstance(techniques_raw, str) else techniques_raw
    except Exception:
        legacy["techniques"] = []
    
    # 已装备的武器/防具/心法（卸下放入储物戒继承）
    legacy["weapon"] = getattr(player, "weapon", "")
    legacy["armor"] = getattr(player, "armor", "")
    legacy["main_technique"] = getattr(player, "main_technique", "")
    
    return legacy


def _merge_equipped_to_storage(legacy: dict) -> dict:
    """将已装备的武器/防具/心法/功法合并到储物戒物品字典中"""
    items = dict(legacy.get("storage_ring_items", {}))
    
    # 已装备的武器
    if legacy.get("weapon"):
        weapon = legacy["weapon"]
        items[weapon] = items.get(weapon, 0) + 1
    
    # 已装备的防具
    if legacy.get("armor"):
        armor = legacy["armor"]
        items[armor] = items.get(armor, 0) + 1
    
    # 已装备的主修心法
    if legacy.get("main_technique"):
        tech = legacy["main_technique"]
        items[tech] = items.get(tech, 0) + 1
    
    # 已装备的功法列表
    for tech_name in legacy.get("techniques", []):
        if tech_name:
            items[tech_name] = items.get(tech_name, 0) + 1
    
    return items


async def save_dead_root(db, user_id: str, root: str, player=None) -> bool:
    """保存死亡遗产（灵根+灵石+所有物品）
    
    在 delete_player_cascade 之前调用，保存玩家所有可继承数据。
    
    Args:
        db: DataBase 实例
        user_id: 玩家ID
        root: 灵根名称（如 "天灵根"）
        player: 玩家对象（可选，传入则同时保存物品和灵石）
    
    Returns:
        True 表示至少一种存储方式成功
    """
    db_success = False
    file_success = False
    
    # 构建完整数据
    data = {"user_id": user_id, "spiritual_root": root}
    if player is not None:
        try:
            legacy = _extract_player_legacy(player)
            data.update(legacy)
            logger.info(
                f"[死亡遗产] 提取完成: gold={legacy['gold']}, "
                f"storage_items={len(legacy['storage_ring_items'])}, "
                f"techniques={len(legacy['techniques'])}, "
                f"weapon={bool(legacy['weapon'])}, armor={bool(legacy['armor'])}, "
                f"main_technique={bool(legacy['main_technique'])}"
            )
        except Exception as e:
            logger.error(f"[死亡遗产] 提取玩家数据失败: {e}", exc_info=True)

    # 1) 主力：写入 system_config 表（灵根单独存，其余打包为 JSON）
    try:
        await db.ext.set_system_config(f"dead_root_{user_id}", root)
        # 将物品数据也存入 system_config
        items_json = json.dumps(data, ensure_ascii=False)
        await db.ext.set_system_config(f"dead_legacy_{user_id}", items_json)
        # 验证灵根
        verified = await db.ext.get_system_config(f"dead_root_{user_id}")
        if verified == root:
            db_success = True
            logger.info(f"[死亡遗产] DB 写入+验证成功: {user_id[:8]} -> {root}")
        else:
            logger.error(
                f"[死亡遗产] DB 验证失败！期望={root}，实际={verified}，"
                f"user_id={user_id[:8]}，将使用文件兜底"
            )
    except Exception as e:
        logger.error(f"[死亡遗产] DB 写入异常: {e}，user_id={user_id[:8]}", exc_info=True)

    # 2) 兜底：写入 JSON 文件
    if not db_success:
        try:
            dead_root_dir = _get_dead_root_dir()
            dead_root_dir.mkdir(parents=True, exist_ok=True)
            filepath = _get_filepath(user_id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            file_success = True
            logger.info(f"[死亡遗产] 文件兜底写入成功: {user_id[:8]}")
        except Exception as e:
            logger.critical(
                f"[死亡遗产] 文件兜底也失败了！user_id={user_id[:8]}，"
                f"灵根 [{root}] 及物品无法保存: {e}", exc_info=True
            )

    return db_success or file_success


async def get_dead_root(db, user_id: str) -> Optional[str]:
    """读取死亡灵根（DB 优先，JSON 文件兜底）
    
    Args:
        db: DataBase 实例
        user_id: 玩家ID
    
    Returns:
        灵根名称，若均无记录则返回 None
    """
    data = await get_dead_legacy(db, user_id)
    if data:
        return data.get("spiritual_root")
    return None


async def get_dead_legacy(db, user_id: str) -> Optional[Dict[str, Any]]:
    """读取死亡遗产完整数据（灵根+灵石+物品）
    
    Args:
        db: DataBase 实例
        user_id: 玩家ID
    
    Returns:
        完整遗产数据字典，若均无记录则返回 None
    """
    # 1) 主力：从 system_config 表读取
    try:
        items_json = await db.ext.get_system_config(f"dead_legacy_{user_id}")
        if items_json:
            data = json.loads(items_json)
            if data.get("spiritual_root"):
                logger.info(
                    f"[死亡遗产] DB 命中: {user_id[:8]} -> root={data['spiritual_root']}, "
                    f"gold={data.get('gold', 0)}, items={len(data.get('storage_ring_items', {}))}"
                )
                return data
    except Exception as e:
        logger.error(f"[死亡遗产] DB 读取异常: {e}，user_id={user_id[:8]}，尝试文件兜底", exc_info=True)
    
    # 2) 兜底：从 JSON 文件读取
    try:
        filepath = _get_filepath(user_id)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            root = data.get("spiritual_root")
            if root:
                logger.info(f"[死亡遗产] 文件兜底命中: {user_id[:8]} -> root={root}")
                # 同步回 DB
                try:
                    await db.ext.set_system_config(f"dead_root_{user_id}", root)
                    await db.ext.set_system_config(f"dead_legacy_{user_id}", json.dumps(data, ensure_ascii=False))
                    filepath.unlink()
                    logger.info(f"[死亡遗产] 已将文件数据同步回 DB，user_id={user_id[:8]}")
                except Exception:
                    pass
                return data
    except Exception as e:
        logger.error(f"[死亡遗产] 文件兜底读取异常: {e}，user_id={user_id[:8]}", exc_info=True)

    logger.warning(f"[死亡遗产] DB 和文件均无记录，user_id={user_id[:8]}")
    return None


async def clear_dead_root(db, user_id: str):
    """清除已消费的死亡遗产记录"""
    # 清理 DB
    try:
        await db.ext.set_system_config(f"dead_root_{user_id}", "")
        await db.ext.set_system_config(f"dead_legacy_{user_id}", "")
    except Exception:
        pass
    
    # 清理文件兜底
    try:
        filepath = _get_filepath(user_id)
        if filepath.exists():
            filepath.unlink()
    except Exception:
        pass


async def apply_legacy_to_player(db, player, user_id: str) -> Dict[str, Any]:
    """将死亡遗产应用到新创建的玩家上
    
    将灵石直接加到新玩家金库，物品（储物戒+已装备的全部）合并到储物戒。
    
    Args:
        db: DataBase 实例
        player: 新创建但尚未持久化的玩家对象
        user_id: 用户ID
    
    Returns:
        {"gold": 继承灵石数, "items": 继承物品总数, "items_list": [物品名列表]}
    """
    legacy = await get_dead_legacy(db, user_id)
    if not legacy:
        return {"gold": 0, "items": 0, "items_list": []}
    
    result = {"gold": 0, "items": 0, "items_list": []}
    
    # 恢复灵石
    inherited_gold = legacy.get("gold", 0)
    if inherited_gold > 0:
        player.gold += inherited_gold
        result["gold"] = inherited_gold
        logger.info(f"[遗产继承] 灵石: +{inherited_gold}，user_id={user_id[:8]}")
    
    # 合并所有物品（储物戒原有 + 已装备的全部）到储物戒
    merged_items = _merge_equipped_to_storage(legacy)
    if merged_items:
        current_items = player.get_storage_ring_items()
        for item_name, count in merged_items.items():
            current_items[item_name] = current_items.get(item_name, 0) + count
            result["items_list"].append(item_name)
        player.set_storage_ring_items(current_items)
        result["items"] = len(result["items_list"])
        logger.info(f"[遗产继承] 物品: {result['items']} 件已存入储物戒，user_id={user_id[:8]}")
    
    return result
