"""桌面端配置 — 不含任何 API 密钥和 QQ 相关数据"""
import os

OWNER_QQ = 0  # 桌面端无主人QQ概念
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
