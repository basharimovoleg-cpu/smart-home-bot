"""
Telegram-бот на aiogram 3.x: управление светом, уход за Элис, погода.
"""
import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    WebAppInfo,
)

from config import settings
from database import (
    add_user,
    complete_task_with_history,
    delete_task,
    get_alice_care,
    get_all_tasks,
    update_alice_care,
    update_task,
)
from device_manager import DeviceManager, TuyaError
from tuya_client import TuyaConfig

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════

ALICE_BIRTHDAY = datetime(2021, 4, 20, tzinfo=timezone.utc)
ALICE_BIRTH_DAY = 20
ALICE_BIRTH_MONTH = 4

PROCEDURE_DELTAS = {
    "прививка": 365 * 86400,
    "от клещей": 30 * 86400,
    "от глистов": 90 * 86400,
}

PROCEDURE_LABELS = {
    "прививка": "💉 Прививка",
    "от клещей": "🦟 От клещей",
    "от глистов": "💊 От глистов",
}

# ═══════════════════════════════════════════════════════════
# Клавиатуры
# ═══════════════════════════════════════════════════════════

PANEL_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💡 Управление светом")],
        [KeyboardButton(text="🐾 Элис")],
    ],
    resize_keyboard=True,
)


def build_main_keyboard(manager: DeviceManager) -> InlineKeyboardMarkup:
    """Главное меню: три кнопки управления светом."""
    e1 = "💡" if manager.state.obodki else "💡"
    e2 = "💡" if manager.state.main_light else "💡"
    all_on = manager.state.all_on()
    label_all = "ВКЛ" if all_on else "ВЫКЛ"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{e1} Ободки", callback_data="obodki"),
            InlineKeyboardButton(text=f"{e2} Основной свет", callback_data="main_light"),
        ],
        [
            InlineKeyboardButton(text=f"💡 Всё – {label_all}", callback_data="all"),
        ],
    ])


def _calc_alice_age() -> tuple[int, str]:
    now = datetime.now(timezone.utc)
    years = now.year - ALICE_BIRTHDAY.year
    if (now.month, now.day) < (ALICE_BIRTH_MONTH, ALICE_BIRTH_DAY):
        years -= 1
    if 11 <= years % 100 <= 14:
        word = "лет"
    elif years % 10 == 1:
        word = "год"
    elif 2 <= years % 10 <= 4:
        word = "года"
    else:
        word = "лет"
    return years, word


def _format_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")


def build_alice_text(care: dict[str, int]) -> str:
    years, word = _calc_alice_age()
    now_ts = int(time.time())
    lines = [f"🐾 *Элис* — {years} {word}", ""]
    for proc in ("прививка", "от клещей", "от глистов"):
        next_ts = care.get(proc, 0)
        label = PROCEDURE_LABELS[proc]
        if next_ts > now_ts:
            lines.append(f"• {label}: {_format_date(next_ts)}")
        else:
            lines.append(f"• {label}: 🔴 НАДО СДЕЛАТЬ!")
    return "\n".join(lines)


def build_alice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💉 Сделали прививку", callback_data="alice_прививка")],
        [InlineKeyboardButton(text="🦟 Дали от клещей", callback_data="alice_от клещей")],
        [InlineKeyboardButton(text="💊 Дали от глистов", callback_data="alice_от глистов")],
    ])


# ═══════════════════════════════════════════════════════════
# Вспомогательные функции
# ═══════════════════════════════════════════════════════════

def _get_manager(bot: Bot) -> DeviceManager | None:
    """Достать DeviceManager из атрибутов бота."""
    return getattr(bot, "device_manager", None)


async def _show_alice(message: Message) -> None:
    care = await get_alice_care()
    text = build_alice_text(care)
    await message.answer(text, reply_markup=build_alice_keyboard(), parse_mode="Markdown")


async def _refresh_alice_callback(callback: CallbackQuery) -> None:
    care = await get_alice_care()
    text = build_alice_text(care)
    await callback.message.edit_text(text, reply_markup=build_alice_keyboard(), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
# Команды
# ═══════════════════════════════════════════════════════════

async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is not None:
        await add_user(user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📱 Открыть Умный Дом",
            web_app=WebAppInfo(url=settings.webapp_url),
        )]
    ])
    # Сначала убираем старую Reply-клавиатуру
    await message.answer(
        "⌨ Старая клавиатура убрана.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "🏠 *Умный дом*\n\n"
        "Нажмите на кнопку ниже, чтобы открыть панель управления:",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def cmd_help(message: Message) -> None:
    await message.answer(
        "🏠 *Умный дом — команды*\n\n"
        "/start  — открыть панель управления\n"
        "/help   — эта справка\n"
        "/status — текущее состояние выключателя\n\n"
        "Все функции доступны через кнопку «📱 Открыть Умный Дом».",
        parse_mode="Markdown",
    )


async def cmd_status(message: Message, bot: Bot) -> None:
    manager = _get_manager(bot)
    if manager is None:
        await message.answer("❌ Устройство не настроено (нет Tuya-ключей).")
        return

    try:
        manager.refresh()
    except TuyaError:
        pass

    e1 = "💡 ВКЛ" if manager.state.obodki else "💡 ВЫКЛ"
    e2 = "💡 ВКЛ" if manager.state.main_light else "💡 ВЫКЛ"

    await message.answer(
        "🏠 *Состояние выключателя:*\n\n"
        f"• Ободки: {e1}\n"
        f"• Основной свет: {e2}",
        parse_mode="Markdown",
    )


# ═══════════════════════════════════════════════════════════
# Текстовые кнопки (ReplyKeyboard)
# ═══════════════════════════════════════════════════════════

async def btn_light(message: Message, bot: Bot) -> None:
    manager = _get_manager(bot)
    if manager is None:
        await message.answer("❌ Управление светом не настроено (нет Tuya-ключей в .env).")
        return
    await message.answer(
        "🏠 *Умный дом* — управление светом\n\nВыберите действие:",
        reply_markup=build_main_keyboard(manager),
        parse_mode="Markdown",
    )


async def btn_alice(message: Message) -> None:
    await _show_alice(message)


# ═══════════════════════════════════════════════════════════
# Inline-кнопки (Callback)
# ═══════════════════════════════════════════════════════════

async def cb_obodki(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    manager = _get_manager(bot)
    if manager is None:
        await callback.message.edit_text("❌ Устройство не настроено.")
        return
    try:
        manager.toggle_obodki()
    except TuyaError as e:
        await callback.message.edit_text(f"❌ Ошибка Tuya: {e}")
        return
    await callback.message.edit_text(
        "🏠 *Умный дом* — управление светом\n\nВыберите действие:",
        reply_markup=build_main_keyboard(manager),
        parse_mode="Markdown",
    )


async def cb_main_light(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    manager = _get_manager(bot)
    if manager is None:
        await callback.message.edit_text("❌ Устройство не настроено.")
        return
    try:
        manager.toggle_main_light()
    except TuyaError as e:
        await callback.message.edit_text(f"❌ Ошибка Tuya: {e}")
        return
    await callback.message.edit_text(
        "🏠 *Умный дом* — управление светом\n\nВыберите действие:",
        reply_markup=build_main_keyboard(manager),
        parse_mode="Markdown",
    )


async def cb_all(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    manager = _get_manager(bot)
    if manager is None:
        await callback.message.edit_text("❌ Устройство не настроено.")
        return
    try:
        manager.toggle_all()
    except TuyaError as e:
        await callback.message.edit_text(f"❌ Ошибка Tuya: {e}")
        return
    await callback.message.edit_text(
        "🏠 *Умный дом* — управление светом\n\nВыберите действие:",
        reply_markup=build_main_keyboard(manager),
        parse_mode="Markdown",
    )


async def cb_alice_procedure(callback: CallbackQuery) -> None:
    await callback.answer()
    data = callback.data
    proc = data.removeprefix("alice_")
    delta = PROCEDURE_DELTAS.get(proc)
    if delta is None:
        await callback.message.edit_text("❌ Неизвестная процедура.")
        return
    new_date = int(time.time()) + delta
    await update_alice_care(proc, new_date)
    await _refresh_alice_callback(callback)


# ═══════════════════════════════════════════════════════════
# Задачи (бота)
# ═══════════════════════════════════════════════════════════

# Состояние редактирования: {user_id: task_id}
_editing_tasks: dict[int, int] = {}


def _format_task_date(date_str: str) -> str:
    parts = date_str.split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str


def _task_buttons(t: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Выполнено", callback_data=f"task_done_{t['id']}"),
            InlineKeyboardButton(text="✏️", callback_data=f"task_edit_{t['id']}"),
            InlineKeyboardButton(text="✕", callback_data=f"task_del_{t['id']}"),
        ],
    ])


async def cmd_tasks(message: Message) -> None:
    """Показать список активных задач."""
    tasks = await get_all_tasks()
    if not tasks:
        await message.answer("✅ Нет активных задач")
        return

    # Шлём по одной задаче с кнопками (чтоб можно было тыкнуть inline)
    await message.answer(f"📋 *Активные задачи* ({len(tasks)})", parse_mode="Markdown")
    for t in tasks:
        date_str = _format_task_date(t["task_date"])
        await message.answer(
            f"📅 {date_str}\n{t['title']}",
            reply_markup=_task_buttons(t),
        )


async def cb_task_done(callback: CallbackQuery) -> None:
    await callback.answer()
    task_id = int(callback.data.removeprefix("task_done_"))
    user_name = callback.from_user.first_name or "Бот"
    try:
        await complete_task_with_history(task_id, user_name)
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ Выполнено"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.exception(f"Task done error: {e}")
        await callback.message.edit_text("❌ Не удалось выполнить задачу")


async def cb_task_del(callback: CallbackQuery) -> None:
    await callback.answer()
    task_id = int(callback.data.removeprefix("task_del_"))
    try:
        await delete_task(task_id)
        await callback.message.edit_text(
            f"{callback.message.text}\n\n🗑 Удалено"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.exception(f"Task done error: {e}")
        await callback.message.edit_text("❌ Не удалось выполнить задачу")


async def cb_task_edit(callback: CallbackQuery) -> None:
    await callback.answer()
    task_id = int(callback.data.removeprefix("task_edit_"))
    user_id = callback.from_user.id
    _editing_tasks[user_id] = task_id
    await callback.message.edit_text(
        f"{callback.message.text}\n\n"
        f"✏️ *Редактирование*\n"
        f"Отправь новый заголовок одной строкой\n"
        f"Или /cancel_edit чтобы отменить",
        parse_mode="Markdown",
    )


async def cmd_cancel_edit(message: Message) -> None:
    user_id = message.from_user.id
    task_id = _editing_tasks.pop(user_id, None)
    if task_id:
        await message.answer("❌ Редактирование отменено")
    else:
        await message.answer("Нет активного редактирования")


async def handle_edit_text(message: Message) -> None:
    user_id = message.from_user.id
    task_id = _editing_tasks.get(user_id)
    if task_id is None:
        return
    new_title = message.text.strip()
    if not new_title:
        await message.answer("Название не может быть пустым. Попробуй ещё раз или /cancel_edit")
        return
    try:
        await update_task(task_id, title=new_title)
        _editing_tasks.pop(user_id, None)
        await message.answer(f"✅ Заголовок обновлён: _{new_title}_", parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Edit task error: {e}")
        await message.answer("❌ Не удалось обновить задачу")


# ═══════════════════════════════════════════════════════════
# Сборка бота
# ═══════════════════════════════════════════════════════════

router = Router()

# ── Access Control Middleware ──────────────────────────────────

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        allowed = settings.allowed_user_ids
        if not allowed:
            return await handler(event, data)

        user_id = None
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, "message") and event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif hasattr(event, "callback_query") and event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        if user_id is None or user_id not in allowed:
            return

        return await handler(event, data)


router.message.outer_middleware(AccessControlMiddleware())
router.callback_query.outer_middleware(AccessControlMiddleware())

# Команды
router.message.register(cmd_start, CommandStart())
router.message.register(cmd_help, Command("help"))
router.message.register(cmd_status, Command("status"))
router.message.register(cmd_tasks, Command("tasks"))
router.message.register(cmd_cancel_edit, Command("cancel_edit"))
# Текст в режиме редактирования задачи (должен быть после команд)
router.message.register(handle_edit_text, F.text & ~F.text.startswith("/"))

# Текстовые кнопки
router.message.register(btn_light, F.text == "💡 Управление светом")
router.message.register(btn_alice, F.text == "🐾 Элис")

# Inline-кнопки
router.callback_query.register(cb_obodki, F.data == "obodki")
router.callback_query.register(cb_main_light, F.data == "main_light")
router.callback_query.register(cb_all, F.data == "all")
router.callback_query.register(cb_alice_procedure, F.data.startswith("alice_"))
router.callback_query.register(cb_task_done, F.data.startswith("task_done_"))
router.callback_query.register(cb_task_edit, F.data.startswith("task_edit_"))
router.callback_query.register(cb_task_del, F.data.startswith("task_del_"))


def create_bot() -> Bot:
    """Создать и настроить бота, включая DeviceManager."""
    token = settings.bot_token
    if not token:
        raise RuntimeError("BOT_TOKEN not set in .env!")

    bot = Bot(token=token)

    # Подключаем DeviceManager если есть Tuya-ключи
    if all([settings.tuya_access_id, settings.tuya_secret, settings.tuya_device_id]):
        config = TuyaConfig(
            access_id=settings.tuya_access_id,
            secret=settings.tuya_secret,
            device_id=settings.tuya_device_id,
            base_url=settings.tuya_region_url,
        )
        bot.device_manager = DeviceManager(config)
    else:
        bot.device_manager = None

    return bot


dp = Dispatcher()
dp.include_router(router)

# Для совместимости с main.py
bot = None  # будет создан в main.py
