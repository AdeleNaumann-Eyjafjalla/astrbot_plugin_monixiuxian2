# handlers/utils.py
# 通用工具函数和装饰器

import time
from functools import wraps
from typing import Callable, Coroutine, AsyncGenerator

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from ..models import Player
from ..models_extended import UserStatus

# 指令常量
CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"

# 闭关状态下允许执行的命令白名单（闭关时只能做最基本的操作）
CULTIVATING_ALLOWED_COMMANDS = [
    # 基础信息查看
    CMD_PLAYER_INFO,
    "我的信息",
    CMD_CHECK_IN,
    "签到",
    # 银行相关
    "银行",
    "存灵石",
    "取灵石",
    "领取利息",
    "贷款",
    "还款",
    "银行流水",
    # 背包查看（只读操作）
    "丹药背包",
    "我的丹药",
    "我的装备",
    "储物戒",
    "查看储物戒",
    # 排行榜查看
    "排行榜",
    "境界榜",
    "战力榜",
    "灵石榜",
    "宗门榜",
    "存款榜",
    # 帮助信息
    "修仙帮助",
    # 闭关相关
    CMD_END_CULTIVATION,
    "出关",
    # 历练/秘境结算
    "结束历练",
    "结束秘境",
    "结束任务",
]

# 历练/探索状态下禁止执行的命令黑名单（只能禁止开启新的冲突活动）
ADVENTURING_BLOCKED_COMMANDS = [
    # 闭关（已在其他活动中）
    CMD_START_CULTIVATION,
    "闭关",
    # 启动新的历练/秘境
    "开始历练",
    "探索秘境",
    # 战斗相关
    "决斗",
    "切磋",
    "挑战Boss",
    # 宗门修改性操作
    "创建宗门",
    "加入宗门",
    "退出宗门",
    "宗门捐献",
    "踢出成员",
    "宗主传位",
    "职位变更",
    # 炼丹（耗时活动）
    "炼丹",
    # 同修
    "同修",
    "接受同修",
    "拒绝同修",
    # 传承挑战
    "传承挑战",
    # 悬赏接取
    "接取悬赏",
    # 灵眼抢占
    "抢占灵眼",
    # 弃道重修
    "弃道重修",
]


def player_required(func: Callable[..., Coroutine[any, any, AsyncGenerator[any, None]]]):
    """
    一个装饰器，用于需要玩家登录才能执行的指令。
    它会自动检查玩家是否存在、状态是否空闲（特定指令除外），否则将玩家对象作为参数注入。
    同时检查贷款状态，如有贷款则显示还款提示。
    """
    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        # self 是 Handler 类的实例 (e.g., PlayerHandler)
        player = await self.db.get_player_by_id(event.get_sender_id())

        if not player:
            yield event.plain_result(f"道友尚未踏入仙途，请发送「{CMD_START_XIUXIAN}」开启你的旅程。")
            return

        # 检查贷款状态并处理逾期
        loan_warning = await _check_loan_status(self.db, player)
        if loan_warning:
            if loan_warning.get("is_dead"):
                # 玩家因逾期被制裁，删除数据
                yield event.plain_result(loan_warning["message"])
                return
        
        message_text = event.get_message_str().strip()
        
        # 检查 user_cd 表的忙碌状态
        user_cd = await self.db.ext.get_user_cd(player.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_time = int(time.time())
            # v3.2.1 自愈：宗门任务是瞬时的，type=4 的旧数据无条件清除
            if user_cd.type == UserStatus.SECT_TASK:
                user_cd.type = UserStatus.IDLE
                user_cd.scheduled_time = 0
                user_cd.extra_data = '{}'
                await self.db.ext.update_user_cd(user_cd)
            elif user_cd.type == UserStatus.CULTIVATING:
                # 闭关状态：使用白名单，仅允许最基本操作
                is_allowed = _is_command_allowed(message_text, CULTIVATING_ALLOWED_COMMANDS)
                if not is_allowed:
                    status_name = UserStatus.get_name(user_cd.type)
                    yield event.plain_result(f"道友当前正在「{status_name}」，无法分心他顾。\n💡 可使用「出关」「我的信息」「签到」「银行」等基础指令。")
                    return
            else:
                # 历练/探索状态：使用黑名单，仅禁止开启新的冲突活动
                is_blocked = _is_command_allowed(message_text, ADVENTURING_BLOCKED_COMMANDS)
                if is_blocked:
                    status_name = UserStatus.get_name(user_cd.type)
                    yield event.plain_result(f"道友当前正在「{status_name}」，无法同时进行此操作。\n💡 可先「结束历练」或「结束秘境」后再试。")
                    return
        
        # 状态检查：如果处于修炼中（闭关），只允许白名单内操作
        if player.state == "修炼中":
            is_allowed = _is_command_allowed(message_text, CULTIVATING_ALLOWED_COMMANDS)

            if not is_allowed:
                yield event.plain_result(f"道友当前正在「{player.state}」中，无法分心他顾。\n💡 可使用「出关」「我的信息」「签到」「银行」等基础指令。")
                return

        # 将 player 对象作为第一个参数传递给原始函数
        async for result in func(self, player, event, *args, **kwargs):
            yield result
        
        # 如果有贷款警告，在指令执行完后显示
        if loan_warning and loan_warning.get("warning_message"):
            yield event.plain_result(loan_warning["warning_message"])

    return wrapper


def _is_command_allowed(message_text: str, allowed_commands: list) -> bool:
    """检查命令是否在允许列表中"""
    for cmd in allowed_commands:
        if message_text.startswith(cmd):
            return True
    return False


async def _check_loan_status(db, player: Player) -> dict:
    """检查玩家贷款状态
    
    Returns:
        dict: {is_dead, message, warning_message} 或 None
    """
    try:
        loan = await db.ext.get_active_loan(player.user_id)
        if not loan:
            return None
        
        now = int(time.time())
        due_at = loan["due_at"]
        
        # 检查是否已逾期
        if now > due_at:
            # 使用事务保护，防止并发删除
            await db.conn.execute("BEGIN IMMEDIATE")
            try:
                # 重新检查贷款状态（可能已被其他请求处理）
                loan = await db.ext.get_active_loan(player.user_id)
                if not loan or loan["status"] != "active":
                    await db.conn.rollback()
                    return None
                
                # 再次检查是否逾期
                if now <= loan["due_at"]:
                    await db.conn.rollback()
                    return None
                
                player_name = player.user_name or f"道友{player.user_id[:6]}"
                
                # 保存灵根供死亡后继承选择（先存后删，DB+文件双保险）
                saved_root = player.spiritual_root
                user_id_for_legacy = player.user_id

                from ..data.dead_root_store import save_dead_root
                await save_dead_root(db, user_id_for_legacy, saved_root)
                logger.info(f"[贷款制裁] 灵根 [{saved_root}] 已保存，user_id={user_id_for_legacy[:8]}")

                # 删除玩家（级联删除所有关联数据）
                await db.delete_player_cascade(user_id_for_legacy)
                
                # 标记贷款逾期
                await db.ext.mark_loan_overdue(loan["id"])
                
                # 记录流水
                await db.ext.add_bank_transaction(
                    player.user_id, "bank_kill", 0, 0,
                    "逾期未还款，被灵石银行制裁", now
                )
                
                await db.conn.commit()
                
                loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
                
                return {
                    "is_dead": True,
                    "message": (
                        f"⚡ 灵石银行制裁令 ⚡\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"道友【{player_name}】因{loan_type_name}逾期未还\n"
                        f"欠款本金：{loan['principal']:,} 灵石\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"灵石银行已收回所有借贷修为\n"
                        f"所有修为和装备化为虚无...\n"
                        f"\n"
                        f"🔮 轮回选择：\n"
                        f"  · 输入「我要修仙 灵修」重新随机灵根\n"
                        f"  · 输入「我要修仙 灵修 继承」保留灵根【{saved_root}】\n"
                        f'（"体修"同理，替换"灵修"即可）'
                    )
                }
            except Exception:
                await db.conn.rollback()
                raise
        
        # 计算剩余时间
        remaining_seconds = due_at - now
        remaining_days = remaining_seconds // 86400
        remaining_hours = (remaining_seconds % 86400) // 3600
        
        # 计算应还金额
        days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
        interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
        total_due = loan["principal"] + interest
        
        loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
        
        # 根据剩余时间设置警告等级
        if remaining_days <= 0:
            urgency = "🔴 紧急"
            time_str = f"{remaining_hours} 小时"
        elif remaining_days <= 1:
            urgency = "🟠 警告"
            time_str = f"{remaining_days} 天 {remaining_hours} 小时"
        else:
            urgency = "🟡 提醒"
            time_str = f"{remaining_days} 天"
        
        warning_message = (
            f"\n━━━━━━━━━━━━━━━\n"
            f"{urgency}【{loan_type_name}还款提醒】\n"
            f"应还金额：{total_due:,} 灵石\n"
            f"剩余时间：{time_str}\n"
            f"⚠️ 逾期将遭受灵石银行严厉制裁！\n"
            f"请使用 /还款 命令还款"
        )
        
        return {
            "is_dead": False,
            "warning_message": warning_message
        }
        
    except Exception:
        return None
