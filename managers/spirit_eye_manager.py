# managers/spirit_eye_manager.py
"""天地灵眼系统管理器"""
import time
import random
from typing import Tuple, Optional, Dict, List
from ..data import DataBase
from ..models import Player

__all__ = ["SpiritEyeManager"]

# 灵眼配置
SPIRIT_EYE_TYPES = {
    1: {"name": "下品灵眼", "exp_per_hour": 500, "spawn_rate": 50},
    2: {"name": "中品灵眼", "exp_per_hour": 2000, "spawn_rate": 30},
    3: {"name": "上品灵眼", "exp_per_hour": 8000, "spawn_rate": 15},
    4: {"name": "极品灵眼", "exp_per_hour": 30000, "spawn_rate": 5},
}


class SpiritEyeManager:
    """天地灵眼管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
    
    async def get_user_spirit_eye(self, user_id: str) -> Optional[Dict]:
        """获取用户占据的灵眼"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def get_available_spirit_eyes(self) -> List[Dict]:
        """获取所有无主的灵眼"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id IS NULL OR owner_id = ''"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_all_spirit_eyes(self) -> List[Dict]:
        """获取所有灵眼（含已被占据的）"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes ORDER BY eye_id ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def spawn_spirit_eye(self) -> Tuple[bool, str]:
        """生成新灵眼（定时调用）"""
        # 随机生成灵眼类型
        roll = random.randint(1, 100)
        eye_type = 1
        cumulative = 0
        for etype, config in SPIRIT_EYE_TYPES.items():
            cumulative += config["spawn_rate"]
            if roll <= cumulative:
                eye_type = etype
                break
        
        config = SPIRIT_EYE_TYPES[eye_type]
        
        await self.db.conn.execute(
            """
            INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time)
            VALUES (?, ?, ?, ?)
            """,
            (eye_type, config["name"], config["exp_per_hour"], int(time.time()))
        )
        await self.db.conn.commit()
        
        return True, f"天地间出现了一处【{config['name']}】！速来抢夺！"
    
    async def claim_spirit_eye(self, player: Player, eye_id: int) -> Tuple[bool, str]:
        """抢占无主灵眼（原子操作）"""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 检查是否已有灵眼
            existing = await self.get_user_spirit_eye(player.user_id)
            if existing:
                await self.db.conn.rollback()
                return False, f"❌ 你已占据【{existing['eye_name']}】，无法再抢占。"
            
            # 获取目标灵眼（带锁）
            async with self.db.conn.execute(
                "SELECT * FROM spirit_eyes WHERE eye_id = ?",
                (eye_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await self.db.conn.rollback()
                    return False, "❌ 灵眼不存在。"
                eye = dict(row)
            
            # 检查是否有主
            if eye["owner_id"]:
                await self.db.conn.rollback()
                # 有主 → 返回特殊标记，由handler触发抢夺决斗
                return False, "__SNATCH__"
            
            # 抢占
            now = int(time.time())
            await self.db.conn.execute(
                """UPDATE spirit_eyes SET owner_id = ?, owner_name = ?, claim_time = ?, last_collect_time = ?
                   WHERE eye_id = ? AND (owner_id IS NULL OR owner_id = '')""",
                (player.user_id, player.user_name or player.user_id[:8], now, now, eye_id)
            )
            
            # 检查是否真的抢占成功（防止并发）
            if self.db.conn.total_changes == 0:
                await self.db.conn.rollback()
                return False, "❌ 抢占失败，灵眼已被他人占据。"
            
            await self.db.conn.commit()
            return True, (
                f"✨ 成功抢占【{eye['eye_name']}】！\n"
                f"每小时自动产出 {eye['exp_per_hour']:,} 修为"
            )
        except Exception as e:
            await self.db.conn.rollback()
            raise

    async def transfer_spirit_eye(self, eye_id: int, new_owner_id: str, new_owner_name: str, eye_data: Dict = None) -> Dict:
        """转移灵眼所有权（抢夺决斗后使用），返回灵眼信息"""
        now = int(time.time())
        # 先获取灵眼信息（如果没传入）
        if not eye_data:
            async with self.db.conn.execute(
                "SELECT * FROM spirit_eyes WHERE eye_id = ?", (eye_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                eye_data = dict(row)
        
        # 收益转移时自动结算旧主的未收收益
        old_owner = eye_data.get("owner_id")
        if old_owner:
            await self._auto_collect_one(eye_data, now)
        
        await self.db.conn.execute(
            """UPDATE spirit_eyes 
               SET owner_id = ?, owner_name = ?, claim_time = ?, last_collect_time = ?
               WHERE eye_id = ?""",
            (new_owner_id, new_owner_name, now, now, eye_id)
        )
        await self.db.conn.commit()
        return eye_data

    async def _auto_collect_one(self, eye: Dict, now: int = None) -> int:
        """对单个灵眼自动结算收益，返回结算的修为"""
        if now is None:
            now = int(time.time())
        owner_id = eye.get("owner_id")
        if not owner_id:
            return 0
        
        last_collect = eye.get("last_collect_time") or eye.get("claim_time", 0)
        hours_passed = (now - last_collect) / 3600
        if hours_passed < 1:
            return 0
        
        hours = min(24, int(hours_passed))
        exp_income = eye["exp_per_hour"] * hours
        
        player = await self.db.get_player_by_id(owner_id)
        if player:
            player.experience += exp_income
            await self.db.update_player(player)
        
        await self.db.conn.execute(
            "UPDATE spirit_eyes SET last_collect_time = ? WHERE eye_id = ?",
            (now, eye["eye_id"])
        )
        await self.db.conn.commit()
        return exp_income

    async def auto_collect_all(self) -> List[str]:
        """自动结算所有灵眼收益（定时调用），返回日志行列表"""
        now = int(time.time())
        async with self.db.conn.execute(
            """SELECT * FROM spirit_eyes 
               WHERE owner_id IS NOT NULL AND owner_id != ''"""
        ) as cursor:
            eyes = [dict(row) for row in await cursor.fetchall()]
        
        logs = []
        for eye in eyes:
            exp = await self._auto_collect_one(eye, now)
            if exp > 0:
                hours = min(24, int((now - (eye.get("last_collect_time") or eye.get("claim_time", now))) / 3600))
                logs.append(f"  {eye.get('owner_name', '?')}:【{eye['eye_name']}】+{exp:,}修为({hours}h)")
        
        return logs
    
    async def release_spirit_eye(self, user_id: str) -> Tuple[bool, str]:
        """释放灵眼（自动结算收益后释放）"""
        eye = await self.get_user_spirit_eye(user_id)
        if not eye:
            return False, "❌ 你没有占据灵眼。"
        
        # 释放前先结算未收收益
        exp = await self._auto_collect_one(eye)
        settled_msg = ""
        if exp > 0:
            settled_msg = f"\n自动结算收益：+{exp:,} 修为"
        
        await self.db.conn.execute(
            """
            UPDATE spirit_eyes SET owner_id = NULL, owner_name = NULL, claim_time = NULL, last_collect_time = NULL
            WHERE owner_id = ?
            """,
            (user_id,)
        )
        await self.db.conn.commit()
        
        return True, f"已释放【{eye['eye_name']}】{settled_msg}。"
    
    async def get_spirit_eye_info(self, user_id: str) -> str:
        """获取灵眼信息（含可抢夺列表）"""
        my_eye = await self.get_user_spirit_eye(user_id)
        all_eyes = await self.get_all_spirit_eyes()
        
        lines = ["👁️ 天地灵眼", "━━━━━━━━━━━━━━━"]
        
        if my_eye:
            now = int(time.time())
            last_collect = my_eye.get("last_collect_time") or my_eye.get("claim_time", now)
            hours = (now - last_collect) / 3600
            pending = int(min(24, hours) * my_eye["exp_per_hour"])
            lines.append(f"【我的灵眼】{my_eye['eye_name']}")
            lines.append(f"每小时：+{my_eye['exp_per_hour']:,} 修为（自动收取）")
            if pending > 0:
                lines.append(f"下次结算：约 +{pending:,} 修为")
            lines.append("")
        
        # 分类：无主可抢占 / 有主可抢夺
        unowned = [e for e in all_eyes if not e.get("owner_id")]
        occupied = [e for e in all_eyes if e.get("owner_id") and e.get("owner_id") != user_id]
        
        if unowned:
            lines.append("【无主灵眼 · 可抢占】")
            for eye in unowned[:5]:
                lines.append(f"  [{eye['eye_id']}] {eye['eye_name']} (+{eye['exp_per_hour']}/时)")
            lines.append("")
        
        if occupied:
            lines.append("【有主灵眼 · 可抢夺】")
            for eye in occupied[:5]:
                lines.append(f"  [{eye['eye_id']}] {eye['eye_name']} | 占据：{eye.get('owner_name', '?')}")
            lines.append("")
        
        if not unowned and not occupied:
            lines.append("当前没有灵眼可供抢占或抢夺。")
        
        lines.append("💡 /抢占灵眼 <ID>  抢夺需与现主决斗")
        return "\n".join(lines)
