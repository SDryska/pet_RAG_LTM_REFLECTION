# concepts_inspector.py

import chromadb
import pandas as pd
from tqdm import tqdm
import json  # Добавляем для работы с JSON-строками
import os

# --- Настройки инспектора ---
# Порог семантической близости для поиска дубликатов концептов.
# Distance - это расстояние, чем оно меньше, тем ближе.
# Для концептов порог должен быть строже, чем для стрима,
# так как мы ищем практически синонимичные утверждения.
# Хорошее начальное значение: 0.1
SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE = 0.1

# --- Конфигурация из проекта ---
# Используем переменные из config.py для консистентности
try:
    from config import CHROMA_DB_PATH, CHROMA_CONCEPTS_COLLECTION_NAME
except ImportError:
    print("Не удалось импортировать config.py. Используются значения по умолчанию.")
    CHROMA_DB_PATH = "db"
    CHROMA_CONCEPTS_COLLECTION_NAME = "concepts"


def inspect_concepts_hygiene():
    """
    Анализирует "Концептуальное Ядро" (коллекцию концептов)
    на предмет семантических дубликатов.
    """
    print("--- Инспектор Гигиены Концептуального Ядра ---")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_collection(name=CHROMA_CONCEPTS_COLLECTION_NAME)

        # Получаем все данные один раз, чтобы не дергать базу постоянно
        all_data = collection.get(include=["metadatas", "documents"])

        if not all_data or not all_data['ids']:
            print("Коллекция концептов пуста.")
            return

        print(f"Всего концептов в базе: {len(all_data['ids'])}")

        # --- Основной анализ: Семантические дубликаты концептов ---
        find_semantic_duplicates(collection, all_data)

    except Exception as e:
        print(f"Произошла критическая ошибка: {e}", exc_info=True)


def find_semantic_duplicates(collection: chromadb.Collection, all_data: dict):
    """Находит и выводит группы семантически близких концептов."""
    print("\n--- Поиск семантических дубликатов ---")
    print(f"Порог расстояния (distance): < {SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE}\n")

    # Создаем map для быстрого доступа к метаданным по ID
    metadata_map = {all_data['ids'][i]: all_data['metadatas'][i] for i in range(len(all_data['ids']))}
    document_map = {all_data['ids'][i]: all_data['documents'][i] for i in range(len(all_data['ids']))}

    processed_ids = set()
    duplicate_groups_found = 0

    for record_id in tqdm(all_data['ids'], desc="Анализ концептов"):
        if record_id in processed_ids:
            continue

        query_doc = document_map[record_id]

        # Ищем 5 ближайших соседей. Для концептов этого обычно достаточно.
        results = collection.query(
            query_texts=[query_doc],
            n_results=5,
            include=["metadatas", "distances"]
        )

        current_group = []

        # Собираем всех кандидатов, которые проходят по порогу
        for j in range(len(results['ids'][0])):
            dist = results['distances'][0][j]
            res_id = results['ids'][0][j]

            if dist < SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE:
                # Получаем метаданные и количество родителей
                meta = results['metadatas'][0][j]
                try:
                    # parent_ids хранится как JSON-строка
                    num_parents = len(json.loads(meta.get('parent_ids', '[]')))
                except (json.JSONDecodeError, TypeError):
                    num_parents = 0

                current_group.append({
                    'id': res_id,
                    'distance': round(dist, 4),
                    'num_parents': num_parents,
                    'document': collection.get(ids=[res_id])['documents'][0]
                })

        # Если в группе больше одного элемента, значит мы нашли дубликаты
        if len(current_group) > 1:
            duplicate_groups_found += 1
            print(f"\n\n--- Найдена Группа Дубликатов #{duplicate_groups_found} ---")
            df_group = pd.DataFrame(current_group)
            # Сортируем внутри группы по расстоянию, чтобы было нагляднее
            print(df_group.sort_values(by='distance').to_string(index=False))

            # Добавляем все ID из найденной группы в обработанные, чтобы не проверять их заново
            for rec in current_group:
                processed_ids.add(rec['id'])

    if duplicate_groups_found == 0:
        print("\nГрупп семантических дубликатов, удовлетворяющих порогу, не найдено.")


if __name__ == "__main__":
    # Убедитесь, что у вас установлены зависимости: pip install pandas tqdm chromadb
    inspect_concepts_hygiene()