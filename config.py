"""تنظیمات ربات فروشگاه.

همه مقادیر حساس از متغیرهای محیطی (.env) خوانده می‌شوند؛
هیچ مقدار واقعی را داخل کد ننویسید.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # خواندن فایل .env (اگر وجود داشته باشد)


def _get_admin_id() -> int:
    raw = os.getenv("ADMIN_ID", "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0  # یعنی هنوز تنظیم نشده (TODO)


# TODO: توکن بات را از BotFather بگیرید و در .env بگذارید
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "TODO:PUT_YOUR_BOT_TOKEN_HERE")

# TODO: آیدی عددی تلگرام ادمین را در .env بگذارید (مثلاً از ربات userinfobot@ بگیرید)
ADMIN_ID: int = _get_admin_id()

# TODO: شماره کارت برای واریز کارت‌به‌کارت را در .env بگذارید
CARD_NUMBER: str = os.getenv("CARD_NUMBER", "TODO:XXXX-XXXX-XXXX-XXXX")

# TODO: نام صاحب کارت را در .env بگذارید
CARD_HOLDER_NAME: str = os.getenv("CARD_HOLDER_NAME", "نام صاحب کارت")

# ---------------------------------------------------------------------------
# محصولات فروشگاه — محصول جدید را همین‌جا اضافه کنید و یک فایل موجودی در
# پوشه stock/ بسازید (هر خط = یک اکانت).
# ---------------------------------------------------------------------------
PRODUCTS: list[dict] = [
    {
        "key": "gemini",            # کلید یکتا (انگلیسی، بدون فاصله)
        "name": "اکانت جمینای",     # نام نمایشی فارسی
        "price": 390000,           # مقدار نمونه به تومان — بعداً اصلاح شود
        "stock_file": "stock/gemini.txt",
    },
    # مثال محصول بعدی:
    # {
    #     "key": "chatgpt",
    #     "name": "اکانت ChatGPT",
    #     "price": 0,               # TODO: قیمت به تومان
    #     "stock_file": "stock/chatgpt.txt",
    # },
]
