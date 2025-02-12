import asyncio
import os
import re
from datetime import datetime
import uuid

from pyairtable import Api, Table
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BotCommand, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv
from gemini_api import GeminiAPI
import logging

load_dotenv()

# Переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AIRTABLE_PERSONAL_ACCESS_TOKEN = os.getenv("AIRTABLE_PERSONAL_ACCESS_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = "Диалоги"  # Имя таблицы

# Проверка наличия переменных окружения
if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, AIRTABLE_PERSONAL_ACCESS_TOKEN, AIRTABLE_BASE_ID]):
    raise ValueError("Необходимые переменные окружения не установлены.")

# Инициализация API
gemini_api = GeminiAPI(GEMINI_API_KEY)
airtable = Api(AIRTABLE_PERSONAL_ACCESS_TOKEN)
table: Table = airtable.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Экранирование MarkdownV2
def escape_markdown_v2(text):
    escape_chars = r"_*[]()~>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Загрузка истории диалога
async def load_conversation_history(user_id, appeal_id):
    try:
        formula = f"AND({{user_id}} = '{user_id}', {{appeal_id}} = '{appeal_id}')"
        records = table.all(formula=formula, sort=["timestamp"])
        history = ""
        for record in records:
            fields = record.get("fields", {})
            role = fields.get("role", "неизвестно")
            content = fields.get("content", "")
            history += f"{role.capitalize()}: {content}\n"
        return history
    except Exception as e:
        logging.error(f"Ошибка при загрузке истории диалога: {e}")
        return ""

# Сохранение сообщения
async def save_message(user_id, message: Message, role, content, appeal_id, tokens=None):
    try:
        table.create({
            "message_id": message.message_id,
            "user_id": user_id,
            "appeal_id": appeal_id,
            "role": role,
            "content": content,
            "timestamp": message.date.isoformat(),
            "tokens": tokens
        })
    except Exception as e:
        logging.error(f"Ошибка при сохранении сообщения: {e}")


# FSM состояния
class ConversationStates(StatesGroup):
    WAITING_FOR_INPUT = State()
    HANDLING_APPEAL = State()
    WAITING_FOR_TITLE = State()

# Инициализация бота
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Установка команд бота
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="Начать диалог"),
        BotCommand(command="/help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)

# Обработчик команды /help
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("Я могу отвечать на ваши вопросы. Используйте /start для начала диалога.")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    # Ищем открытые обращения в таблице "Диалоги"
    open_appeals = table.all(formula=f"AND({{user_id}}='{user_id}', {{appeal_status}}='открыто')")

    if open_appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for record in open_appeals:
            appeal_id = record["fields"].get("appeal_id")
            appeal_title = record["fields"].get("appeal_title", f"Обращение {appeal_id}")
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=appeal_title, callback_data=f"open_appeal:{appeal_id}")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="Новое обращение", callback_data="new_appeal")])
        await message.answer("У вас есть не закрытые обращения. Выберите одно из них, чтобы продолжить или создайте новое:", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Новое обращение", callback_data="new_appeal")]
        ])
        await message.answer("У вас нет открытых обращений. Создайте новое:", reply_markup=keyboard)

    await state.set_state(ConversationStates.WAITING_FOR_INPUT)


@router.callback_query(F.data.startswith("open_appeal:"))
async def open_appeal(callback_query: CallbackQuery, state: FSMContext):
    appeal_id = callback_query.data.split(":")[1]
    await state.update_data(appeal_id=appeal_id)
    await state.set_state(ConversationStates.HANDLING_APPEAL)
    await bot.send_message(callback_query.from_user.id, f"Обращение {appeal_id} открыто. Что вас интересует?")


@router.callback_query(F.data == "new_appeal")
async def new_appeal(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    await state.set_state(ConversationStates.WAITING_FOR_TITLE)
    await bot.send_message(user_id, "Введите название обращения (не более 50 символов):")


@router.message(F.text, ConversationStates.WAITING_FOR_TITLE)
async def get_appeal_title(message: Message, state: FSMContext):
    user_id = message.from_user.id
    title = message.text

    if len(title) > 50:
        await message.answer("Название слишком длинное. Пожалуйста, введите название не более 50 символов.")
        return

    try:
        appeal_id = str(uuid.uuid4())

        # Создание записи в Airtable
        table.create({
            "user_id": user_id,
            "appeal_id": appeal_id,
            "appeal_title": title,
            "appeal_status": "открыто",
            "timestamp": datetime.now().isoformat()
        })

        await state.update_data(appeal_id=appeal_id)
        await state.set_state(ConversationStates.HANDLING_APPEAL)
        await message.answer(f"Обращение '{title}' создано. Опишите вашу проблему.")

    except Exception as e:
        logging.error(f"Ошибка при создании обращения: {e}", exc_info=True)
        await message.answer("Ошибка при создании обращения. Пожалуйста, попробуйте позже.")


@router.message(F.text, ConversationStates.HANDLING_APPEAL)
async def handle_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    appeal_id = user_data.get("appeal_id")
    user_input = message.text

    if not appeal_id:
        await message.answer("Ошибка: не найден ID обращения.")
        return

    conversation_history = await load_conversation_history(user_id, appeal_id)
    conversation_history += f"Пользователь: {user_input}\n"

    response = await gemini_api.get_response(f"{conversation_history}Бот:")
    if not response:
        response = "Извините, я не могу ответить на ваш запрос."

    parts = response.split("**")
    formatted_response = ""
    for i, part in enumerate(parts):
        if i % 2 == 1:
            formatted_response += f"*{escape_markdown_v2(part)}*"
        else:
            formatted_response += escape_markdown_v2(part)

    await save_message(user_id, message, "user", user_input, appeal_id)
    await save_message(user_id, message, "bot", response, appeal_id)

    MAX_MESSAGE_LENGTH = 4096
    for x in range(0, len(formatted_response), MAX_MESSAGE_LENGTH):
        await message.answer(
            formatted_response[x:x + MAX_MESSAGE_LENGTH],
            parse_mode="MarkdownV2"
        )

    if any(keyword in response.lower() for keyword in ["проблема решена", "надеюсь, это помогло", "вопрос закрыт"]):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Закрыть обращение", callback_data=f"close_appeal:{appeal_id}")]
        ])
        await message.answer("Закрыть обращение?", reply_markup=keyboard)


@router.callback_query(F.data.startswith("close_appeal:"))
async def close_appeal(callback_query: CallbackQuery, state: FSMContext):
    appeal_id = callback_query.data.split(":")[1]
    try:
        record = table.first(formula=f"{{appeal_id}}='{appeal_id}'")
        if record:
            table.update(record["id"], {"appeal_status": "закрыто"})
            await bot.send_message(callback_query.from_user.id, "Обращение закрыто.")
            await state.clear()
        else:
            await bot.send_message(callback_query.from_user.id, "Ошибка: обращение не найдено.")
    except Exception as e:
        logging.error(f"Ошибка при закрытии обращения: {e}", exc_info=True)
        await bot.send_message(callback_query.from_user.id, "Ошибка при закрытии обращения.")


async def main():
    print("Бот запущен...")
    dp.include_router(router)
    await set_bot_commands(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())