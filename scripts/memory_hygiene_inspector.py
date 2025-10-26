# memory_hygiene_inspector.py

import chromadb
import pandas as pd
from tqdm import tqdm  # Библиотека для красивых progress bar

# --- Настройки инспектора ---
# Записи короче этого количества символов будут считаться кандидатами на удаление.
SHORT_MESSAGE_THRESHOLD_CHARS = 15

# Порог семантической близости для поиска дубликатов.
# Distance - это расстояние, чем оно меньше, тем ближе. 0 - идентичные.
# Для стандартной модели Chroma (L2-нормализация) хороший порог < 0.2
SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE = 0.2

# --- Конфигурация базы (можно вынести в config.py, если хотите) ---
CHROMA_DB_PATH = "db"
CHROMA_COLLECTION_NAME = "stream"


def inspect_memory_hygiene():
    """
    Анализирует LTM на предмет коротких записей и семантических дубликатов.
    """
    print("--- Инспектор Гигиены Памяти ---")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_collection(name=CHROMA_COLLECTION_NAME)

        # Получаем все данные один раз, чтобы не дергать базу постоянно
        all_data = collection.get(include=["metadatas", "documents"])

        if not all_data or not all_data['ids']:
            print("База данных пуста.")
            return

        print(f"Всего записей в базе: {len(all_data['ids'])}")

        # --- Анализ №1: Короткие сообщения ---
        find_short_messages(all_data)

        # --- Анализ №2: Семантические дубликаты ---
        find_semantic_duplicates(collection, all_data)

    except Exception as e:
        print(f"Произошла ошибка: {e}")


def find_short_messages(all_data: dict):
    """Находит и выводит слишком короткие записи."""
    print("\n--- Анализ 1: Короткие сообщения ---")
    print(f"Порог длины: {SHORT_MESSAGE_THRESHOLD_CHARS} символов.\n")

    short_records = []
    for i in range(len(all_data['ids'])):
        doc = all_data['documents'][i]
        if len(doc) < SHORT_MESSAGE_THRESHOLD_CHARS:
            meta = all_data['metadatas'][i]
            short_records.append({
                'id': all_data['ids'][i],
                'access_count': meta.get('access_count', 0),
                'role': meta.get('role', 'N/A'),
                'document': doc
            })

    if not short_records:
        print("Коротких сообщений, подпадающих под критерии, не найдено.")
        return

    df = pd.DataFrame(short_records)
    df_sorted = df.sort_values(by='access_count', ascending=False)

    print("Найденные короткие записи (кандидаты на удаление):")
    print(df_sorted.to_string())


def find_semantic_duplicates(collection: chromadb.Collection, all_data: dict):
    """Находит и выводит группы семантически близких записей."""
    print("\n--- Анализ 2: Семантические дубликаты ---")
    print(f"Порог расстояния (distance): < {SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE}\n")

    processed_ids = set()
    duplicate_groups = []

    # Используем tqdm для наглядности, так как процесс может быть долгим
    for i in tqdm(range(len(all_data['ids'])), desc="Поиск дубликатов"):
        record_id = all_data['ids'][i]

        if record_id in processed_ids:
            continue

        query_doc = all_data['documents'][i]

        # Ищем 5 ближайших соседей, включая саму запись
        results = collection.query(
            query_texts=[query_doc],
            n_results=5,
            include=["documents", "metadatas", "distances"]
        )

        current_group = []

        # results['distances'][0] - это список расстояний для нашего одного запроса
        distances = results['distances'][0]
        result_ids = results['ids'][0]

        for j in range(len(result_ids)):
            dist = distances[j]
            res_id = result_ids[j]

            # Если сосед очень близок (и это не сама запись)
            if dist < SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE:
                if not current_group:
                    # Добавляем оригинал в группу, только если найден хоть один дубликат
                    original_meta = all_data['metadatas'][i]
                    current_group.append({
                        'id': record_id,
                        'distance': 0.0,  # Расстояние до самого себя
                        'access_count': original_meta.get('access_count', 0),
                        'document': query_doc
                    })

                # Проверяем, что это не сама запись (хотя ее distance будет 0)
                if res_id != record_id:
                    res_meta = results['metadatas'][0][j]
                    current_group.append({
                        'id': res_id,
                        'distance': round(dist, 4),
                        'access_count': res_meta.get('access_count', 0),
                        'document': results['documents'][0][j]
                    })

        if len(current_group) > 1:
            duplicate_groups.append(current_group)
            # Добавляем все ID из найденной группы в обработанные, чтобы не проверять их заново
            for rec in current_group:
                processed_ids.add(rec['id'])

    if not duplicate_groups:
        print("Групп семантических дубликатов не найдено.")
        return

    print("Найдены следующие группы семантических дубликатов:")
    for i, group in enumerate(duplicate_groups):
        print(f"\n--- Группа {i + 1} ---")
        df_group = pd.DataFrame(group)
        print(df_group.to_string())


if __name__ == "__main__":
    # Установка зависимостей: pip install pandas tqdm
    inspect_memory_hygiene()