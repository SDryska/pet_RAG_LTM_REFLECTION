# memory_cleaner.py

import chromadb
import pandas as pd
from tqdm import tqdm
import time

# --- Настройки ---
SHORT_MESSAGE_THRESHOLD_CHARS = 15
# Удаляем короткие сообщения с access_count <= этого значения
SHORT_MESSAGE_MAX_AC = 1

SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE = 0.2
# --- Конфигурация базы ---
CHROMA_DB_PATH = "db"
CHROMA_COLLECTION_NAME = "stream"


def confirm_action(prompt: str) -> bool:
    """Запрашивает у пользователя подтверждение действия."""
    while True:
        response = input(f"{prompt} (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            return True
        if response in ['n', 'no']:
            return False
        print("Пожалуйста, введите 'y' или 'n'.")


def run_memory_hygiene():
    """Основная функция для очистки и оптимизации LTM."""
    print("--- Запуск процедуры Гигиены Памяти ---")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_collection(name=CHROMA_COLLECTION_NAME)

        # --- Этап 1: Санитарная чистка ---
        clean_short_messages(collection)

        # --- Этап 2: Интеллектуальное слияние ---
        merge_semantic_duplicates(collection)

        print("\n--- Процедура Гигиены Памяти завершена. ---")

    except Exception as e:
        print(f"\nПроизошла критическая ошибка: {e}")


def clean_short_messages(collection: chromadb.Collection):
    """Находит и предлагает удалить короткие и 'холодные' сообщения."""
    print("\n--- Этап 1: Поиск коротких и неиспользуемых сообщений ---")

    try:
        # Получаем все данные. Для больших баз может быть медленно, но надежно.
        all_data = collection.get(include=["metadatas", "documents"])

        ids_to_delete = []
        short_records_for_display = []

        for i in range(len(all_data['ids'])):
            doc = all_data['documents'][i]
            meta = all_data['metadatas'][i]
            if (len(doc) < SHORT_MESSAGE_THRESHOLD_CHARS and
                    meta.get('access_count', 0) <= SHORT_MESSAGE_MAX_AC):
                ids_to_delete.append(all_data['ids'][i])
                short_records_for_display.append({
                    'id': all_data['ids'][i],
                    'access_count': meta.get('access_count', 0),
                    'document': doc
                })

        if not ids_to_delete:
            print("Не найдено коротких/неиспользуемых сообщений для удаления.")
            return

        print(f"Найдено {len(ids_to_delete)} записей-кандидатов на удаление:")
        df = pd.DataFrame(short_records_for_display)
        print(df.to_string())

        if confirm_action("\nУдалить эти записи?"):
            collection.delete(ids=ids_to_delete)
            print(f"Успешно удалено {len(ids_to_delete)} записей.")
        else:
            print("Удаление отменено.")

    except Exception as e:
        print(f"Ошибка на этапе санитарной чистки: {e}")


def merge_semantic_duplicates(collection: chromadb.Collection):
    """Находит, предлагает и выполняет слияние семантических дубликатов."""
    print("\n--- Этап 2: Поиск и слияние семантических дубликатов ---")

    all_data = collection.get(include=["metadatas", "documents"])
    if not all_data or not all_data['ids']:
        print("База данных пуста, слияние невозможно.")
        return

    processed_ids = set()

    for i in tqdm(range(len(all_data['ids'])), desc="Анализ дубликатов"):
        record_id = all_data['ids'][i]
        if record_id in processed_ids:
            continue

        query_doc = all_data['documents'][i]

        results = collection.query(
            query_texts=[query_doc],
            n_results=10,  # Ищем больше соседей для надежности
            include=["documents", "metadatas", "distances"]
        )

        group_candidates = []
        for j in range(len(results['ids'][0])):
            dist = results['distances'][0][j]
            if dist < SEMANTIC_DUPLICATE_THRESHOLD_DISTANCE:
                group_candidates.append({
                    'id': results['ids'][0][j],
                    'distance': round(dist, 4),
                    'metadata': results['metadatas'][0][j],
                    'document': results['documents'][0][j]
                })

        if len(group_candidates) <= 1:
            processed_ids.add(record_id)
            continue

        print("\n\n-----------------------------------------------------")
        print(f"Найдена группа из {len(group_candidates)} семантических дубликатов:")
        df_group = pd.DataFrame([{
            'id': rec['id'],
            'role': rec['metadata'].get('role'),
            'ac': rec['metadata'].get('access_count'),
            'timestamp': pd.to_datetime(rec['metadata'].get('timestamp'), unit='s'),
            'document': rec['document']
        } for rec in group_candidates])
        print(df_group.to_string())

        # Определяем стратегию
        internal_count = sum(1 for rec in group_candidates if rec['metadata'].get('role') == 'internal')
        is_thought_group = internal_count / len(group_candidates) > 0.5

        leader = None
        if is_thought_group:
            print("\nСтратегия: 'Новизна' (оставляем самую свежую мысль).")
            leader = max(group_candidates, key=lambda x: x['metadata'].get('timestamp', 0))
        else:
            print("\nСтратегия: 'Популярность' (оставляем запись с макс. access_count).")
            leader = max(group_candidates, key=lambda x: x['metadata'].get('access_count', 0))

        ids_to_delete = [rec['id'] for rec in group_candidates if rec['id'] != leader['id']]
        total_ac = sum(rec['metadata'].get('access_count', 0) for rec in group_candidates)

        print("\nПлан операции:")
        print(f"  - Оставить ID: {leader['id']}")
        print(f"  - Текст: '{leader['document'][:80]}...'")
        print(f"  - Присвоить новый access_count: {total_ac}")
        print(f"  - Удалить IDs: {ids_to_delete}")

        if confirm_action("Применить это слияние?"):
            try:
                # Обновляем лидера
                leader_meta = leader['metadata']
                leader_meta['access_count'] = total_ac
                collection.update(ids=[leader['id']], metadatas=[leader_meta])

                # Удаляем остальных
                if ids_to_delete:
                    collection.delete(ids=ids_to_delete)

                print("Слияние успешно выполнено.")
            except Exception as e:
                print(f"Ошибка при выполнении слияния: {e}")
        else:
            print("Слияние для этой группы отменено.")

        # Добавляем все ID из группы в обработанные, чтобы не анализировать их снова
        for rec in group_candidates:
            processed_ids.add(rec['id'])


if __name__ == "__main__":
    # Установка зависимостей: pip install pandas tqdm
    run_memory_hygiene()