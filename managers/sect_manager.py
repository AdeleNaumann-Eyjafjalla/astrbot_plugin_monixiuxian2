# managers/sect_manager.py
"""
宗门系统管理器 - 处理宗门创建、管理、捐献、任务等逻辑
参照NoneBot2插件的xiuxian_sect实现
"""

import json
import random
import time
from typing import Tuple, List, Optional, Dict
from ..data.data_manager import DataBase
from ..models_extended import Sect, UserStatus
from ..models import Player

SECT_NAME_MIN_LENGTH = 2
SECT_NAME_MAX_LENGTH = 12
SECT_NAME_FORBIDDEN = ["管理员", "系统", "官方", "GM", "admin"]


class SectManager:
    """宗门系统管理器"""
    
    # 宗门职位定义
    POSITIONS = {
        0: "宗主",
        1: "长老",
        2: "亲传弟子",
        3: "内门弟子",
        4: "外门弟子"
    }
    
    # 宗门职位权限
    POSITION_PERMISSIONS = {
        0: ["manage_all", "kick", "position_change", "build", "search_skill"],
        1: ["kick_outer", "build"],
        2: ["learn_skill"],
        3: ["learn_skill"],
        4: []  # 外门弟子无特殊权限
    }
    
    def __init__(self, db: DataBase, config_manager=None):
        self.db = db
        self.config_manager = config_manager
        self.config = config_manager.sect_config if config_manager else {}
    
    def _validate_sect_name(self, name: str) -> Tuple[bool, str]:
        """验证宗门名称"""
        if len(name) < SECT_NAME_MIN_LENGTH or len(name) > SECT_NAME_MAX_LENGTH:
            return False, f"❌ 宗门名称长度需在{SECT_NAME_MIN_LENGTH}-{SECT_NAME_MAX_LENGTH}字之间！"
        for forbidden in SECT_NAME_FORBIDDEN:
            if forbidden.lower() in name.lower():
                return False, f"❌ 宗门名称包含禁用词汇！"
        return True, ""
    
    async def create_sect(
        self,
        user_id: str,
        sect_name: str,
        required_stone: int = None,
        required_level: int = None
    ) -> Tuple[bool, str]:
        """
        创建宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            required_stone: 需求灵石（默认为配置值或10000）
            required_level: 需求境界等级（默认为配置值或3）
            
        Returns:
            (成功标志, 消息)
        """
        # 加载配置
        if required_stone is None:
            required_stone = self.config.get("create_cost", 10000)
        if required_level is None:
            required_level = self.config.get("create_level_required", 3)
        # 1. 检查用户是否存在
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查是否已有宗门
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门，无法创建新宗门！"
        
        # 3. 检查境界
        if player.level_index < required_level:
            return False, f"❌ 创建宗门需要达到境界等级 {required_level}！"
        
        # 4. 检查灵石
        if player.gold < required_stone:
            return False, f"❌ 创建宗门需要 {required_stone} 灵石！"
        
        # 验证宗门名称
        valid, error = self._validate_sect_name(sect_name)
        if not valid:
            return False, error
        
        # 5. 检查宗门名称是否重复
        existing_sect = await self.db.ext.get_sect_by_name(sect_name)
        if existing_sect:
            return False, f"❌ 宗门名称『{sect_name}』已被使用！"
        
        # 6. 扣除灵石
        player.gold -= required_stone
        await self.db.update_player(player)
        
        # 7. 创建宗门
        new_sect = Sect(
            sect_id=0,  # 自动生成
            sect_name=sect_name,
            sect_owner=user_id,
            sect_scale=100,  # 初始建设度
            sect_used_stone=0,
            sect_fairyland=0,
            sect_materials=100,  # 初始资材
            mainbuff="0",
            secbuff="0",
            elixir_room_level=0
        )
        
        sect_id = await self.db.ext.create_sect(new_sect)
        
        # 8. 更新玩家宗门信息（设为宗主）
        await self.db.ext.update_player_sect_info(user_id, sect_id, 0)
        
        # 9. 初始化用户buff信息（如果没有）
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 恭喜！你成功创建了宗门『{sect_name}』，成为一代宗主！"
    
    async def join_sect(self, user_id: str, sect_name: str) -> Tuple[bool, str]:
        """
        加入宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门！请先退出当前宗门。"
        
        # 2. 查找宗门
        sect = await self.db.ext.get_sect_by_name(sect_name)
        if not sect:
            return False, f"❌ 未找到宗门『{sect_name}』！"
        
        # 3. 加入宗门（默认为外门弟子）
        await self.db.ext.update_player_sect_info(user_id, sect.sect_id, 4)
        
        # 4. 初始化buff信息
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 你成功加入了宗门『{sect_name}』，成为外门弟子！"
    
    async def leave_sect(self, user_id: str) -> Tuple[bool, str]:
        """
        退出宗门
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入任何宗门！"
        
        # 检查是否为宗主
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect and sect.sect_owner == user_id:
            return False, "❌ 宗主无法直接退出宗门！请先传位或解散宗门。"
        
        sect_name = sect.sect_name if sect else "未知宗门"
        
        # 清除宗门信息（先同步 player 对象，避免 update_player 覆盖 DB 独立提交）
        player.sect_id = 0
        player.sect_position = 4
        player.sect_contribution = 0
        await self.db.ext.update_player_sect_info(user_id, 0, 4)
        await self.db.update_player(player)
        
        return True, f"✨ 你已退出宗门『{sect_name}』！"
    
    async def donate_to_sect(
        self,
        user_id: str,
        stone_amount: int
    ) -> Tuple[bool, str]:
        """
        宗门捐献（1灵石 = 10建设度）
        
        Args:
            user_id: 用户ID
            stone_amount: 捐献灵石数量
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if stone_amount <= 0:
            return False, "❌ 捐献数量必须大于0！"
        
        if player.gold < stone_amount:
            return False, f"❌ 你的灵石不足！当前拥有 {player.gold} 灵石。"
        
        # 扣除灵石
        player.gold -= stone_amount
        
        # 增加宗门贡献度（1灵石 = 1贡献）
        player.sect_contribution += stone_amount
        await self.db.update_player(player)
        
        # 增加宗门建设度和灵石（1灵石 = 10建设度）
        await self.db.ext.donate_to_sect(player.sect_id, stone_amount)
        
        scale_gained = stone_amount * 10
        
        return True, f"✨ 捐献成功！消耗 {stone_amount} 灵石，宗门获得 {scale_gained} 建设度！\n你的宗门贡献度：{player.sect_contribution}"
    
    async def get_sect_info(self, user_id: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        获取宗门信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 宗门数据)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！", None
        
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！", None
        
        # 获取宗主信息
        owner = await self.db.get_player_by_id(sect.sect_owner)
        owner_name = owner.user_name if owner and owner.user_name else sect.sect_owner
        
        # 获取成员数量
        members = await self.db.ext.get_sect_members(sect.sect_id)
        member_count = len(members)
        
        # 构建信息
        position_name = self.POSITIONS.get(player.sect_position, "未知")
        
        info_msg = f"""
🏛️ 宗门信息
━━━━━━━━━━━━━━━

宗门名称：{sect.sect_name}
宗主：{owner_name}
建设度：{sect.sect_scale}
宗门灵石：{sect.sect_used_stone}
宗门资材：{sect.sect_materials}
丹房等级：{sect.elixir_room_level}
成员数量：{member_count}人

你的职位：{position_name}
你的贡献：{player.sect_contribution}
        """.strip()
        
        sect_data = {
            "sect": sect,
            "player_position": player.sect_position,
            "player_contribution": player.sect_contribution,
            "member_count": member_count
        }
        
        return True, info_msg, sect_data
    
    async def list_all_sects(self) -> Tuple[bool, str]:
        """
        获取所有宗门列表
        
        Returns:
            (成功标志, 消息)
        """
        sects = await self.db.ext.get_all_sects()
        
        if not sects:
            return False, "❌ 当前还没有任何宗门！"
        
        msg = "🏛️ 宗门列表\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, sect in enumerate(sects[:10], 1):  # 只显示前10个
            owner = await self.db.get_player_by_id(sect.sect_owner)
            owner_name = owner.user_name if owner and owner.user_name else "未知"
            members = await self.db.ext.get_sect_members(sect.sect_id)
            
            msg += f"{idx}. 【{sect.sect_name}】\n"
            msg += f"   宗主：{owner_name}\n"
            msg += f"   建设度：{sect.sect_scale} | 成员：{len(members)}人\n\n"
        
        return True, msg
    
    async def change_position(
        self,
        operator_id: str,
        target_id: str,
        new_position: int
    ) -> Tuple[bool, str]:
        """
        变更宗门职位
        
        Args:
            operator_id: 操作者ID（必须是宗主）
            target_id: 目标用户ID
            new_position: 新职位（0-4）
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if operator.sect_position != 0:
            return False, "❌ 只有宗主才能变更职位！"
        
        # 检查目标用户
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法变更自己的职位！"
        
        if new_position not in self.POSITIONS:
            return False, "❌ 无效的职位！职位范围：0（宗主）- 4（外门弟子）"
        
        if new_position == 0:
            return False, "❌ 无法直接任命宗主！请使用传位功能。"
        
        # 变更职位
        await self.db.ext.update_player_sect_info(target_id, target.sect_id, new_position)
        
        target_name = target.user_name if target.user_name else target_id
        position_name = self.POSITIONS[new_position]
        
        return True, f"✨ 已将 {target_name} 的职位变更为：{position_name}"
    
    async def transfer_ownership(
        self,
        current_owner_id: str,
        new_owner_id: str
    ) -> Tuple[bool, str]:
        """
        宗主传位
        
        Args:
            current_owner_id: 当前宗主ID
            new_owner_id: 新宗主ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查当前宗主
        current_owner = await self.db.get_player_by_id(current_owner_id)
        if not current_owner or current_owner.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        sect = await self.db.ext.get_sect_by_id(current_owner.sect_id)
        if not sect or sect.sect_owner != current_owner_id:
            return False, "❌ 你不是宗主！"
        
        # 检查新宗主
        new_owner = await self.db.get_player_by_id(new_owner_id)
        if not new_owner:
            return False, "❌ 目标用户不存在！"
        
        if new_owner.sect_id != current_owner.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if new_owner_id == current_owner_id:
            return False, "❌ 无法传位给自己！"
        
        # 执行传位
        sect.sect_owner = new_owner_id
        await self.db.ext.update_sect(sect)
        
        # 更新职位：新宗主->宗主，旧宗主->长老
        await self.db.ext.update_player_sect_info(new_owner_id, sect.sect_id, 0)
        await self.db.ext.update_player_sect_info(current_owner_id, sect.sect_id, 1)
        
        new_owner_name = new_owner.user_name if new_owner.user_name else new_owner_id
        
        return True, f"✨ 宗主之位已传给 {new_owner_name}！你现在是长老。"
    
    async def kick_member(
        self,
        operator_id: str,
        target_id: str
    ) -> Tuple[bool, str]:
        """
        踢出宗门成员
        
        Args:
            operator_id: 操作者ID
            target_id: 目标用户ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者权限
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        # 宗主和长老可以踢人
        if operator.sect_position not in [0, 1]:
            return False, "❌ 只有宗主和长老才能踢出成员！"
        
        # 检查目标
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法踢出自己！"
        
        # 长老只能踢外门弟子
        if operator.sect_position == 1 and target.sect_position <= 3:
            return False, "❌ 长老只能踢出外门弟子！"
        
        # 无法踢出宗主
        if target.sect_position == 0:
            return False, "❌ 无法踢出宗主！"
        
        # 踢出（先同步 target 对象，避免 update_player 覆盖 DB 独立提交）
        target_name = target.user_name if target.user_name else target_id
        target.sect_id = 0
        target.sect_position = 4
        target.sect_contribution = 0
        await self.db.ext.update_player_sect_info(target_id, 0, 4)
        await self.db.update_player(target)
        
        return True, f"✨ 已将 {target_name} 踢出宗门！"

    # 宗门任务文案（按境界档位分组）
    SECT_MISSION_TEXTS = {
        # 入门级：炼气期 (Lv.0-9)
        1: [
            "在宗门后山巡逻，驱赶闯入的低阶妖兽",
            "为药园除草浇水，悉心照料灵草灵植",
            "打扫宗门大殿，清理各处积尘与蛛网",
            "前往附近坊市采买宗门日常物资",
            "整理藏经阁一楼的基础功法典籍",
            "帮执事长老誊抄宗门日志与花名册",
        ],
        # 初级：筑基-金丹 (Lv.10-15)
        2: [
            "前往黑风山清剿作乱的筑基期妖兽",
            "护送宗门物资车队安全抵达邻城",
            "协助长老炼制一炉低阶培元丹",
            "在灵脉矿洞监督杂役开采灵石矿",
            "为新入门弟子讲授基础吐纳功法",
            "巡查宗门方圆百里的结界阵眼",
        ],
        # 中级：元婴-化神 (Lv.16-21)
        3: [
            "深入幽冥深渊调查近日的灵气异动",
            "参与宗门护山大阵的维护与阵眼加固",
            "炼制中品凝神丹补充宗门丹房库存",
            "前往妖兽森林猎取珍稀兽核与灵材",
            "代表宗门出席坊市拍卖会竞价宝物",
            "在灵兽园驯养新捕获的四阶灵兽",
        ],
        # 高级：炼虚-合体 (Lv.22-27)
        4: [
            "剿灭盘踞在宗门领地边缘的强大妖兽",
            "深入上古秘境探索未知区域并绘制地图",
            "主持宗门外围九天玄元大阵的修复",
            "炼制高阶破境符箓以充实宗门武库",
            "追查魔道修士在宗门辖区内活动的踪迹",
            "前往灵脉深处引导地脉灵气增强宗门",
        ],
        # 顶级：大乘及以上 (Lv.28-35)
        5: [
            "深入上古遗迹夺取失传的传承秘法",
            "炼制帝品丹药为宗门太上长老续命",
            "镇压封印松动、即将苏醒的上古凶兽",
            "前往域外战场收集稀世天材地宝",
            "为即将渡劫的宗门强者护法守关",
            "以神念覆盖万里疆域清除潜伏魔物",
        ],
    }

    # 宗门任务失败文案（按档位分组）
    SECT_MISSION_FAIL_TEXTS = {
        1: [
            "在山中迷了路，只找到几株普通草药便悻悻而归",
            "低阶妖兽早已被其他师兄弟清理干净，白跑一趟",
            "除草时不小心踩坏了长老心爱的灵植，被训斥一番",
            "坊市今日休市，只换得些许杂物",
            "典籍分类时搞混了卷轴顺序，被罚重新整理",
        ],
        2: [
            "黑风山的妖兽比预想中凶悍，负伤退回宗门休整",
            "运送途中遭遇山贼伏击，虽击退但物资有所损失",
            "炼丹炉意外炸炉，材料尽毁，只保住些残渣",
            "矿洞塌方，不得不中断看守提前返回",
            "讲授功法时一时语塞，弟子们听得云里雾里",
        ],
        3: [
            "幽冥深渊深处魔气浓郁，修为不足以深入调查",
            "大阵阵眼年久失修，反复尝试仍未能完全修复",
            "炼丹时心绪不宁，一炉凝神丹炼成了废渣",
            "妖兽森林深处遭遇意外兽潮，仓皇撤回宗门",
            "拍卖会上竞拍失败，只能空手而回",
        ],
        4: [
            "妖兽实力远超情报所述，苦战一番仍未能将其剿灭",
            "上古秘境机关重重，在第三层触发了禁制险些丧命",
            "修复大阵时阵眼反噬，被震伤经脉只得中途放弃",
            "炼制符箓时灵力失控，一整叠符纸全部自燃",
            "魔修老奸巨猾设下重重陷阱，追踪线索全断",
        ],
        5: [
            "上古遗迹外围的禁制超乎想象，连续数日未能破解",
            "帝品丹药所需天材地宝欠缺一味，功败垂成",
            "上古凶兽残魂爆发，封印反被震裂，只得加固外层",
            "域外战场上遭遇空间乱流，差点迷失在虚空之中",
            "天劫提前降临，护法被余威波及，渡劫者亦未成功",
        ],
    }

    # 宗门任务奖励配置：(最小贡献, 最大贡献, 资材倍率, 境界要求下限, 档位名称, 成功率)
    SECT_MISSION_TIERS = [
        (10,   30,   10,  0,  "入门",      0.95),
        (30,   80,   10,  10, "筑基-金丹", 0.88),
        (80,   250,  10,  16, "元婴-化神", 0.78),
        (250,  600,  10,  22, "炼虚-合体", 0.68),
        (600,  1500, 10,  28, "大乘之上", 0.55),
    ]

    @staticmethod
    def _get_mission_tier(level_index: int) -> dict:
        """根据境界获取任务档位信息"""
        tier_idx = 0
        for i, (mn, mx, sm, lv_req, name, sr) in enumerate(SectManager.SECT_MISSION_TIERS):
            if level_index >= lv_req:
                tier_idx = i
            else:
                break
        mn, mx, sm, lv_req, name, sr = SectManager.SECT_MISSION_TIERS[tier_idx]
        tier_id = tier_idx + 1  # 1-based for mission text lookup
        return {"tier_id": tier_id, "name": name, "min_contrib": mn, "max_contrib": mx, "stone_mult": sm, "success_rate": sr}

    async def perform_sect_task(self, user_id: str) -> Tuple[bool, str]:
        """
        执行宗门任务（根据境界分档，随机文案）
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
            
        # 检查CD
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)
            
        current_time = int(time.time())
        
        try:
            extra = json.loads(user_cd.extra_data) if user_cd.extra_data else {}
        except (json.JSONDecodeError, TypeError):
            extra = {}
        sect_task_cd = extra.get("sect_task_cd", 0)
        if current_time < sect_task_cd:
            remaining = sect_task_cd - current_time
            return False, f"❌ 宗门任务冷却中！还需 {remaining//60} 分钟。"

        # 根据境界获取任务档位
        tier = self._get_mission_tier(player.level_index)
        mission_text = random.choice(self.SECT_MISSION_TEXTS.get(tier["tier_id"], self.SECT_MISSION_TEXTS[1]))
        
        # 获取境界名称
        realm_name = player.get_level(self.config_manager) if hasattr(self, 'config_manager') else f"Lv.{player.level_index}"
        
        # 判定成功/失败
        success_roll = random.random()
        success = success_roll < tier["success_rate"]
        
        if success:
            # 计算奖励（5%概率暴击2倍）
            contribution_gain = random.randint(tier["min_contrib"], tier["max_contrib"])
            crit = random.random() < 0.05
            if crit:
                contribution_gain *= 2
            stone_gain = contribution_gain * tier["stone_mult"]
        else:
            # 失败：获得 1/4 基础贡献（保底安慰）
            base = random.randint(tier["min_contrib"], tier["max_contrib"])
            contribution_gain = max(1, base // 4)
            stone_gain = contribution_gain * tier["stone_mult"]
            crit = False
            fail_text = random.choice(self.SECT_MISSION_FAIL_TEXTS.get(tier["tier_id"], self.SECT_MISSION_FAIL_TEXTS[1]))
        
        player.sect_contribution += contribution_gain
        player.sect_task += 1
        await self.db.update_player(player)
        
        # 更新宗门资源
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect:
            sect.sect_materials += stone_gain
            await self.db.ext.update_sect(sect)

        # 记录1小时冷却
        extra["sect_task_cd"] = current_time + 1800
        user_cd.extra_data = json.dumps(extra, ensure_ascii=False)
        await self.db.ext.update_user_cd(user_cd)
        
        # 构建返回消息
        if success:
            msg = (
                f"📋 宗门任务【{tier['name']}】\n"
                f"━━━━━━━━━━━━━━━\n"
                f"任务：{mission_text}\n"
                f"境界：{realm_name}\n"
            )
            if crit:
                msg += f"🎉 暴击！贡献翻倍！\n"
            msg += (
                f"结果：✅ 成功\n"
                f"个人贡献：+{contribution_gain}\n"
                f"宗门资材：+{stone_gain}\n"
                f"今日任务：{player.sect_task} 次"
            )
        else:
            msg = (
                f"📋 宗门任务【{tier['name']}】\n"
                f"━━━━━━━━━━━━━━━\n"
                f"任务：{mission_text}\n"
                f"境界：{realm_name}\n"
                f"结果：❌ 失败 ({fail_text})\n"
                f"个人贡献：+{contribution_gain}（保底）\n"
                f"宗门资材：+{stone_gain}\n"
                f"今日任务：{player.sect_task} 次"
            )
        return True, msg

    # 宗门贡献可兑换的破境丹列表（贡献值 = 商店原价 / 10）
    SECT_EXCHANGE_PILLS = [
        # 筑基期
        {"name": "筑基丹",    "target_level": 10, "cost": 500},
        {"name": "固基丹·中",  "target_level": 11, "cost": 800},
        {"name": "固基丹·后",  "target_level": 12, "cost": 1200},
        # 金丹期
        {"name": "结丹丹",    "target_level": 13, "cost": 1500},
        {"name": "温丹丹·中",  "target_level": 14, "cost": 2500},
        {"name": "温丹丹·后",  "target_level": 15, "cost": 4000},
        # 元婴期
        {"name": "凝婴丹",    "target_level": 16, "cost": 5000},
        {"name": "养婴丹·中",  "target_level": 17, "cost": 8000},
        {"name": "养婴丹·后",  "target_level": 18, "cost": 15000},
        # 化神期
        {"name": "化神丹",    "target_level": 19, "cost": 20000},
        {"name": "温神丹·中",  "target_level": 20, "cost": 35000},
        {"name": "温神丹·后",  "target_level": 21, "cost": 60000},
        # 炼虚期
        {"name": "炼虚丹",    "target_level": 22, "cost": 80000},
        {"name": "破虚丹·中",  "target_level": 23, "cost": 150000},
        {"name": "破虚丹·后",  "target_level": 24, "cost": 250000},
        # 合体期
        {"name": "合体丹",    "target_level": 25, "cost": 300000},
        {"name": "融合丹·中",  "target_level": 26, "cost": 500000},
        {"name": "融合丹·后",  "target_level": 27, "cost": 800000},
        # 大乘期
        {"name": "大乘丹",    "target_level": 28, "cost": 1000000},
        {"name": "悟道丹·中",  "target_level": 29, "cost": 2000000},
        {"name": "悟道丹·后",  "target_level": 30, "cost": 3500000},
        # 渡劫期
        {"name": "渡劫丹",    "target_level": 31, "cost": 5000000},
        # 仙境
        {"name": "地仙丹",    "target_level": 32, "cost": 20000000},
        {"name": "天仙丹",    "target_level": 33, "cost": 80000000},
        {"name": "大罗金仙丹", "target_level": 34, "cost": 300000000},
        {"name": "混元丹",    "target_level": 35, "cost": 1000000000},
    ]

    async def get_sect_exchange_list(self, user_id: str) -> Tuple[bool, str]:
        """查看宗门贡献可兑换的破境丹列表"""
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        lines = ["🏛️ 宗门丹房 — 贡献兑换破境丹", "━━━━━━━━━━━━━━━", ""]
        for pill in self.SECT_EXCHANGE_PILLS:
            can_buy = "✅" if player.sect_contribution >= pill["cost"] else "❌"
            lines.append(
                f"{can_buy} {pill['name']}: {pill['cost']:,} 贡献 "
                f"(突破至 {self._format_level_name(pill['target_level'])})"
            )
        lines.extend([
            "",
            f"你的贡献: {player.sect_contribution:,}",
            "使用 /宗门兑换 <丹药名> 兑换破境丹"
        ])
        return True, "\n".join(lines)

    async def exchange_breakthrough_pill(self, user_id: str, pill_name: str) -> Tuple[bool, str]:
        """使用宗门贡献兑换破境丹"""
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        # 查找丹药
        pill_config = None
        for pill in self.SECT_EXCHANGE_PILLS:
            if pill["name"] == pill_name:
                pill_config = pill
                break

        if not pill_config:
            # 构建可选名称列表
            names = ", ".join(p["name"] for p in self.SECT_EXCHANGE_PILLS)
            return False, f"❌ 宗门丹房暂不提供【{pill_name}】！\n可兑换: {names}"

        if player.sect_contribution < pill_config["cost"]:
            return False, f"❌ 贡献不足！需要 {pill_config['cost']:,} 贡献，你当前有 {player.sect_contribution:,}。"

        # 扣除贡献
        player.sect_contribution -= pill_config["cost"]

        # 将丹药存入丹药背包
        inventory = player.get_pills_inventory()
        inventory[pill_name] = inventory.get(pill_name, 0) + 1
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        return True, f"✨ 兑换成功！消耗 {pill_config['cost']:,} 贡献获得【{pill_name}】x1\n剩余贡献: {player.sect_contribution:,}"

    def _format_level_name(self, level_index: int) -> str:
        """将 level_index 转为境界名称"""
        if hasattr(self, 'config_manager') and self.config_manager:
            level_data = getattr(self.config_manager, 'level_data', None)
            if level_data and 0 <= level_index < len(level_data):
                return level_data[level_index].get("level_name", f"Lv.{level_index}")
        return f"Lv.{level_index}"

    async def handle_owner_death(self, sect_id: int, dead_owner_id: str) -> Tuple[bool, str]:
        """处理宗主死亡，自动传位或解散宗门"""
        members = await self.db.ext.get_sect_members(sect_id)
        # 过滤掉死亡的宗主
        remaining = [m for m in members if m.user_id != dead_owner_id]
        
        if not remaining:
            # 无其他成员，解散宗门
            await self.db.ext.delete_sect(sect_id)
            return True, "宗门已解散"
        
        # 按职位和贡献排序，选择新宗主
        remaining.sort(key=lambda m: (m.sect_position, -m.sect_contribution))
        new_owner = remaining[0]
        
        # 更新宗门宗主
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect:
            sect.sect_owner = new_owner.user_id
            await self.db.ext.update_sect(sect)
            await self.db.ext.update_player_sect_info(new_owner.user_id, sect_id, 0)
        
        return True, f"宗主之位已传给{new_owner.user_name or new_owner.user_id}"
