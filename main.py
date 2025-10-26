# main.py
# Версия для aiogram 3.x и архитектуры v2.0 "Концептуальное Ядро"
# ИСПРАВЛЕНИЕ: Правильная обработка задач извлечения концептов + отладка + поддержка Markdown

import asyncio
import logging
import aiogram
import google.generativeai as genai
import statistics
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ChatAction, ParseMode  # ИЗМЕНЕНО: Добавлен импорт ParseMode
from aiogram.exceptions import TelegramBadRequest

import config
from ltm import ltm
from graph_manager import graph_manager

# --- Настройка ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
if not config.TELEGRAM_BOT_TOKEN or not config.GEMINI_API_KEY:
    raise ValueError("Необходимо установить TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в .env файле")

# Инициализация для aiogram 3.x
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Глобальная конфигурация API ключа для основной модели
genai.configure(api_key=config.GEMINI_API_KEY)
user_chats = {}

# --- Логирование ---
os.makedirs(config.LOG_DIR, exist_ok=True)
thought_process_logger = logging.getLogger("ThoughtProcess")
thought_process_logger.setLevel(logging.INFO)
thought_process_logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - [ThoughtProcess] - %(message)s'))
thought_process_logger.addHandler(handler)

reflections_logger = logging.getLogger("Reflections")
reflections_logger.setLevel(logging.INFO)
reflections_logger.propagate = False
reflections_file_handler = logging.FileHandler(os.path.join(config.LOG_DIR, "reflections.log"), encoding='utf-8')
reflections_file_handler.setFormatter(logging.Formatter('%(asctime)s\n%(message)s\n' + '-' * 80))
reflections_logger.addHandler(reflections_file_handler)

# Добавляем специальный логгер для концептов
concepts_logger = logging.getLogger("Concepts")
concepts_logger.setLevel(logging.INFO)
concepts_logger.propagate = False
concepts_handler = logging.StreamHandler()
concepts_handler.setFormatter(logging.Formatter('%(asctime)s - [CONCEPTS] - %(message)s'))
concepts_logger.addHandler(concepts_handler)


# --- Вспомогательные функции ---
# --- Вспомогательные функции ---
async def safe_extract_assets(parent_id: str, description: str):
    """
    Безопасное извлечение активов с полным логированием ошибок
    """
    # ИЗМЕНЕНО: Обновлены логи для соответствия "Активам"
    concepts_logger.info(f"=== НАЧАЛО ИЗВЛЕЧЕНИЯ АКТИВОВ ===")
    concepts_logger.info(f"Parent ID: {parent_id}")
    concepts_logger.info(f"Description: {description}")

    try:
        # ИСПРАВЛЕНИЕ: Вызываем правильный метод extract_and_process_assets
        await ltm.extract_and_process_assets(parent_id=parent_id)
        concepts_logger.info(f"✓ Успешно завершено извлечение активов для {parent_id} ({description})")
    except Exception as e:
        concepts_logger.error(f"✗ ОШИБКА при извлечении активов для {parent_id} ({description}): {e}", exc_info=True)
        # Дополнительное логирование для диагностики
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА АКТИВОВ [{parent_id}]: {e}", exc_info=True)

    concepts_logger.info(f"=== КОНЕЦ ИЗВЛЕЧЕНИЯ АКТИВОВ ===")


async def run_concepts_extraction_with_wait(user_record_id: str, bot_record_id: str):
    """
    Запускает извлечение активов для обеих записей и ждет их завершения
    """
    # ИЗМЕНЕНО: Обновлены логи
    concepts_logger.info("Запуск параллельного извлечения активов для диалоговой пары...")

    # Создаем задачи
    # ИСПРАВЛЕНИЕ: Вызываем переименованную функцию safe_extract_assets
    user_task = asyncio.create_task(
        safe_extract_assets(user_record_id, "USER_MESSAGE"),
        name=f"extract_user_{user_record_id}"
    )
    bot_task = asyncio.create_task(
        safe_extract_assets(bot_record_id, "BOT_RESPONSE"),
        name=f"extract_bot_{bot_record_id}"
    )

    # Ждем завершения обеих задач
    try:
        await asyncio.gather(user_task, bot_task, return_exceptions=True)
        concepts_logger.info("Извлечение активов для диалоговой пары завершено")
    except Exception as e:
        concepts_logger.error(f"Ошибка при групповом извлечении активов: {e}", exc_info=True)


# НОВАЯ ФУНКЦИЯ: Конвертация Markdown для Telegram
def convert_to_telegram_markdown(text: str) -> str:
    """
    Конвертирует распространенные Markdown-форматы (например, **bold** от Gemini)
    в формат, поддерживаемый Telegram в режиме 'Markdown' (legacy: *bold*).
    Также обрабатывает _italic_.
    """
    # Заменяем **bold** на *bold*
    # Используем нежадный поиск (.*?), чтобы правильно обработать несколько выделений в одной строке
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # Заменяем __italic__ на _italic_ (если модель будет его использовать)
    text = re.sub(r'__(.*?)__', r'_\1_', text)

    # ВАЖНО: Режим 'Markdown' не требует экранирования большинства символов,
    # в отличие от 'MarkdownV2', что делает его более устойчивым для вывода LLM.
    # Мы не экранируем другие символы намеренно.
    return text


# --- Обработчики (синтаксис aiogram 3.x) ---
@dp.message(CommandStart())
async def handle_start(message: Message):
    user_id = message.from_user.id
    if user_id in user_chats:
        del user_chats[user_id]
        logging.info(f"Пользователь {user_id} начал новый диалог. Старая сессия STM удалена.")
    await message.answer("Цифровой Генезис: Этап 4.0. Концептуальное Ядро активно. Системы в норме.")


@dp.message(F.text)
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    user_text = message.text

    chat_session = user_chats.get(user_id)
    if not chat_session:
        logging.info(f"Для пользователя {user_id} не найдена активная сессия STM. Создаю новую.")
        model = genai.GenerativeModel(
            config.GEMINI_MODEL_NAME,
            system_instruction=config.SYSTEM_PROMPT,
            safety_settings=config.SAFETY_SETTINGS
        )
        chat_session = model.start_chat(history=[])
        user_chats[user_id] = chat_session

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        thought_memories, _ = ltm.search_and_update(
            query_text=user_text,
            n_results=config.THOUGHT_SEARCH_RESULT_COUNT,
            where_filter={"role": "internal"}
        )
        dialogue_memories, dialogue_access_counts = ltm.search_and_update(
            query_text=user_text,
            n_results=config.DIALOGUE_SEARCH_RESULT_COUNT,
            where_filter={"role": {"$in": ["user", config.AI_ROLE_NAME]}}
        )

        all_relevant_memories = list(dict.fromkeys(thought_memories + dialogue_memories))
        final_prompt = user_text
        if all_relevant_memories:
            memories_str = "\n".join(f"- {mem}" for mem in all_relevant_memories)
            final_prompt = config.MEMORY_PROMPT_TEMPLATE.format(memories=memories_str, user_text=user_text)

        thought_process_logger.info(f"--- START DIALOGUE TURN (User: {user_id}) ---")
        thought_process_logger.info(f"User query: '{user_text}'")
        thought_process_logger.info(f"Final prompt sent to LLM:\n---\n{final_prompt}\n---")

        response = await chat_session.send_message_async(final_prompt)
        bot_response_original = response.text

        # ИЗМЕНЕНО: Блок отправки сообщения с поддержкой Markdown
        bot_response_formatted = convert_to_telegram_markdown(bot_response_original)
        try:
            # Используем ParseMode.MARKDOWN (старый, более щадящий стиль)
            await message.answer(bot_response_formatted, parse_mode=ParseMode.MARKDOWN)
        except TelegramBadRequest as e:
            # Если парсинг не удался (например, из-за незакрытого '*'), отправляем как простой текст
            logging.warning(f"Ошибка парсинга Markdown: {e}. Отправка как простой текст.")
            await message.answer(bot_response_original)

        bot_response_ac = round(statistics.median(dialogue_access_counts)) if dialogue_access_counts else 0
        user_record_id, bot_record_id = await ltm.save_dialogue_pair(
            user_text=user_text,
            bot_text=bot_response_original,
            bot_response_access_count=bot_response_ac
        )

        thought_process_logger.info(f"Bot response: '{bot_response_original}'")
        thought_process_logger.info(f"Записи сохранены: User ID={user_record_id}, Bot ID={bot_record_id}")

        concepts_logger.info("Инициируется извлечение концептов для диалоговой пары...")
        await run_concepts_extraction_with_wait(user_record_id, bot_record_id)

        thought_process_logger.info(f"--- END DIALOGUE TURN ---")

    except Exception as e:
        logging.error(f"Критическая ошибка при обработке сообщения от {user_id}: {e}", exc_info=True)
        await message.answer(
            "Произошла ошибка во время обработки вашего запроса. Попробуйте начать заново с команды /start.")
        if user_id in user_chats:
            del user_chats[user_id]


# --- ЛОГИКА РЕФЛЕКСИИ ---
async def run_reflection_cycle():
    """
    Цикл рефлексии с полной обработкой ошибок
    """
    try:
        thought_process_logger.info("--- START FOCUSED REFLECTION CYCLE ---")
        concepts_logger.info("🔄 РЕФЛЕКСИЯ: Поиск горячих записей для рефлексии...")

        # Проверяем наличие необходимых конфигураций
        if not hasattr(config, 'REFLECTION_MIN_ACCESS_COUNT'):
            concepts_logger.error("🔄 РЕФЛЕКСИЯ: REFLECTION_MIN_ACCESS_COUNT не найден в конфигурации")
            return

        if not hasattr(config, 'REFLECTION_CLUSTER_SIZE'):
            concepts_logger.error("🔄 РЕФЛЕКСИЯ: REFLECTION_CLUSTER_SIZE не найден в конфигурации")
            return

        if not hasattr(config, 'REFLECTION_PROMPT_TEMPLATE'):
            concepts_logger.error("🔄 РЕФЛЕКСИЯ: REFLECTION_PROMPT_TEMPLATE не найден в конфигурации")
            return

        seed = ltm.get_random_hot_record_as_seed(config.REFLECTION_MIN_ACCESS_COUNT)
        if not seed:
            thought_process_logger.info("No hot records to serve as a seed. Skipping reflection.")
            concepts_logger.info("🔄 РЕФЛЕКСИЯ: Горячие записи не найдены, пропуск цикла")
            return

        thought_process_logger.info(f"Reflection seed chosen: '{seed['doc'][:80]}...'")
        concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Выбрано зерно рефлексии: ID={seed['id']}")

        reflection_cluster = ltm.get_semantic_cluster(seed_doc=seed['doc'], cluster_size=config.REFLECTION_CLUSTER_SIZE)
        if not reflection_cluster:
            thought_process_logger.info("Could not form a semantic cluster around the seed. Skipping.")
            concepts_logger.info("🔄 РЕФЛЕКСИЯ: Не удалось сформировать семантический кластер")
            return

        concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Сформирован кластер из {len(reflection_cluster)} записей")

        # Безопасное формирование промпта
        try:
            memories_for_prompt = []
            for mem in reflection_cluster:
                role = mem.get('role', 'unknown')
                access_count = mem.get('access_count', 0)
                doc = mem.get('doc', '')
                memories_for_prompt.append(f"[{role.capitalize()} (ac={access_count})]: {doc}")

            memories_str = "\n".join(f"- {mem}" for mem in memories_for_prompt)
            reflection_prompt = config.REFLECTION_PROMPT_TEMPLATE.format(hot_memories=memories_str)
            concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Сформирован промпт длиной {len(reflection_prompt)} символов")
        except Exception as e:
            concepts_logger.error(f"🔄 РЕФЛЕКСИЯ: Ошибка при формировании промпта: {e}", exc_info=True)
            return

        thought_text = None
        try:
            concepts_logger.info("🔄 РЕФЛЕКСИЯ: Отправка запроса к основной модели...")

            # Создаем модель каждый раз заново для рефлексии
            reflection_model = genai.GenerativeModel(
                model_name=config.GEMINI_MODEL_NAME,
                safety_settings=config.SAFETY_SETTINGS
            )
            response = await reflection_model.generate_content_async(reflection_prompt)
            thought_text = response.text
            concepts_logger.info("🔄 РЕФЛЕКСИЯ: Получен ответ от основной модели")

        except Exception as e:
            logging.error(f"Reflection error with main model: {e}", exc_info=True)
            concepts_logger.warning(f"🔄 РЕФЛЕКСИЯ: Ошибка основной модели, переключение на резервную: {e}")

            # Проверяем наличие резервной модели
            if not hasattr(config, 'GEMINI_BACKUP_MODEL_NAME'):
                concepts_logger.error("🔄 РЕФЛЕКСИЯ: GEMINI_BACKUP_MODEL_NAME не найден в конфигурации")
                return

            try:
                backup_model = genai.GenerativeModel(
                    model_name=config.GEMINI_BACKUP_MODEL_NAME,
                    safety_settings=config.SAFETY_SETTINGS
                )
                response = await backup_model.generate_content_async(reflection_prompt)
                thought_text = response.text
                concepts_logger.info("🔄 РЕФЛЕКСИЯ: Получен ответ от резервной модели")
            except Exception as e2:
                logging.error(f"Reflection failed with backup model: {e2}", exc_info=True)
                concepts_logger.error(f"🔄 РЕФЛЕКСИЯ: Критическая ошибка, цикл прерван: {e2}")
                return

        if thought_text and thought_text.strip():
            thought_process_logger.info(f"Generated thought: '{thought_text}'")
            reflections_logger.info(thought_text)
            concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Сгенерирована мысль длиной {len(thought_text)} символов")

            try:
                parent_counts = [mem.get('access_count', 0) for mem in reflection_cluster]
                initial_thought_ac = round(statistics.median(parent_counts)) if parent_counts else 0

                reflection_id = await ltm.save_reflection(reflection_text=thought_text,
                                                          initial_access_count=initial_thought_ac)
                concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Рефлексия сохранена с ID={reflection_id}")

                # Извлечение активов для рефлексии
                concepts_logger.info("🔄 РЕФЛЕКСИЯ: Запуск извлечения активов...")
                # ИСПРАВЛЕНИЕ: Вызываем переименованную функцию safe_extract_assets
                await safe_extract_assets(reflection_id, "REFLECTION")

                # Охлаждение записей
                cluster_ids = [rec.get('id') for rec in reflection_cluster if rec.get('id')]
                if cluster_ids:
                    ltm.cooldown_records_by_ids(cluster_ids)
                    concepts_logger.info(f"🔄 РЕФЛЕКСИЯ: Выполнено охлаждение {len(cluster_ids)} записей кластера")
                else:
                    concepts_logger.warning("🔄 РЕФЛЕКСИЯ: Нет ID для охлаждения записей")

            except Exception as e:
                concepts_logger.error(f"🔄 РЕФЛЕКСИЯ: Ошибка при сохранении рефлексии: {e}", exc_info=True)
        else:
            concepts_logger.warning("🔄 РЕФЛЕКСИЯ: Получен пустой или некорректный текст мысли")

        thought_process_logger.info("--- END FOCUSED REFLECTION CYCLE ---")
        concepts_logger.info("🔄 РЕФЛЕКСИЯ: Цикл рефлексии завершен успешно")

    except Exception as e:
        logging.error(f"КРИТИЧЕСКАЯ ОШИБКА в цикле рефлексии: {e}", exc_info=True)
        concepts_logger.error(f"🔄 РЕФЛЕКСИЯ: КРИТИЧЕСКАЯ ОШИБКА цикла: {e}", exc_info=True)


async def main():
    """Основная асинхронная функция, которая запускает все компоненты."""

    # Проверяем настройки концептов при запуске
    concepts_logger.info("=== ДИАГНОСТИКА СИСТЕМЫ КОНЦЕПТОВ ===")
    concepts_logger.info(
        f"GEMINI_CONCEPTS_API_KEY установлен: {bool(getattr(config, 'GEMINI_CONCEPTS_API_KEY', None))}")
    concepts_logger.info(f"GEMINI_CONCEPTS_MODEL_NAME: {getattr(config, 'GEMINI_CONCEPTS_MODEL_NAME', 'НЕ ЗАДАН')}")
    concepts_logger.info(f"CONCEPT_EXTRACTION_PROMPT длина: {len(getattr(config, 'CONCEPT_EXTRACTION_PROMPT', ''))}")
    concepts_logger.info("=======================================")

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_reflection_cycle, 'interval', seconds=config.REFLECTION_INTERVAL_SECONDS, id='reflection_job')
    scheduler.add_job(graph_manager.save_graph, 'interval', seconds=config.GRAPH_SAVE_INTERVAL_SECONDS,
                      id='save_graph_job')
    scheduler.start()
    logging.info("Планировщик фоновых задач запущен.")

    try:
        logging.info("Запуск поллинга Telegram...")
        # В aiogram 3.x используется dp.start_polling(bot)
        await dp.start_polling(bot)
    finally:
        logging.info("Остановка поллинга...")
        scheduler.shutdown()
        logging.info("Планировщик остановлен.")
        logging.info("Выполняется финальное сохранение графа...")
        graph_manager.save_graph()
        logging.info("Система 'Цифровой Генезис' остановлена.")


if __name__ == '__main__':
    logging.info("Запуск системы 'Цифровой Генезис'...")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен вручную.")