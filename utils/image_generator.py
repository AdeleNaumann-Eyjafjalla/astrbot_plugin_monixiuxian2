import asyncio
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

# 资源路径配置
# 默认寻找 data/xiuxian 目录 (AstrBot数据目录下的xiuxian文件夹)
ASSETS_PATH = Path(get_astrbot_data_path()) / "xiuxian"
FONT_PATH = ASSETS_PATH / "font" / "font.ttf"
IMG_PATH = ASSETS_PATH / "info_img"

# 跨平台中文字体优先级列表
_CJK_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
]

def _find_cjk_font_path() -> Optional[str]:
    """查找可用的中文字体文件路径"""
    # 先尝试插件的自定义字体
    if FONT_PATH.exists():
        return str(FONT_PATH)
    # 再尝试系统字体
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None

# 缓存找到的字体路径
_CACHED_CJK_FONT_PATH = _find_cjk_font_path()

class ImageGenerator:
    """图片生成器"""
    
    def __init__(self):
        self.has_pil = HAS_PIL
        if not self.has_pil:
            logger.warning("【修仙插件】未检测到 Pillow 库，将无法生成图片卡片。请安装 pip install Pillow")
            
    def _get_font(self, size: int):
        if not FONT_PATH.exists():
            # 尝试使用系统字体或默认
            return ImageFont.load_default()
        return ImageFont.truetype(str(FONT_PATH), size)

    @staticmethod
    def _get_cjk_font(size: int) -> ImageFont.FreeTypeFont:
        """获取中文字体，优先资源包字体，其次系统字体"""
        global _CACHED_CJK_FONT_PATH
        if _CACHED_CJK_FONT_PATH and Path(_CACHED_CJK_FONT_PATH).exists():
            return ImageFont.truetype(_CACHED_CJK_FONT_PATH, size)
        # 重新查找
        _CACHED_CJK_FONT_PATH = _find_cjk_font_path()
        if _CACHED_CJK_FONT_PATH:
            return ImageFont.truetype(_CACHED_CJK_FONT_PATH, size)
        return ImageFont.load_default()

    async def generate_user_info_card(self, user_id: str, detail_map: Dict) -> Optional[BytesIO]:
        """
        生成用户信息卡片
        
        Args:
            user_id: 用户ID
            detail_map: 属性字典 (参考 NoneBot 插件格式)
            
        Returns:
            BytesIO: 图片数据，如果生成失败返回None
        """
        if not self.has_pil:
            return None
            
        if not IMG_PATH.exists():
            logger.warning(f"【修仙插件】资源目录 {IMG_PATH} 不存在，无法生成卡片。")
            return None

        try:
            # 跑在线程池中避免阻塞
            return await asyncio.to_thread(self._draw_info_card_sync, user_id, detail_map)
        except Exception as e:
            logger.error(f"生成图片失败: {e}")
            return None

    def _draw_info_card_sync(self, user_id: str, detail_map: Dict) -> BytesIO:
        # 画布基础尺寸
        width = 1100
        height = 2250
        
        # 1. 背景图
        back_path = IMG_PATH / "back.png"
        if back_path.exists():
            img = Image.open(back_path).convert("RGBA").resize((width, height))
        else:
            img = Image.new("RGBA", (width, height), (50, 50, 50, 255))
            
        # 字体
        font_36 = self._get_font(36)
        font_40 = self._get_font(40)
        color_text = (242, 250, 242)
        
        draw = ImageDraw.Draw(img)
        
        # 简单绘制逻辑 (复刻原版布局)
        
        # 2. 基本信息栏 (头像位置预留)
        # 绘制 QQ/User ID
        line3_path = IMG_PATH / "line3.png"
        if line3_path.exists():
            line3 = Image.open(line3_path).convert("RGBA").resize((400, 60))
            # 绘制ID
            l_draw = ImageDraw.Draw(line3)
            id_text = f"ID: {user_id}"
            w = l_draw.textlength(id_text, font=font_36)
            l_draw.text(((400-w)/2, 10), id_text, fill=color_text, font=font_36)
            img.paste(line3, (130, 520), line3)

        # 3. 属性列表 (右侧)
        right_keys = ['道号', '境界', '修为', '灵石', '战力']
        base_y = 100
        for i, key in enumerate(right_keys):
            val = detail_map.get(key, "未知")
            self._draw_status_line(img, key, str(val), 550, base_y + i * 103, font_36, color_text)

        # 4. 基本信息 (中间)
        self._draw_section_header(img, "【基本信息】", 600, font_40, color_text)
        base_keys = ["灵根", "突破状态", "主修功法", "攻击力", "法器", "防具"]
        base_list_y = 703
        for i, key in enumerate(base_keys):
            val = detail_map.get(key, "无")
            self._draw_wide_line(img, key, str(val), 100, base_list_y + i * 103, font_36, color_text)

        # 5. 宗门信息
        sect_y_header = base_list_y + len(base_keys) * 103 + 50 # 动态计算高度? 原版是硬编码
        sect_y_header = 1442 # 原版硬编码
        self._draw_section_header(img, "【宗门信息】", sect_y_header, font_40, color_text)
        
        sect_keys = ["所在宗门", "宗门职位"]
        sect_y_list = 1547
        for i, key in enumerate(sect_keys):
            val = detail_map.get(key, "无")
            self._draw_wide_line(img, key, str(val), 100, sect_y_list + i * 103, font_36, color_text)

        # 6. 转换输出
        img = img.convert("RGB")
        output = BytesIO()
        img.save(output, format="JPEG", quality=90)
        output.seek(0)
        return output

    # ===== 帮助图片生成 =====

    async def generate_help_image(self, lines: List[str]) -> Optional[str]:
        """生成帮助图片，返回临时文件路径"""
        if not self.has_pil:
            return None
        try:
            return await asyncio.to_thread(self._draw_help_sync, lines)
        except Exception as e:
            logger.error(f"【修仙插件】生成帮助图片失败: {e}")
            return None

    def _draw_help_sync(self, lines: List[str]) -> Optional[str]:
        """同步绘制帮助图片"""
        # 颜色方案：深色修仙主题
        BG_COLOR = (22, 24, 46)         # 深蓝黑背景
        TITLE_COLOR = (255, 215, 80)    # 金色标题
        HEADER_COLOR = (240, 180, 60)   # 暗金 section header
        BODY_COLOR = (210, 210, 220)    # 浅灰白正文
        CMD_COLOR = (180, 220, 255)     # 淡蓝指令名
        DESC_COLOR = (150, 155, 170)    # 灰色描述
        ACCENT_COLOR = (255, 120, 80)   # 橘红强调
        WARN_COLOR = (255, 160, 60)     # 橙色警告
        SEP_COLOR = (60, 62, 80)        # 分隔线色

        # 字体
        title_font = self._get_cjk_font(36)
        header_font = self._get_cjk_font(22)
        body_font = self._get_cjk_font(18)
        small_font = self._get_cjk_font(13)

        # 尺寸计算
        PAD_X = 50
        PAD_TOP = 40
        PAD_BOTTOM = 40
        LINE_HEIGHT = 28
        HEADER_GAP = 12     # section header 前额外间距
        width = 860

        # 先计算总高度
        total_height = PAD_TOP
        for line in lines:
            stripped = line.strip()
            if not stripped:
                total_height += LINE_HEIGHT // 2
            elif stripped.startswith("📖") or stripped.startswith("━━"):
                total_height += LINE_HEIGHT if "📖" in stripped else LINE_HEIGHT // 2
            elif any(stripped.startswith(c) for c in "📖🧘🎒💊🏪📦🏦📜🏛️⚔️📊🚶🌀🔥✨🏔️🌾💕👁️"):
                total_height += LINE_HEIGHT + HEADER_GAP
            elif stripped.startswith("💡") or stripped.startswith("📋"):
                total_height += LINE_HEIGHT + HEADER_GAP
            else:
                total_height += LINE_HEIGHT
        total_height += PAD_BOTTOM

        # 创建画布
        img = Image.new("RGB", (width, total_height), BG_COLOR)
        draw = ImageDraw.Draw(img)

        y = PAD_TOP

        for line in lines:
            stripped = line.strip()
            if not stripped:
                y += LINE_HEIGHT // 2
                continue

            # 标题行
            if stripped.startswith("📖 修仙指令大全"):
                bbox = draw.textbbox((0, 0), stripped, font=title_font)
                tw = bbox[2] - bbox[0]
                draw.text(((width - tw) / 2, y), stripped, fill=TITLE_COLOR, font=title_font)
                y += LINE_HEIGHT + 8

            # 分隔线
            elif stripped.startswith("━━"):
                line_y = y + LINE_HEIGHT // 2
                draw.line([(PAD_X, line_y), (width - PAD_X, line_y)], fill=SEP_COLOR, width=1)
                y += LINE_HEIGHT

            # section header (emoji开头)
            elif any(stripped.startswith(c) for c in "📖🧘🎒💊🏪📦🏦📜🏛️⚔️📊🚶🌀🔥✨🏔️🌾💕👁️"):
                y += HEADER_GAP
                draw.rectangle([(PAD_X - 10, y - 2), (width - PAD_X + 10, y + LINE_HEIGHT - 2)],
                              fill=(32, 34, 52))
                draw.text((PAD_X, y), stripped, fill=HEADER_COLOR, font=header_font)
                y += LINE_HEIGHT

            # 底部信息
            elif stripped.startswith("📋") or stripped.startswith("💡"):
                y += HEADER_GAP
                if stripped.startswith("💡"):
                    bbox = draw.textbbox((0, 0), stripped, font=small_font)
                    tw = bbox[2] - bbox[0]
                    draw.text(((width - tw) / 2, y), stripped, fill=WARN_COLOR, font=small_font)
                else:
                    bbox = draw.textbbox((0, 0), stripped, font=small_font)
                    tw = bbox[2] - bbox[0]
                    draw.text(((width - tw) / 2, y), stripped, fill=DESC_COLOR, font=small_font)
                y += LINE_HEIGHT

            # 具体的指令/描述行
            else:
                indent = PAD_X
                if stripped.startswith("└─"):
                    indent = PAD_X + 30
                    draw.text((indent, y), stripped, fill=DESC_COLOR, font=body_font)
                elif stripped.startswith("⚠"):
                    indent = PAD_X + 20
                    draw.text((indent, y), stripped, fill=WARN_COLOR, font=body_font)
                elif "─ " in stripped:
                    # 指令名─描述 格式
                    cmd, desc = stripped.split("─ ", 1)
                    draw.text((indent, y), cmd.strip(), fill=CMD_COLOR, font=body_font)
                    bbox = draw.textbbox((0, 0), cmd.strip(), font=body_font)
                    cw = bbox[2] - bbox[0]
                    draw.text((indent + cw + 10, y), "─ " + desc, fill=DESC_COLOR, font=body_font)
                else:
                    draw.text((indent, y), stripped, fill=CMD_COLOR, font=body_font)
                y += LINE_HEIGHT

        # 保存到插件目录（固定路径，每次覆盖）
        from pathlib import Path
        output_dir = Path(get_astrbot_data_path()) / "plugins" / "astrbot_plugin_monixiuxian2"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "help_card.png"
        img.save(str(output_path), format="PNG")

        logger.info(f"【修仙插件】帮助图片已生成: {output_path} ({width}x{total_height})")
        return str(output_path)

    def _draw_status_line(self, img, key, value, x, y, font, color):
        path = IMG_PATH / "line3.png"
        text = f"{key}:{value}"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((450, 68))
            d = ImageDraw.Draw(line)
            try:
                # Pillow 9.2+ using textbbox or textlength, older using textsize
                # simple centered logic
                d.text((70, 15), text, fill=color, font=font)
            except:
                 d.text((70, 15), text, fill=color, font=font)
            img.paste(line, (x, y), line)
        else:
            # fallback
            d = ImageDraw.Draw(img)
            d.text((x, y), text, fill=color, font=font)

    def _draw_wide_line(self, img, key, value, x, y, font, color):
        path = IMG_PATH / "line4.png"
        text = f"{key}:{value}"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((900, 100))
            d = ImageDraw.Draw(line)
            d.text((100, 30), text, fill=color, font=font)
            img.paste(line, (x, y), line)
        else:
            d = ImageDraw.Draw(img)
            d.text((x, y), text, fill=color, font=font)

    def _draw_section_header(self, img, text, y, font, color):
        path = IMG_PATH / "line2.png"
        if path.exists():
            line = Image.open(path).convert("RGBA").resize((900, 100))
            d = ImageDraw.Draw(line)
            # Centered text approx
            w = d.textlength(text, font=font)
            d.text(((900-w)/2, 30), text, fill=color, font=font)
            img.paste(line, (100, y), line)
        else:
            d = ImageDraw.Draw(img)
            d.text((100, y), text, fill=color, font=font)
