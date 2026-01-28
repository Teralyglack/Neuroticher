import asyncio
import html
import logging
import os
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

from database import UserDatabase
from learning_engine import LearningEngine
from openai_api import OpenAIAPI

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

db = UserDatabase()
ai = OpenAIAPI()
learning = LearningEngine()


class UserStates(StatesGroup):
    asking_question = State()
    checking_text = State()
    waiting_exercise_answer = State()


def esc(text: str) -> str:
    return html.escape(text or "")


def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Уроки", callback_data="lessons"),
         InlineKeyboardButton(text="💪 Упражнение", callback_data="exercises")],
        [InlineKeyboardButton(text="❓ Вопрос AI", callback_data="ask_question"),
         InlineKeyboardButton(text="📝 Проверить текст", callback_data="check_text")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="🧹 Сброс AI", callback_data="reset_ai")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])


def kb_lessons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Present Simple", callback_data="lesson_present_simple")],
        [InlineKeyboardButton(text="📖 Past Simple", callback_data="lesson_past_simple")],
        [InlineKeyboardButton(text="📖 Артикли a/an/the", callback_data="lesson_articles")],
        [InlineKeyboardButton(text="📖 Модальные глаголы", callback_data="lesson_modals")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])


def kb_exercises() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Грамматика", callback_data="exercise_grammar")],
        [InlineKeyboardButton(text="🧠 Лексика", callback_data="exercise_vocab")],
        [InlineKeyboardButton(text="🔄 Перевод RU→EN", callback_data="exercise_translate")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])


async def safe_edit(message: Message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> bool:
    try:
        await message.edit_text(text=text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e) or "message to edit not found" in str(e):
            return True
        logging.error(f"TelegramBadRequest: {e}")
        return False
    except Exception as e:
        logging.error(f"Edit error: {e}")
        return False


async def safe_answer(callback: CallbackQuery, text: Optional[str] = None, show_alert: bool = False) -> bool:
    try:
        await callback.answer(text=text, show_alert=show_alert)
        return True
    except Exception as e:
        logging.error(f"Callback answer error: {e}")
        return False


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    db.get_or_create_user(user_id, username=username)
    stats = db.get_user_stats(user_id)

    if stats.get("total_exercises", 0) == 0:
        text = (
            "🎓 <b>Добро пожаловать в NeuroEnglish Tutor!</b>\n\n"
            f"Привет, <b>{esc(message.from_user.first_name)}</b>!\n"
            "Я помогу учить английский: уроки, упражнения, ответы на вопросы, проверка текста.\n\n"
            "Выбери действие ниже 👇"
        )
    else:
        accuracy = stats.get("accuracy", 0.0) * 100
        streak = stats.get("streak_days", 0)
        mot = learning.motivation_message(streak, stats.get("accuracy", 0.0))
        text = (
            f"🎓 <b>С возвращением, {esc(message.from_user.first_name)}!</b>\n\n"
            "📊 <b>Статистика:</b>\n"
            f"• Упражнений: <b>{stats.get('total_exercises', 0)}</b>\n"
            f"• Точность: <b>{accuracy:.0f}%</b>\n"
            f"• Серия: <b>{streak}</b> дн.\n\n"
            f"{esc(mot)}\n\n"
            "<b>Что делаем сегодня?</b>"
        )

    await message.answer(text, reply_markup=kb_main())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎛️ <b>Главное меню</b>", reply_markup=kb_main())


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    cleared = ai.clear_conversation(message.from_user.id)
    await message.answer("🧹 Контекст AI очищен." if cleared else "🧹 Контекст AI уже был пуст.", reply_markup=kb_main())


@router.callback_query(F.data == "lessons")
async def show_lessons(callback: CallbackQuery):
    await safe_edit(callback.message, "📚 <b>Уроки</b>\n\nВыбери тему — объясню с примерами.", kb_lessons())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("lesson_"))
async def handle_lesson(callback: CallbackQuery):
    lesson_type = callback.data.replace("lesson_", "")
    await safe_answer(callback, "⏳ Готовлю урок...")

    topic_map = {
        "present_simple": "Present Simple",
        "past_simple": "Past Simple",
        "articles": "Articles (a/an/the)",
        "modals": "Modal verbs (can/should/must)",
    }
    topic = topic_map.get(lesson_type, "English grammar")

    prompt = (
        f"Сделай мини-урок по теме: {topic}.\n"
        "Структура:\n"
        "1) <b>Что это</b> (простыми словами)\n"
        "2) <b>Когда использовать</b> (2-4 правила)\n"
        "3) <b>Примеры</b> (минимум 5) + короткий перевод\n"
        "4) <b>Частые ошибки</b> (3-5)\n"
        "5) <b>3 мини-упражнения</b> без ответов\n"
        "Пиши компактно."
    )

    lesson = await ai.ask_question(callback.from_user.id, prompt)
    await safe_edit(callback.message, f"📚 <b>{esc(topic)}</b>\n\n{lesson}", kb_back())


@router.callback_query(F.data == "exercises")
async def show_exercises(callback: CallbackQuery):
    await safe_edit(callback.message, "💪 <b>Упражнения</b>\n\nВыбери тип — я проверю твой ответ.", kb_exercises())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("exercise_"))
async def handle_exercise(callback: CallbackQuery, state: FSMContext):
    exercise_type = callback.data.replace("exercise_", "")
    user_id = callback.from_user.id

    await safe_answer(callback, "⏳ Генерирую упражнение...")

    stats = db.get_user_stats(user_id)
    level = stats.get("level", "beginner")
    difficulty = learning.calculate_difficulty(stats)

    topics = learning.recommend_topics(level, stats.get("weak_topics", []))
    topic = topics[0] if topics else "General English"

    ex_type_map = {
        "grammar": "grammar",
        "vocab": "vocab",
        "translate": "translate",
    }

    ex = await ai.generate_exercise_structured(
        topic=topic,
        level=level,
        exercise_type=ex_type_map.get(exercise_type, exercise_type),
        weak_areas=stats.get("weak_topics", []),
        difficulty=difficulty,
    )

    await state.set_state(UserStates.waiting_exercise_answer)
    await state.update_data(
        exercise_type=exercise_type,
        topic=topic,
        difficulty=float(difficulty),
        title=str(ex.get("title", "")),
        instruction=str(ex.get("instruction", "")),
        question=str(ex.get("question", "")),
        correct_answer=str(ex.get("correct_answer", "")),
        started_at=time.time(),
    )

    tips = ex.get("tips") or []
    tips_text = ""
    if isinstance(tips, list) and tips:
        tips_text = "\n".join("• " + esc(str(t)) for t in tips[:4])

    text = (
            f"💪 <b>{esc(str(ex.get('title', 'Упражнение')))}</b>\n\n"
            f"<b>Инструкция:</b> {esc(str(ex.get('instruction', '')))}\n\n"
            f"<b>Задание:</b>\n{esc(str(ex.get('question', '')))}\n\n"
            + (f"💡 <b>Подсказки:</b>\n{tips_text}\n\n" if tips_text else "")
            + "<i>Отправь ответ одним сообщением. Я проверю ✅</i>"
    )

    await safe_edit(callback.message, text, kb_back())


@router.message(UserStates.waiting_exercise_answer)
async def process_exercise_answer(message: Message, state: FSMContext):
    data = await state.get_data()

    user_answer = (message.text or "").strip()
    if not user_answer:
        await message.answer("⚠️ Напиши ответ текстом одним сообщением 🙂")
        return

    correct_answer = str(data.get("correct_answer", "") or "")
    started_at = float(data.get("started_at", time.time()) or time.time())
    time_spent = int(max(0, time.time() - started_at))

    eval_res = learning.evaluate_answer(user_answer, correct_answer)
    is_correct = bool(eval_res.is_correct)

    stats_before = db.get_user_stats(message.from_user.id)
    predicted_level = learning.get_user_level(
        accuracy=float(stats_before.get("accuracy", 0.0) or 0.0),
        total_exercises=int(stats_before.get("total_exercises", 0) or 0) + 1,
    )

    db.record_exercise(
        telegram_id=message.from_user.id,
        exercise_type=str(data.get("exercise_type", "exercise")),
        topic=str(data.get("topic", "")),
        question=str(data.get("question", "")),
        user_answer=user_answer,
        correct_answer=correct_answer,
        is_correct=is_correct,
        difficulty=float(data.get("difficulty", 0.5) or 0.5),
        time_spent=time_spent,
        new_level=predicted_level,
    )

    stats = db.get_user_stats(message.from_user.id)
    accuracy = stats.get("accuracy", 0.0) * 100
    streak = stats.get("streak_days", 0)
    mot = learning.motivation_message(streak, stats.get("accuracy", 0.0))

    text = (
            ("✅ <b>Верно!</b>\n" if is_correct else "❌ <b>Нужно поправить</b>\n")
            + f"{esc(eval_res.feedback)}\n\n"
            + f"<b>Твой ответ:</b> {esc(user_answer)}\n"
            + f"<b>Правильный:</b> {esc(correct_answer)}\n\n"
            + f"⏱️ Время: <b>{time_spent}</b> сек.\n"
            + f"🎯 Точность: <b>{accuracy:.0f}%</b> | 🔥 Серия: <b>{streak}</b> дн.\n\n"
            + f"{esc(mot)}"
    )

    await message.answer(text, reply_markup=kb_main())
    await state.clear()


@router.callback_query(F.data == "ask_question")
async def ask_question_handler(callback: CallbackQuery, state: FSMContext):
    await safe_edit(
        callback.message,
        "❓ <b>Задай любой вопрос по английскому</b>\n\n"
        "<u>Примеры:</u>\n"
        "• В чём разница между Present Perfect и Past Simple?\n"
        "• Когда ставить артикль the?\n"
        "• Как не путать say/tell?\n\n"
        "<i>Напиши вопрос следующим сообщением.</i>",
        kb_back(),
    )
    await safe_answer(callback)
    await state.set_state(UserStates.asking_question)


@router.message(UserStates.asking_question)
async def process_question(message: Message, state: FSMContext):
    await bot.send_chat_action(message.chat.id, "typing")
    answer = await ai.ask_question(message.from_user.id, message.text or "")
    await message.answer(
        f"❓ <b>Вопрос:</b> {esc(message.text or '')}\n\n💡 <b>Ответ:</b>\n{answer}",
        reply_markup=kb_main(),
    )
    await state.clear()


@router.callback_query(F.data == "check_text")
async def check_text_handler(callback: CallbackQuery, state: FSMContext):
    await safe_edit(
        callback.message,
        "📝 <b>Проверка текста</b>\n\n"
        "Отправь текст на английском (2-10 предложений).\n"
        "<i>Я отмечу ошибки и предложу улучшенную версию.</i>",
        kb_back(),
    )
    await safe_answer(callback)
    await state.set_state(UserStates.checking_text)


@router.message(UserStates.checking_text)
async def process_text_check(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if len(txt) < 10:
        await message.answer("⚠️ Слишком коротко. Пришли минимум 2-3 предложения.")
        return
    if len(txt) > 2500:
        await message.answer("⚠️ Слишком длинно. Сократи до ~2500 символов.")
        return

    await bot.send_chat_action(message.chat.id, "typing")
    result = await ai.check_homework(txt)
    await message.answer(f"📝 <b>Готово!</b>\n\n{result}", reply_markup=kb_main())
    await state.clear()


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    stats = db.get_user_stats(callback.from_user.id)
    if not stats or stats.get("total_exercises", 0) == 0:
        text = "📊 <b>Статистика</b>\n\nПока нет данных — начни с упражнения 💪"
    else:
        total = stats["total_exercises"]
        correct = stats["correct_answers"]
        accuracy = stats["accuracy"] * 100
        weak = ", ".join(stats.get("weak_topics", [])) or "Нет"
        streak = stats.get("streak_days", 0)
        level = stats.get("level", "beginner")

        text = (
            "📊 <b>Твоя статистика</b>\n\n"
            f"🏷️ Уровень: <b>{esc(level)}</b>\n"
            f"📈 Упражнений: <b>{total}</b>\n"
            f"✅ Правильных: <b>{correct}</b>\n"
            f"🎯 Точность: <b>{accuracy:.0f}%</b>\n"
            f"🔥 Серия: <b>{streak}</b> дн.\n"
            f"⚠️ Слабые темы: <b>{esc(weak)}</b>\n"
        )

    await safe_edit(callback.message, text, kb_back())
    await safe_answer(callback)


@router.callback_query(F.data == "help")
async def help_handler(callback: CallbackQuery):
    text = (
        "ℹ️ <b>Помощь</b>\n\n"
        "<b>Как пользоваться:</b>\n"
        "• 📚 Уроки — объяснения тем + мини-упражнения\n"
        "• 💪 Упражнение — бот задаёт задачу и проверяет ответ\n"
        "• ❓ Вопрос AI — спроси что угодно по английскому\n"
        "• 📝 Проверить текст — разбор ошибок + улучшенная версия\n\n"
        "<b>Команды:</b>\n"
        "• /menu — открыть меню\n"
        "• /reset — очистить контекст AI\n"
    )
    await safe_edit(callback.message, text, kb_back())
    await safe_answer(callback)


@router.callback_query(F.data == "reset_ai")
async def reset_ai_handler(callback: CallbackQuery):
    cleared = ai.clear_conversation(callback.from_user.id)
    await safe_answer(callback, "🧹 Контекст AI очищен!" if cleared else "🧹 Контекст AI уже был пуст.")
    await safe_edit(callback.message, "🎛️ <b>Главное меню</b>\n\nВыбери действие:", kb_main())


@router.callback_query(F.data == "back")
async def back_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(callback.message, "🎓 <b>NeuroEnglish Tutor</b>\n\nГлавное меню. Выбери действие:", kb_main())
    await safe_answer(callback)


@router.message()
async def fallback_handler(message: Message):
    txt = (message.text or "").strip().lower()
    if "спасибо" in txt or txt == "thanks":
        await message.answer("😊 Всегда рад помочь!", reply_markup=kb_main())
        return
    await message.answer(
        "💬 Лучше используй кнопки меню 👇\n\n"
        "Если хочешь задать вопрос — нажми <b>Вопрос AI</b>.",
        reply_markup=kb_main(),
    )


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env! (файл должен лежать рядом с main.py)")
        return

    print("\n" + "=" * 55)
    print("🎓 NeuroEnglish Tutor запущен!")
    print("📗 База данных: ✅")

    # Проверяем GigaChat настройки
    gigachat_client_id = os.getenv("GIGACHAT_CLIENT_ID")
    gigachat_client_secret = os.getenv("GIGACHAT_CLIENT_SECRET")

    if gigachat_client_id and gigachat_client_secret:
        print(f"🧠 GigaChat: ✅ настроен")
    else:
        print(f"🧠 GigaChat: ⚠️ не настроен (будут использоваться резервные упражнения)")

    print("=" * 55 + "\n")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
