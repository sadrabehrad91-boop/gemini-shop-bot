"""
ربات فروشگاه اکانت هوش مصنوعی (فارسی)

- حالت اجرا: polling (نیازی به وب‌هوک و سرور عمومی نیست)
- پرداخت: کارت‌به‌کارت با تأیید دستی ادمین
- تحویل: یک خط از فایل موجودی محصول، بعد از تأیید ادمین

اجرا:
    python -m venv .venv
    source .venv/bin/activate   (در ویندوز: .venv\\Scripts\\activate)
    pip install -r requirements.txt
    cp .env.example .env        (و مقادیر TODO را پر کنید)
    python bot.py
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dp = Dispatcher(storage=MemoryStorage())


# ---------------------------------------------------------------------------
# Callback data (حداکثر ۶۴ بایت برای تلگرام)
# ---------------------------------------------------------------------------

class BuyCallback(CallbackData, prefix="buy"):
    product_key: str


class ReceiptCallback(CallbackData, prefix="receipt"):
    product_key: str


class AdminActionCallback(CallbackData, prefix="order"):
    action: str  # "approve" | "reject"
    order_id: str


# ---------------------------------------------------------------------------
# وضعیت‌های گفتگو (FSM)
# ---------------------------------------------------------------------------

class OrderStates(StatesGroup):
    waiting_for_receipt = State()  # منتظر عکس رسید از خریدار


# سفارش‌های در انتظار بررسی ادمین — در حافظه موقت نگه داشته می‌شود.
# نکته: با ری‌استارت بات پاک می‌شود؛ برای فروشگاه واقعی از دیتابیس استفاده کنید.
orders: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    """آیا این کاربر ادمین است؟"""
    return config.ADMIN_ID != 0 and user_id == config.ADMIN_ID


def get_product(key: str) -> dict | None:
    """پیدا کردن محصول با کلید یکتا."""
    for p in config.PRODUCTS:
        if p["key"] == key:
            return p
    return None


def format_price(price: int) -> str:
    """نمایش قیمت با جداکننده هزارگان، مثلاً: ۱٬۲۵۰٬۰۰۰ تومان."""
    return f"{price:,} تومان"


def count_stock(product: dict) -> int:
    """تعداد خطوط استفاده‌نشده فایل موجودی (خط خالی و کامنت حساب نمی‌شود)."""
    stock_path = product["stock_file"]
    if not os.path.exists(stock_path):
        return 0
    n = 0
    with open(stock_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def pop_stock_line(product: dict) -> str | None:
    """اولین خط استفاده‌نشده را از فایل موجودی برمی‌دارد و به فایل used منتقل می‌کند.

    اگر موجودی تمام شده باشد None برمی‌گرداند.
    """
    stock_path = product["stock_file"]
    if not os.path.exists(stock_path):
        return None
    with open(stock_path, encoding="utf-8") as f:
        lines = f.readlines()

    sold = None
    kept: list[str] = []
    for line in lines:
        s = line.strip()
        if sold is None and s and not s.startswith("#"):
            sold = s  # این خط فروخته شد
            continue
        kept.append(line)

    if sold is None:
        return None

    with open(stock_path, "w", encoding="utf-8") as f:
        f.writelines(kept)

    used_path = os.path.join(
        os.path.dirname(stock_path), f"used_{os.path.basename(stock_path)}"
    )
    with open(used_path, "a", encoding="utf-8") as f:
        f.write(f"{sold}\n")

    return sold


def catalog_keyboard() -> InlineKeyboardMarkup:
    """دکمه‌های کاتالوگ محصولات."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"🛒 {p['name']} — {format_price(p['price'])}",
                callback_data=BuyCallback(product_key=p["key"]).pack(),
            )
        ]
        for p in config.PRODUCTS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# دستور /start — خوش‌آمد + کاتالوگ
# ---------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 سلام! به <b>فروشگاه اکانت هوش مصنوعی</b> خوش اومدی.\n\n"
        "اینجا می‌تونی اکانت‌های هوش مصنوعی رو با چند کلیک بخری.\n"
        "یکی از محصولات زیر رو انتخاب کن:",
        reply_markup=catalog_keyboard(),
    )


@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 یکی از محصولات زیر رو انتخاب کن:",
        reply_markup=catalog_keyboard(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# انتخاب محصول → کارت سفارش (شماره کارت + درخواست رسید)
# ---------------------------------------------------------------------------

@dp.callback_query(BuyCallback.filter())
async def cb_buy(
    callback: types.CallbackQuery,
    callback_data: BuyCallback,
    state: FSMContext,
):
    product = get_product(callback_data.product_key)
    if product is None:
        await callback.answer("محصول یافت نشد.", show_alert=True)
        return

    text = (
        f"🧾 <b>سفارش: {product['name']}</b>\n\n"
        f"💰 قیمت: <b>{format_price(product['price'])}</b>\n\n"
        f"💳 لطفاً مبلغ رو به شماره کارت زیر واریز کن:\n"
        f"<code>{config.CARD_NUMBER}</code>\n"
        f"👤 به نام: {config.CARD_HOLDER_NAME}\n\n"
        "📸 بعد از واریز، روی دکمه «ارسال رسید» بزن و عکس رسید رو همینجا بفرست."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 ارسال رسید",
                    callback_data=ReceiptCallback(
                        product_key=product["key"]
                    ).pack(),
                )
            ],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_menu")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(ReceiptCallback.filter())
async def cb_receipt(
    callback: types.CallbackQuery,
    callback_data: ReceiptCallback,
    state: FSMContext,
):
    product = get_product(callback_data.product_key)
    if product is None:
        await callback.answer("محصول یافت نشد.", show_alert=True)
        return
    await state.set_state(OrderStates.waiting_for_receipt)
    await state.update_data(product_key=product["key"])
    await callback.message.answer(
        f"📸 لطفاً عکس رسید واریز <b>{format_price(product['price'])}</b> "
        f"برای «{product['name']}» رو همینجا بفرست.\n\n"
        "برای لغو سفارش: /cancel"
    )
    await callback.answer()


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ سفارش لغو شد. برای شروع دوباره /start رو بزن.")


# ---------------------------------------------------------------------------
# دریافت عکس رسید → ارسال برای ادمین با دکمه‌های تأیید/رد
# ---------------------------------------------------------------------------

@dp.message(OrderStates.waiting_for_receipt, F.photo)
async def on_receipt_photo(
    message: types.Message, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    product = get_product(data.get("product_key", ""))
    if product is None:
        await message.answer("مشکلی پیش اومد؛ لطفاً با /start از اول شروع کن.")
        await state.clear()
        return

    order_id = uuid.uuid4().hex[:12]
    orders[order_id] = {
        "buyer_id": message.from_user.id,
        "buyer_name": message.from_user.full_name,
        "buyer_username": message.from_user.username,
        "product_key": product["key"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    file_id = message.photo[-1].file_id  # باکیفیت‌ترین نسخه عکس
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    caption = (
        "🧾 <b>رسید جدید</b>\n\n"
        f"📦 محصول: {product['name']}\n"
        f"💰 مبلغ: {format_price(product['price'])}\n"
        f"👤 خریدار: {message.from_user.full_name} ({username})\n"
        f"🆔 آیدی عددی: <code>{message.from_user.id}</code>\n"
        f"🔖 کد سفارش: <code>{order_id}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=AdminActionCallback(
                        action="approve", order_id=order_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ رد",
                    callback_data=AdminActionCallback(
                        action="reject", order_id=order_id
                    ).pack(),
                ),
            ]
        ]
    )
    await bot.send_photo(config.ADMIN_ID, file_id, caption=caption, reply_markup=keyboard)
    await message.answer(
        "✅ رسیدت برای ادمین ارسال شد.\n"
        "بعد از بررسی، نتیجه همینجا بهت اطلاع داده می‌شه. 🙏"
    )
    await state.clear()


@dp.message(F.photo)
async def photo_without_order(message: types.Message):
    """عکس بدون سفارش فعال — راهنمایی کاربر."""
    await message.answer("برای ثبت سفارش، اول از /start یک محصول انتخاب کن. 🙂")


# ---------------------------------------------------------------------------
# دکمه‌های ادمین: تأیید → تحویل اکانت | رد → اطلاع به خریدار
# ---------------------------------------------------------------------------

@dp.callback_query(AdminActionCallback.filter())
async def cb_admin_action(
    callback: types.CallbackQuery,
    callback_data: AdminActionCallback,
    bot: Bot,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ فقط ادمین.", show_alert=True)
        return

    order = orders.pop(callback_data.order_id, None)
    if order is None:
        await callback.answer(
            "این سفارش قبلاً بررسی شده یا منقضی شده.", show_alert=True
        )
        return

    product = get_product(order["product_key"])
    product_name = product["name"] if product else "نامشخص"
    buyer_id = order["buyer_id"]

    if callback_data.action == "approve":
        if product is None:
            await callback.answer("محصول یافت نشد.", show_alert=True)
            return
        account = pop_stock_line(product)
        if account is None:
            # موجودی تمام شده — سفارش را برمی‌گردانیم تا گم نشود
            orders[callback_data.order_id] = order
            await callback.answer("⚠️ موجودی این محصول تمام شده!", show_alert=True)
            await bot.send_message(
                callback.from_user.id,
                f"⚠️ موجودی «{product_name}» تمام شده!\n"
                f"فایل {product['stock_file']} را شارژ کن.",
            )
            return
        try:
            await bot.send_message(
                buyer_id,
                f"🎉 پرداختت تأیید شد!\n\n"
                f"📦 محصول: {product_name}\n"
                f"🔑 اکانت شما:\n<code>{account}</code>\n\n"
                "ممنون از خریدت! 🌟",
            )
        except Exception as exc:  # مثلاً اگر کاربر بات را بلاک کرده باشد
            logger.warning("ارسال به خریدار ناموفق بود: %s", exc)
            await callback.answer(
                "تأیید شد ولی ارسال به خریدار ناموفق بود (احتمالاً بات را بلاک کرده).",
                show_alert=True,
            )
            return
        await callback.answer("تأیید و ارسال شد ✅")
        try:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "")
                + "\n\n✅ تأیید شد و اکانت برای خریدار ارسال گردید.",
                reply_markup=None,
            )
        except Exception:
            pass

    else:  # reject
        try:
            await bot.send_message(
                buyer_id,
                f"❌ متأسفانه رسید شما برای «{product_name}» تأیید نشد.\n"
                "لطفاً رسید معتبر ارسال کن یا با پشتیبانی در تماس باش.",
            )
        except Exception as exc:
            logger.warning("ارسال به خریدار ناموفق بود: %s", exc)
        await callback.answer("رد شد ❌")
        try:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "") + "\n\n❌ رد شد.",
                reply_markup=None,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# دستور /stock — فقط ادمین: نمایش موجودی هر محصول
# ---------------------------------------------------------------------------

@dp.message(Command("stock"))
async def cmd_stock(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ این دستور فقط برای ادمین است.")
        return
    lines = [
        f"📦 {p['name']}: <b>{count_stock(p)}</b> عدد باقی مانده"
        for p in config.PRODUCTS
    ]
    await message.answer("📊 <b>موجودی انبار:</b>\n\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# نقطه شروع
# ---------------------------------------------------------------------------

async def main() -> None:
    missing = []
    if not config.BOT_TOKEN or config.BOT_TOKEN.startswith("TODO"):
        missing.append("BOT_TOKEN")
    if config.ADMIN_ID == 0:
        missing.append("ADMIN_ID")
    if config.CARD_NUMBER.startswith("TODO"):
        missing.append("CARD_NUMBER")
    if missing:
        logger.error(
            "مقادیر TODO زیر در فایل .env تکمیل نشده است: %s",
            ", ".join(missing),
        )
        return

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("ربات شروع به کار کرد... (حالت polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
