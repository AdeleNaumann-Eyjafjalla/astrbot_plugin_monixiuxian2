# core/equipment_manager.py

from typing import Optional, List, Dict, TYPE_CHECKING
from ..models import Player, Item
from ..data import DataBase

if TYPE_CHECKING:
    from ..config_manager import ConfigManager
    from .storage_ring_manager import StorageRingManager

class EquipmentManager:
    """装备管理器 - 处理装备的穿戴、卸下和属性计算"""

    # 强化等级与所需强化石映射
    ENHANCE_TIERS = {
        0: {"stone": "初级强化石", "max": 3, "success_rate": 1.0},
        1: {"stone": "初级强化石", "max": 3, "success_rate": 1.0},
        2: {"stone": "初级强化石", "max": 3, "success_rate": 1.0},
        3: {"stone": "中级强化石", "max": 6, "success_rate": 0.70},
        4: {"stone": "中级强化石", "max": 6, "success_rate": 0.70},
        5: {"stone": "中级强化石", "max": 6, "success_rate": 0.70},
        6: {"stone": "高级强化石", "max": 9, "success_rate": 0.50},
        7: {"stone": "高级强化石", "max": 9, "success_rate": 0.50},
        8: {"stone": "高级强化石", "max": 9, "success_rate": 0.50},
        9: {"stone": "极品强化石", "max": 12, "success_rate": 0.30},
        10: {"stone": "极品强化石", "max": 12, "success_rate": 0.30},
        11: {"stone": "极品强化石", "max": 12, "success_rate": 0.30},
    }
    MAX_ENHANCE = 12
    ENHANCE_PER_LEVEL = 0.10  # 每级强化 +10% 全属性

    def __init__(self, db: DataBase, config_manager: "ConfigManager" = None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager

    def parse_item_from_name(self, item_name: str, items_data: dict, weapons_data: dict = None, enhance_level: int = 0) -> Optional[Item]:
        """从物品名称解析为Item对象

        Args:
            item_name: 物品名称
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）

        Returns:
            Item对象，如果未找到则返回None
        """
        if not item_name or item_name == "":
            return None

        # 先从物品配置中查找
        item_config = items_data.get(item_name)

        # 如果没找到且提供了武器配置，从武器配置中查找
        if not item_config and weapons_data:
            item_config = weapons_data.get(item_name)

        if not item_config:
            return None

        # 处理新旧格式兼容性
        item_type = item_config.get("type", "")
        physical_damage = item_config.get("physical_damage", 0)
        physical_defense = item_config.get("physical_defense", 0)
        magic_damage = item_config.get("magic_damage", 0)
        magic_defense = item_config.get("magic_defense", 0)
        mental_power = item_config.get("mental_power", 0)

        # 旧格式兼容：处理 items.json 中的法器（equip_effects 格式）
        if "equip_effects" in item_config:
            equip_effects = item_config["equip_effects"]
            # 旧格式 attack -> physical_damage
            if "attack" in equip_effects:
                physical_damage = equip_effects["attack"]
            # 旧格式 defense -> physical_defense
            if "defense" in equip_effects:
                physical_defense = equip_effects["defense"]
            # 旧格式 max_hp 可用于体修的 blood_qi 加成

        # 旧格式兼容：处理类型映射
        # "法器" + subtype="武器" -> "weapon"
        # "法器" + subtype="防具" -> "armor"
        # "法器" + subtype="饰品" -> "accessory" (暂不支持装备)
        if item_type == "法器":
            subtype = item_config.get("subtype", "")
            if subtype == "武器":
                item_type = "weapon"
            elif subtype == "防具":
                item_type = "armor"
            elif subtype == "饰品":
                item_type = "accessory"
        elif item_type == "功法":
            # 旧格式功法 -> technique
            item_type = "technique"

        return Item(
            item_id=item_config.get("id", item_name),
            name=item_name,
            item_type=item_type,
            description=item_config.get("description", ""),
            rank=item_config.get("rank", ""),
            required_level_index=item_config.get("required_level_index", 0),
            weapon_category=item_config.get("weapon_category", ""),
            magic_damage=magic_damage,
            physical_damage=physical_damage,
            magic_defense=magic_defense,
            physical_defense=physical_defense,
            mental_power=mental_power,
            exp_multiplier=item_config.get("exp_multiplier", 0.0),
            spiritual_qi=item_config.get("spiritual_qi", 0),
            blood_qi=item_config.get("blood_qi", 0),
            enhance_level=enhance_level
        )

    def get_equipped_items(self, player: Player, items_data: dict, weapons_data: dict = None) -> List[Item]:
        """获取玩家所有已装备的物品（含强化等级）

        Args:
            player: 玩家对象
            items_data: 物品配置数据字典
            weapons_data: 武器配置数据字典（可选）

        Returns:
            已装备物品列表
        """
        equipped = []
        enhance_data = player.get_equipment_enhance()

        # 武器
        if player.weapon:
            lv = enhance_data.get(player.weapon, 0)
            item = self.parse_item_from_name(player.weapon, items_data, weapons_data, enhance_level=lv)
            if item:
                equipped.append(item)

        # 防具
        if player.armor:
            lv = enhance_data.get(player.armor, 0)
            item = self.parse_item_from_name(player.armor, items_data, weapons_data, enhance_level=lv)
            if item:
                equipped.append(item)

        # 主修心法
        if player.main_technique:
            lv = enhance_data.get(player.main_technique, 0)
            item = self.parse_item_from_name(player.main_technique, items_data, weapons_data, enhance_level=lv)
            if item:
                equipped.append(item)

        # 功法列表
        techniques_list = player.get_techniques_list()
        for technique_name in techniques_list:
            lv = enhance_data.get(technique_name, 0)
            item = self.parse_item_from_name(technique_name, items_data, weapons_data, enhance_level=lv)
            if item:
                equipped.append(item)

        return equipped

    def check_equipment_level_requirement(self, player: Player, item: Item) -> tuple[bool, str]:
        """检查玩家是否满足装备的境界要求

        Args:
            player: 玩家对象
            item: 装备物品

        Returns:
            (是否满足, 提示消息)
        """
        if player.level_index < item.required_level_index:
            # 获取需求境界名称
            required_level_name = self._format_required_level(item.required_level_index)
            return False, f"境界不足！装备【{item.name}】（{item.rank}）需要达到【{required_level_name}】以上"
        return True, ""

    def _format_required_level(self, level_index: int) -> str:
        """格式化需求境界名称（同时显示灵修/体修）"""
        if not self.config_manager:
            return f"境界{level_index}"

        names = []
        # 灵修境界名称
        if 0 <= level_index < len(self.config_manager.level_data):
            name = self.config_manager.level_data[level_index].get("level_name", "")
            if name:
                names.append(name)
        # 体修境界名称
        if 0 <= level_index < len(self.config_manager.body_level_data):
            name = self.config_manager.body_level_data[level_index].get("level_name", "")
            if name and name not in names:
                names.append(name)

        if not names:
            return f"境界{level_index}"
        return " / ".join(names)

    async def equip_item(self, player: Player, item: Item) -> tuple[bool, str]:
        """装备物品

        Args:
            player: 玩家对象
            item: 要装备的物品

        Returns:
            (是否成功, 消息)
        """
        # 检查境界要求
        can_equip, error_msg = self.check_equipment_level_requirement(player, item)
        if not can_equip:
            return False, error_msg

        # 从DB同步储物戒数据（避免 update_player 覆盖 handler 中 retrieve_item 的扣除）
        fresh = await self.db.get_player_by_id(player.user_id)
        if fresh:
            player.storage_ring_items = fresh.storage_ring_items

        # 根据物品类型装备到相应位置
        if item.item_type == "weapon":
            old_item = player.weapon
            # 先尝试将旧装备存入储物戒，再更新玩家装备
            storage_msg = ""
            if old_item:
                success, store_msg = await self.storage_ring_manager.store_item(player, old_item, 1, silent=True) if self.storage_ring_manager else (True, "")
                if not success:
                    return False, f"储物戒空间不足，无法替换装备！\n旧装备【{old_item}】存入失败：{store_msg}"
                storage_msg = f"\n旧装备【{old_item}】已存入储物戒"
            player.weapon = item.name
            await self.db.update_player(player)
            return True, f"已将【{old_item or '空'}】替换为【{item.name}】（{item.rank}）{storage_msg}" if old_item else f"已装备武器【{item.name}】（{item.rank}）"

        elif item.item_type == "armor":
            old_item = player.armor
            storage_msg = ""
            if old_item:
                success, store_msg = await self.storage_ring_manager.store_item(player, old_item, 1, silent=True) if self.storage_ring_manager else (True, "")
                if not success:
                    return False, f"储物戒空间不足，无法替换装备！\n旧装备【{old_item}】存入失败：{store_msg}"
                storage_msg = f"\n旧装备【{old_item}】已存入储物戒"
            player.armor = item.name
            await self.db.update_player(player)
            return True, f"已将【{old_item or '空'}】替换为【{item.name}】（{item.rank}）{storage_msg}" if old_item else f"已装备防具【{item.name}】（{item.rank}）"

        elif item.item_type == "main_technique":
            old_item = player.main_technique
            storage_msg = ""
            if old_item:
                success, store_msg = await self.storage_ring_manager.store_item(player, old_item, 1, silent=True) if self.storage_ring_manager else (True, "")
                if not success:
                    return False, f"储物戒空间不足，无法替换装备！\n旧装备【{old_item}】存入失败：{store_msg}"
                storage_msg = f"\n旧装备【{old_item}】已存入储物戒"
            player.main_technique = item.name
            await self.db.update_player(player)
            return True, f"已将主修心法【{old_item or '空'}】替换为【{item.name}】（{item.rank}）{storage_msg}" if old_item else f"已装备主修心法【{item.name}】（{item.rank}）"

        elif item.item_type == "technique":
            techniques_list = player.get_techniques_list()

            # 检查是否已装备
            if item.name in techniques_list:
                return False, f"功法【{item.name}】已装备"

            # 检查功法栏是否已满（最多3个）
            if len(techniques_list) >= 3:
                return False, f"功法栏已满（最多3个），请先卸下其他功法"

            # 添加功法
            techniques_list.append(item.name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return True, f"已装备功法【{item.name}】（{item.rank}）（{len(techniques_list)}/3）"

        else:
            return False, f"未知的装备类型：{item.item_type}"

    async def unequip_item(self, player: Player, slot_or_name: str) -> tuple[bool, str]:
        """卸下装备

        Args:
            player: 玩家对象
            slot_or_name: 装备槽位名称（武器/防具/主修心法）或功法名称

        Returns:
            (是否成功, 消息)
        """
        # 尝试按槽位卸下
        if slot_or_name in ["武器", "weapon"]:
            if not player.weapon:
                return False, "未装备武器"
            item_name = player.weapon
            player.weapon = ""
            await self.db.update_player(player)
            return True, f"已卸下武器【{item_name}】"

        elif slot_or_name in ["防具", "armor"]:
            if not player.armor:
                return False, "未装备防具"
            item_name = player.armor
            player.armor = ""
            await self.db.update_player(player)
            return True, f"已卸下防具【{item_name}】"

        elif slot_or_name in ["主修心法", "心法", "main_technique"]:
            if not player.main_technique:
                return False, "未装备主修心法"
            item_name = player.main_technique
            player.main_technique = ""
            await self.db.update_player(player)
            return True, f"已卸下主修心法【{item_name}】"

        # 尝试从功法列表中卸下（按名称）
        techniques_list = player.get_techniques_list()
        if slot_or_name in techniques_list:
            techniques_list.remove(slot_or_name)
            player.set_techniques_list(techniques_list)
            await self.db.update_player(player)
            return True, f"已卸下功法【{slot_or_name}】"

        return False, f"未找到装备：{slot_or_name}"

    async def enhance_equipment(self, player: Player, slot: str,
                                 items_data: dict, weapons_data: dict = None) -> tuple:
        """强化已装备的装备"""
        import random

        if slot in ["武器", "weapon"]:
            item_name = player.weapon
            slot_display = "武器"
        elif slot in ["防具", "armor"]:
            item_name = player.armor
            slot_display = "防具"
        elif slot in ["主修心法", "心法", "main_technique"]:
            item_name = player.main_technique
            slot_display = "主修心法"
        else:
            return False, f"无效的强化槽位：{slot}（支持：武器/防具/心法）"

        if not item_name:
            return False, f"你没有装备{slot_display}，无法强化。"

        enhance_data = player.get_equipment_enhance()
        current_level = enhance_data.get(item_name, 0)

        if current_level >= self.MAX_ENHANCE:
            return False, f"【{item_name}】已达最高强化等级 +{self.MAX_ENHANCE}！"

        tier_info = self.ENHANCE_TIERS.get(current_level)
        if not tier_info:
            return False, "强化系统配置错误。"

        stone_name = tier_info["stone"]
        success_rate = tier_info["success_rate"]

        if not self.storage_ring_manager:
            return False, "储物戒系统未初始化。"

        if not self.storage_ring_manager.has_item(player, stone_name, 1):
            return False, (
                f"❌ 储物戒中没有【{stone_name}】！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"当前强化：+{current_level} → 目标：+{current_level + 1}\n"
                f"所需：{stone_name} ×1 | 成功率：{success_rate:.0%}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 前往天机阁购买强化石"
            )

        success, _ = await self.storage_ring_manager.retrieve_item(player, stone_name, 1)
        if not success:
            return False, "取出强化石失败。"

        roll = random.random()
        if roll <= success_rate:
            enhance_data[item_name] = current_level + 1
            player.set_equipment_enhance(enhance_data)
            await self.db.update_player(player)

            item = self.parse_item_from_name(item_name, items_data, weapons_data, enhance_level=current_level + 1)
            attr_display = item.get_attribute_display() if item else "未知"

            return True, (
                f"✨ 强化成功！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{slot_display}【{item_name}】+{current_level} → +{current_level + 1}\n"
                f"当前属性：{attr_display}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"消耗：{stone_name} ×1"
            )
        else:
            await self.db.update_player(player)

            item = self.parse_item_from_name(item_name, items_data, weapons_data, enhance_level=current_level)
            attr_display = item.get_attribute_display() if item else "未知"

            return True, (
                f"💔 强化失败！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{slot_display}【{item_name}】仍为 +{current_level}\n"
                f"当前属性：{attr_display}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"消耗：{stone_name} ×1\n"
                f"💡 再接再厉，下次一定能成功！"
            )

    async def _store_old_equipment(self, player: Player, item_name: str) -> str:
        """尝试将旧装备存入储物戒

        Args:
            player: 玩家对象
            item_name: 物品名称

        Returns:
            存储结果消息
        """
        if not self.storage_ring_manager:
            return ""

        success, msg = await self.storage_ring_manager.store_item(player, item_name, 1, silent=True)
        if success:
            return f"\n旧装备【{item_name}】已存入储物戒"
        else:
            return f"\n⚠️ 旧装备【{item_name}】存入储物戒失败：{msg}"
