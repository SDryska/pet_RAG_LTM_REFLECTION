# force_reflection.py (интерактивная версия)

import asyncio
import logging
import sys
import google.generativeai as genai
import statistics
import os

import config
from ltm import ltm

# --- Настройка логгеров (остается без изменений) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
genai.configure(api_key=config.GEMINI_API_KEY)

thought_process_logger = logging.getLogger("ThoughtProcess")
thought_process_logger.setLevel(logging.INFO)
thought_process_logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - [ForceReflection] - %(message)s'))
thought_process_logger.addHandler(handler)

os.makedirs(config.LOG_DIR, exist_ok=True)
reflections_logger = logging.getLogger("Reflections")
reflections_logger.setLevel(logging.INFO)
reflections_logger.propagate = False
reflections_file_handler = logging.FileHandler(
    os.path.join(config.LOG_DIR, "reflections.log"),
    encoding='utf-8'
)
# Используем специальный форматтер, чтобы отличать принудительные мысли
reflections_file_handler.setFormatter(
    logging.Formatter('%(asctime)s\n[Forced Reflection from ID: %(seed_id)s]\n%(message)s\n' + '-' * 80)
)
reflections_logger.addHandler(reflections_file_handler)


async def force_reflection_on_id(seed_id: str):
    """
    Основная логика принудительной рефлексии для одного ID.
    """
    thought_process_logger.info(f"--- START FORCED REFLECTION CYCLE (Seed ID: {seed_id}) ---")

    # 1. Получаем "зерно" по ID
    seed_data = ltm.get_records_by_ids([seed_id])
    if not seed_data:
        thought_process_logger.error(f"Не удалось найти запись с ID: {seed_id}")
        print(f"\nОшибка: Запись с ID '{seed_id}' не найдена в базе.")
        return

    seed = {
        "id": seed_data[0]['id'],
        "doc": seed_data[0]['doc'],
        "meta": {
            'role': seed_data[0]['role'],
            'access_count': seed_data[0]['access_count'],
            'timestamp': seed_data[0].get('timestamp')
        }
    }

    thought_process_logger.info(
        f"Reflection seed loaded: '{seed['doc'][:80]}...' (ac={seed['meta'].get('access_count')})")

    # 2. Находим семантический кластер
    reflection_cluster = ltm.get_semantic_cluster(
        seed_doc=seed['doc'],
        cluster_size=config.REFLECTION_CLUSTER_SIZE
    )
    if not reflection_cluster:
        thought_process_logger.info("Could not form a semantic cluster around the seed. Skipping.")
        print("\nНе удалось сформировать семантический кластер вокруг этого 'зерна'.")
        return

    # 3. Подготовка промпта
    memories_for_prompt = [f"[{mem['role'].capitalize()} (ac={mem['access_count']})]: {mem['doc']}" for mem in
                           reflection_cluster]
    memories_str = "\n".join(f"- {mem}" for mem in memories_for_prompt)
    reflection_prompt = config.REFLECTION_PROMPT_TEMPLATE.format(hot_memories=memories_str)

    thought_process_logger.info(f"Formed a cluster of {len(reflection_cluster)} memories.")
    thought_process_logger.info(f"Reflection prompt sent to LLM:\n---\n{reflection_prompt}\n---")

    try:
        # 4. Акт Рефлексии
        print("\nОтправка запроса на рефлексию в LLM...")
        reflection_model = genai.GenerativeModel(config.GEMINI_MODEL_NAME)
        response = await reflection_model.generate_content_async(reflection_prompt)
        thought_text = response.text

        # 5. Вычисление "веса"
        parent_counts = [mem['access_count'] for mem in reflection_cluster]
        initial_thought_ac = round(statistics.median(parent_counts)) if parent_counts else 0

        thought_process_logger.info(f"Generated thought: '{thought_text}'")
        print(f"\nСгенерирована новая мысль:\n---\n{thought_text}\n---")

        # 6. Запись в дневник
        class SeedIdAdapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):
                kwargs['extra'] = {'seed_id': self.extra['seed_id']}
                return msg, kwargs

        adapter = SeedIdAdapter(reflections_logger, {'seed_id': seed_id})
        adapter.info(thought_text)

        # 7. Сохранение "Мысли" в LTM
        ltm.save_reflection(reflection_text=thought_text, initial_access_count=initial_thought_ac)

        # 8. "Охлаждение" памяти
        cluster_ids_to_cooldown = [rec['id'] for rec in reflection_cluster]
        ltm.cooldown_records_by_ids(cluster_ids_to_cooldown)

        print(f"\nПринудительная рефлексия для ID {seed_id} успешно завершена.")
        print(f"Новая мысль сохранена в LTM и в {os.path.join(config.LOG_DIR, 'reflections.log')}")

    except Exception as e:
        logging.error(f"Акт Рефлексии: Ошибка при генерации или сохранении мысли: {e}. 'Охлаждение' памяти отменено.")
        print(f"\nПроизошла ошибка в процессе рефлексии: {e}")

    thought_process_logger.info("--- END FORCED REFLECTION CYCLE ---")


async def interactive_reflection_session():
    """
    Запускает интерактивную сессию, запрашивая ID у пользователя в цикле.
    """
    print("--- Интерактивная сессия принудительной рефлексии ---")
    print("Введите ID записи для запуска рефлексии.")
    print("Для выхода введите 'exit' или 'quit'.\n")

    while True:
        # Запрашиваем ID у пользователя
        target_id = input("Введите ID записи-зерна: ").strip()

        # Проверяем команду выхода
        if target_id.lower() in ['exit', 'quit', 'q']:
            print("Завершение сессии.")
            break

        # Проверяем, что ID не пустой
        if not target_id:
            continue

        # Запускаем асинхронную функцию рефлексии
        await force_reflection_on_id(target_id)

        print("\n" + "=" * 50 + "\n")  # Разделитель для следующей итерации


if __name__ == "__main__":
    # Запускаем интерактивную сессию
    try:
        asyncio.run(interactive_reflection_session())
    except KeyboardInterrupt:
        print("\nСессия прервана пользователем.")
        sys.exit(0)