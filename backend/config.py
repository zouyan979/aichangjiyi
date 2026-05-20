import os
import sys

# Resolve base directory:
# - PyInstaller bundled: exe's directory (persistent data)
# - Normal: backend's directory
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(__file__)

DB_PATH = os.path.join(_BASE_DIR, "data", "memoria.db")

# Token budget defaults
DEFAULT_TOKEN_BUDGET = 3000
MAX_TOKEN_BUDGET = 8000

# Memory defaults
DEFAULT_CTX_WINDOW = 20        # recent messages to keep
DEFAULT_SUMMARIZE_AT = 10      # auto-summarize after N unsummarized messages
DEFAULT_SUMMARY_BATCH = 8      # messages per summary batch
META_SUMMARY_THRESHOLD = 30    # merge old summaries when count exceeds this

# Proactive defaults
DEFAULT_PROACTIVE_INTERVAL = 30  # minutes
PROACTIVE_CHECK_INTERVAL = 300   # seconds (5 min scheduler tick)
PROACTIVE_COOLDOWN = 3600        # seconds between proactive messages

# Summary retention
MAX_SUMMARIES = 100
MAX_GROWTH_LOG = 50

# Profile limits
MAX_PROFILE_ITEMS_PER_CAT = 50
MAX_CORE_FACTS = 100

# Supported categories for user_profiles
PROFILE_CATEGORIES = ["name", "interest", "trait", "fact", "preference", "goal"]

# Sentiment keywords (simple Chinese sentiment detection)
NEGATIVE_KEYWORDS = ["难过", "伤心", "烦", "焦虑", "压力", "累", "不开心", "郁闷", "烦躁",
                     "失望", "害怕", "担心", "孤独", "无聊", "痛苦", "沮丧", "崩溃", "糟糕"]
POSITIVE_KEYWORDS = ["开心", "高兴", "快乐", "兴奋", "期待", "感谢", "太好了", "棒", "不错",
                     "幸福", "满足", "放松", "舒服", "喜欢", "爱"]

# Event extraction keywords
EVENT_KEYWORDS = {
    "面试": 24,      # follow up after 24 hours
    "考试": 24,
    "约会": 12,
    "出差": 48,
    "旅行": 72,
    "手术": 48,
    "汇报": 24,
    "述职": 24,
    "体检": 48,
    "搬家": 48,
}

TIME_KEYWORDS = ["明天", "后天", "下周", "下个月", "下周", "今晚", "明早"]
