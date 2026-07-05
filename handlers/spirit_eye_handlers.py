# handlers/spirit_eye_handlers.py
"""天地灵眼处理器"""
import re
import time
from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import *
from ..data import DataBase
from ..managers.spirit_eye_manager import SpiritEyeManager
from ..managers.combat_manager import CombatManager, CombatStats
from ..models import Player
from ..models_extended import UserStatus
from .utils import player_required

__all__ = ["SpiritEyeHandlers"]

# 抢夺冷却 = 决斗冷却（5分钟）
SNATCH_COOLDOWN = 300


class SpiritEyeHandlers:
    """天地灵眼处理器"""
    
    def __init__(self, db: DataBase, eye_mgr: SpiritEyeManager, combat_mgr: CombatManager, config_manager=None):
        self.db = db
        self.mgr = eye_mgr
        self.combat_mgr = combat_mgr
        self.config_manager = config_manager
    
    @player_required
    async def handle_spirit_eye_info(self, player: Player, event: AstrMessageEvent):
        """查看灵眼信息"""
        info = await self.mgr.get_spirit_eye_info(player.user_id)
        yield event.plain_result(info)
    
    @player_required
    async def handle_claim(self, player: Player, event: AstrMessageEvent, eye_id: int = 0):
        """抢占/抢夺灵眼"""
        if eye_id <= 0:
            yield event.plain_result("❌ 请指定灵眼ID，例如：/抢占灵眼 1")
            return
        
        user_id = player.user_id
        
        # 先尝试直接抢占无主灵眼
        success, msg = await self.mgr.claim_spirit_eye(player, eye_id)
        if msg == "__SNATCH__":
            # 有主灵眼 → 触发抢夺决斗
            async for r in self._handle_snatch(user_id, player.user_name or user_id[:8], eye_id, event):
                yield r
            return
        
        yield event.plain_result(msg)
    
    async def _handle_snatch(self, user_id: str, user_name: str, eye_id: int, event: AstrMessageEvent):
        """抢夺有主灵眼（决斗）"""
        # 获取灵眼信息
        eye = None
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE eye_id = ?", (eye_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                yield event.plain_result("❌ 灵眼不存在。")
                return
            eye = dict(row)
        
        target_id = eye.get("owner_id")
        target_name = eye.get("owner_name", "?")
        
        if not target_id:
            yield event.plain_result("❌ 此灵眼无主，请直接抢占。")
            return
        
        if user_id == target_id:
            yield event.plain_result("❌ 不能抢夺自己的灵眼。")
            return
        
        # 检查发起者状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            yield event.plain_result(f"❌ 你当前正在{UserStatus.get_name(user_cd.type)}，无法抢夺！")
            return
        
        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            yield event.plain_result(f"❌ 对方当前正在{UserStatus.get_name(target_cd.type)}，无法抢夺！")
            return
        
        # 检查战斗冷却
        cooldown = await self._get_combat_cooldown(user_id)
        last_duel = cooldown.get("last_duel_time", 0)
        now = int(time.time())
        if last_duel and (now - last_duel) < SNATCH_COOLDOWN:
            remaining = SNATCH_COOLDOWN - (now - last_duel)
            yield event.plain_result(f"❌ 战斗冷却中，还需 {remaining // 60} 分 {remaining % 60} 秒")
            return
        
        # 获取双方战斗属性
        p1_stats = await self._prepare_combat_stats(user_id)
        p2_stats = await self._prepare_combat_stats(target_id)
        
        if not p1_stats:
            yield event.plain_result("❌ 你还未踏入修仙之路")
            return
        if not p2_stats:
            yield event.plain_result("❌ 对方还未踏入修仙之路")
            return
        
        # 决斗！
        result = self.combat_mgr.player_vs_player(p1_stats, p2_stats, combat_type=2)
        
        # 结算 HP
        await self.db.ext.update_player_hp_mp(user_id, result['player1_final_hp'], result['player1_final_mp'])
        await self.db.ext.update_player_hp_mp(target_id, result['player2_final_hp'], result['player2_final_mp'])
        
        # 更新冷却
        await self._update_combat_cooldown(user_id, "duel")
        
        # 战报
        log_lines = result['combat_log'][:]
        log_lines.append("")
        
        if result['winner'] == user_id:
            # 抢夺成功
            await self.mgr.transfer_spirit_eye(eye_id, user_id, user_name, eye)
            log_lines.append(f"🏆 抢夺成功！你夺得了【{eye['eye_name']}】！")
            log_lines.append(f"每小时自动产出 {eye['exp_per_hour']:,} 修为")
        elif result['winner'] == target_id:
            log_lines.append(f"💔 抢夺失败，【{target_name}】守住了【{eye['eye_name']}】。")
        else:
            log_lines.append(f"🤝 平局！【{eye['eye_name']}】仍归【{target_name}】所有。")
        
        yield event.plain_result("\n".join(log_lines))
    
    @player_required
    async def handle_release(self, player: Player, event: AstrMessageEvent):
        """释放灵眼"""
        success, msg = await self.mgr.release_spirit_eye(player.user_id)
        yield event.plain_result(msg)

    # ===== 战斗辅助方法 =====

    async def _get_combat_cooldown(self, user_id: str) -> dict:
        try:
            async with self.db.conn.execute(
                "SELECT last_duel_time, last_spar_time FROM combat_cooldowns WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"last_duel_time": row[0], "last_spar_time": row[1]}
        except Exception:
            pass
        return {"last_duel_time": 0, "last_spar_time": 0}
    
    async def _update_combat_cooldown(self, user_id: str, combat_type: str):
        now = int(time.time())
        try:
            if combat_type == "duel":
                await self.db.conn.execute(
                    """INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                       VALUES (?, ?, 0) ON CONFLICT(user_id) DO UPDATE SET last_duel_time = ?""",
                    (user_id, now, now)
                )
            else:
                await self.db.conn.execute(
                    """INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                       VALUES (?, 0, ?) ON CONFLICT(user_id) DO UPDATE SET last_spar_time = ?""",
                    (user_id, now, now)
                )
            await self.db.conn.commit()
        except Exception:
            pass

    def _calculate_equipment_bonus(self, player) -> dict:
        bonus = {"atk": 0, "defense": 0}
        if not self.config_manager:
            return bonus
        if player.weapon and player.weapon in self.config_manager.weapons_data:
            data = self.config_manager.weapons_data[player.weapon]
            bonus["atk"] += data.get("atk", 0)
            bonus["atk"] += data.get("physical_damage", 0)
            bonus["atk"] += data.get("magic_damage", 0)
        if player.armor and player.armor in self.config_manager.items_data:
            data = self.config_manager.items_data[player.armor]
            bonus["defense"] += data.get("physical_defense", 0)
            bonus["defense"] += data.get("magic_defense", 0)
        return bonus

    async def _prepare_combat_stats(self, user_id: str):
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return None
        
        impart_info = await self.db.ext.get_impart_info(user_id)
        hp_buff = impart_info.impart_hp_per if impart_info else 0.0
        mp_buff = impart_info.impart_mp_per if impart_info else 0.0
        atk_buff = impart_info.impart_atk_per if impart_info else 0.0
        
        hp, mp = self.combat_mgr.calculate_hp_mp(player.experience, hp_buff, mp_buff)
        base_atk = self.combat_mgr.calculate_atk(player.experience, player.atkpractice, atk_buff)
        equip_bonus = self._calculate_equipment_bonus(player)
        final_atk = base_atk + equip_bonus["atk"]
        
        player.hp = hp
        player.mp = mp
        player.atk = final_atk
        await self.db.update_player(player)
        
        return CombatStats(
            user_id=user_id,
            name=player.user_name if player.user_name else f"道友{user_id}",
            hp=hp, max_hp=hp,
            mp=mp, max_mp=mp,
            atk=final_atk,
            defense=equip_bonus["defense"],
            exp=player.experience
        )
