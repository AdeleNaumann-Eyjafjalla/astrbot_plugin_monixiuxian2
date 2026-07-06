# handlers/equipment_handler.py

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..core import EquipmentManager, PillManager, StorageRingManager
from ..config_manager import ConfigManager
from ..models import Player
from .utils import player_required

CMD_SHOW_EQUIPMENT = "我的装备"
CMD_EQUIP_ITEM = "装备"
CMD_UNEQUIP_ITEM = "卸下"
CMD_ENHANCE = "强化"

__all__ = ["EquipmentHandler"]

class EquipmentHandler:
    """装备系统处理器"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = StorageRingManager(db, config_manager)
        self.equipment_manager = EquipmentManager(db, config_manager, self.storage_ring_manager)
        self.pill_manager = PillManager(db, config_manager)

    @player_required
    async def handle_show_equipment(self, player: Player, event: AstrMessageEvent):
        """显示玩家当前装备"""
        display_name = event.get_sender_name()

        # 获取所有已装备物品
        equipped_items = self.equipment_manager.get_equipped_items(
            player,
            self.config_manager.items_data,
            self.config_manager.weapons_data
        )

        await self.pill_manager.update_temporary_effects(player)
        pill_multipliers = self.pill_manager.calculate_pill_attribute_effects(player)

        # 构建装备显示
        equipment_lines = [
            f"=== {display_name} 的装备 ===\n",
            f"【武器】{player.weapon if player.weapon else '未装备'}\n",
            f"【防具】{player.armor if player.armor else '未装备'}\n",
            f"【主修心法】{player.main_technique if player.main_technique else '未装备'}\n",
        ]

        # 功法列表
        techniques_list = player.get_techniques_list()
        equipment_lines.append(f"【功法】({len(techniques_list)}/3)\n")
        if techniques_list:
            for i, tech in enumerate(techniques_list, 1):
                equipment_lines.append(f"  {i}. {tech}\n")
        else:
            equipment_lines.append("  未装备\n")

        # 总属性加成
        if equipped_items:
            equipment_lines.append("\n--- 装备属性加成 ---\n")
            total_attrs = player.get_total_attributes(equipped_items, pill_multipliers)

            # 计算加成值（总属性 - 基础属性）
            magic_damage_bonus = total_attrs["magic_damage"] - player.magic_damage
            physical_damage_bonus = total_attrs["physical_damage"] - player.physical_damage
            magic_defense_bonus = total_attrs["magic_defense"] - player.magic_defense
            physical_defense_bonus = total_attrs["physical_defense"] - player.physical_defense
            mental_power_bonus = total_attrs["mental_power"] - player.mental_power
            max_spiritual_qi_bonus = total_attrs["max_spiritual_qi"] - player.max_spiritual_qi
            exp_multiplier = total_attrs["exp_multiplier"]

            if magic_damage_bonus > 0:
                equipment_lines.append(f"⚔️ 法伤 +{magic_damage_bonus}\n")
            if physical_damage_bonus > 0:
                equipment_lines.append(f"🗡️ 物伤 +{physical_damage_bonus}\n")
            if magic_defense_bonus > 0:
                equipment_lines.append(f"🛡️ 法防 +{magic_defense_bonus}\n")
            if physical_defense_bonus > 0:
                equipment_lines.append(f"🪨 物防 +{physical_defense_bonus}\n")
            if mental_power_bonus > 0:
                equipment_lines.append(f"🧠 精神力 +{mental_power_bonus}\n")
            if max_spiritual_qi_bonus > 0:
                equipment_lines.append(f"✨ 灵气容量 +{max_spiritual_qi_bonus}\n")
            if exp_multiplier > 0:
                equipment_lines.append(f"📈 修为倍率 +{exp_multiplier:.1%}\n")

        equipment_lines.append("=" * 28)

        yield event.plain_result("".join(equipment_lines))

    @player_required
    async def handle_equip_item(self, player: Player, event: AstrMessageEvent, item_name: str):
        """装备物品
        支持语法：
          - 装备 物品名              → 自动判断槽位
          - 装备 主修 功法名         → 指定装备为主修心法
        """
        if not item_name or item_name.strip() == "":
            yield event.plain_result(
                f"请指定要装备的物品名称\n"
                f"用法：{CMD_EQUIP_ITEM} 物品名称\n"
                f"用法：{CMD_EQUIP_ITEM} 主修 功法名称"
            )
            return

        item_name = item_name.strip()

        # 检测「主修」前缀
        as_main_technique = False
        if item_name.startswith("主修 ") or item_name.startswith("主修"):
            if item_name == "主修":
                yield event.plain_result(
                    f"请指定要装备为主修心法的功法名称\n"
                    f"用法：{CMD_EQUIP_ITEM} 主修 功法名称"
                )
                return
            as_main_technique = True
            item_name = item_name[2:].strip()  # 去掉"主修"前缀

        if not item_name:
            yield event.plain_result(f"请指定要装备的物品名称")
            return

        # 检查物品是否存在于配置中（先查items再查weapons）
        item_config = self.config_manager.items_data.get(item_name)
        if not item_config:
            item_config = self.config_manager.weapons_data.get(item_name)

        if not item_config:
            yield event.plain_result(f"未找到物品：{item_name}")
            return

        # 检查物品类型是否可装备
        raw_item_type = item_config.get("type", "")
        equippable_types = ["weapon", "armor", "main_technique", "technique"]

        # 兼容旧格式
        if raw_item_type == "法器":
            subtype = item_config.get("subtype", "")
            if subtype == "武器":
                item_type = "weapon"
            elif subtype == "防具":
                item_type = "armor"
            else:
                # 饰品等其他法器暂不支持装备
                item_type = raw_item_type
        elif raw_item_type == "功法":
            # 「装备 主修 xxx」→ 装备为主修心法
            if as_main_technique:
                item_type = "main_technique"
            else:
                item_type = "technique"
        else:
            item_type = raw_item_type

        if item_type not in equippable_types:
            yield event.plain_result(f"【{item_name}】不是可装备的物品类型")
            return

        # 如果用户指定「主修」但物品不是功法，提示错误
        if as_main_technique and raw_item_type != "功法":
            yield event.plain_result(f"【{item_name}】是{raw_item_type}，不能作为主修心法装备")
            return

        # 检查储物戒中是否有该物品
        if not self.storage_ring_manager.has_item(player, item_name, 1):
            yield event.plain_result(
                f"❌ 储物戒中没有【{item_name}】\n"
                f"请先通过购买或获得该装备"
            )
            return

        # 从储物戒取出物品
        success, retrieve_msg = await self.storage_ring_manager.retrieve_item(player, item_name, 1)
        if not success:
            yield event.plain_result(f"❌ 无法从储物戒取出装备：{retrieve_msg}")
            return

        # 使用 equipment_manager 的 parse_item_from_name 创建 Item 对象
        # （确保旧格式 equip_effects 兼容映射、强化等级等正确应用）
        item = self.equipment_manager.parse_item_from_name(
            item_name,
            self.config_manager.items_data,
            self.config_manager.weapons_data,
            enhance_level=0
        )
        if not item:
            yield event.plain_result(f"无法解析物品：{item_name}")
            return

        # 覆盖类型为 handler 判断的结果（parse_item_from_name 可能有默认映射差异）
        item.item_type = item_type

        # 装备物品
        success, message = await self.equipment_manager.equip_item(player, item)

        if success:
            # 显示属性加成
            attr_display = item.get_attribute_display()
            result_msg = (
                f"✅ {message}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"属性加成：{attr_display}"
            )
            yield event.plain_result(result_msg)
        else:
            # 装备失败，将物品放回储物戒
            await self.storage_ring_manager.store_item(player, item_name, 1, silent=True)
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_unequip_item(self, player: Player, event: AstrMessageEvent, slot_or_name: str):
        """卸下装备"""
        if not slot_or_name or slot_or_name.strip() == "":
            yield event.plain_result(
                f"请指定要卸下的装备\n"
                f"用法：{CMD_UNEQUIP_ITEM} 武器/防具/心法/功法名称"
            )
            return

        slot_or_name = slot_or_name.strip()

        # 获取卸下前的装备名称，用于存入储物戒
        unequipped_item_name = None
        if slot_or_name in ["武器", "weapon"]:
            unequipped_item_name = player.weapon
        elif slot_or_name in ["防具", "armor"]:
            unequipped_item_name = player.armor
        elif slot_or_name in ["主修心法", "心法", "main_technique"]:
            unequipped_item_name = player.main_technique
        else:
            # 检查功法列表
            techniques_list = player.get_techniques_list()
            if slot_or_name in techniques_list:
                unequipped_item_name = slot_or_name

        # 卸下装备
        success, message = await self.equipment_manager.unequip_item(player, slot_or_name)

        if success:
            # 卸下成功后，将装备存入储物戒
            storage_msg = ""
            if unequipped_item_name:
                store_success, store_msg = await self.storage_ring_manager.store_item(
                    player, unequipped_item_name, 1, silent=True
                )
                if store_success:
                    storage_msg = f"\n已存入储物戒"
                else:
                    storage_msg = f"\n⚠️ 存入储物戒失败：{store_msg}"
            
            yield event.plain_result(f"✅ {message}{storage_msg}")
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_enhance(self, player: Player, event: AstrMessageEvent, slot: str = ""):
        """强化装备"""
        if not slot or slot.strip() == "":
            yield event.plain_result(
                "请指定要强化的装备槽位\n"
                "用法：强化 武器/防具/心法\n"
                "示例：强化 武器"
            )
            return

        slot = slot.strip()
        success, msg = await self.equipment_manager.enhance_equipment(
            player, slot, 
            self.config_manager.items_data,
            self.config_manager.weapons_data
        )
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
