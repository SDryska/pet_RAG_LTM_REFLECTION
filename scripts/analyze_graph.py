# export_db_to_csv.py (v4 - Final Architecture)

import chromadb
import csv
import os
import json
import logging

try:
    from config import (
        CHROMA_DB_PATH,
        CHROMA_STREAM_COLLECTION_NAME,
        CHROMA_CONCEPTS_COLLECTION_NAME, # cognitive_assets
        CHROMA_FACTS_COLLECTION_NAME,
        CHROMA_MODALITIES_COLLECTION_NAME
    )
except ImportError:
    print("Ошибка: Не удалось импортировать настройки из config.py.")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
OUTPUT_DIR = "export"

def process_collection(collection: chromadb.Collection, output_filename: str):
    """
    Извлекает все данные из коллекции и сохраняет их в CSV-файл,
    оптимизированный для открытия в Microsoft Excel.
    """
    collection_name = collection.name
    logging.info(f"Начинаю обработку коллекции: '{collection_name}'...")

    try:
        data = collection.get(include=["documents", "metadatas"])
    except Exception as e:
        logging.error(f"Не удалось получить данные из коллекции '{collection_name}': {e}")
        return

    if not data or not data['ids']:
        logging.warning(f"Коллекция '{collection_name}' пуста. Файл не будет создан.")
        return

    # --- Подготовка данных и заголовков ---
    all_metadata_keys = set()
    for metadata in data['metadatas']:
        if metadata:
            all_metadata_keys.update(metadata.keys())

    sorted_metadata_keys = sorted(list(all_metadata_keys))
    # Убедимся, что document всегда второй, если он есть
    headers = ['id']
    if 'document' in sorted_metadata_keys:
        headers.append('document')
        sorted_metadata_keys.remove('document')
    headers.extend(sorted_metadata_keys)


    rows_to_write = []
    for i in range(len(data['ids'])):
        row = {'id': data['ids'][i]}
        # Добавляем документ, если он есть
        if data['documents'] and data['documents'][i] is not None:
             row['document'] = data['documents'][i]

        metadata = data['metadatas'][i] or {}

        # Распаковываем JSON-поля для лучшей читаемости
        for key in ['parent_ids', 'тональность']:
             if key in metadata and isinstance(metadata.get(key), str):
                try:
                    items_list = json.loads(metadata[key])
                    metadata[key] = ", ".join(items_list)
                except (json.JSONDecodeError, TypeError):
                    pass # Оставляем как есть, если невалидный JSON или не список

        row.update(metadata)
        rows_to_write.append(row)

    # --- Сортировка и адаптация данных для каждой коллекции ---
    if collection_name == CHROMA_STREAM_COLLECTION_NAME:
        rows_to_write.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    elif collection_name == CHROMA_FACTS_COLLECTION_NAME:
        # Факты сортируем по алфавиту для удобства
        rows_to_write.sort(key=lambda x: x.get('document', ''))
    elif collection_name == CHROMA_CONCEPTS_COLLECTION_NAME: # Когнитивные активы
        # Переименовываем 'document' в 'debug_info' для ясности
        if 'document' in headers:
            headers[headers.index('document')] = 'debug_info'
            for row in rows_to_write:
                if 'document' in row:
                    row['debug_info'] = row.pop('document')
        # Сортируем по ID родителя, чтобы видеть активы от одной реплики вместе
        rows_to_write.sort(key=lambda x: x.get('parent_id', ''))
    elif collection_name == CHROMA_MODALITIES_COLLECTION_NAME:
        # Переименовываем 'document' в 'hydrated_text'
        if 'document' in headers:
            headers[headers.index('document')] = 'hydrated_text'
            for row in rows_to_write:
                if 'document' in row:
                    row['hydrated_text'] = row.pop('document')
        # Сортируем по оригинальному тексту
        rows_to_write.sort(key=lambda x: x.get('original_text', ''))


    # --- Запись в CSV файл ---
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    try:
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            # Убедимся, что все ключи из rows_to_write есть в заголовках
            all_keys = set()
            for row in rows_to_write:
                all_keys.update(row.keys())
            final_headers = sorted(list(all_keys), key=lambda x: (x!='id', x!='document', x))

            writer = csv.DictWriter(csvfile, fieldnames=final_headers, delimiter=';', extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows_to_write)

        logging.info(
            f"Успешно экспортировано {len(rows_to_write)} записей из '{collection_name}' в файл: {output_path}")

    except Exception as e:
        logging.error(f"Ошибка при записи CSV для '{collection_name}': {e}", exc_info=True)


def main():
    print(f"--- Запуск экспорта данных из ChromaDB в CSV (v4 Architecture) ---")
    if not os.path.exists(CHROMA_DB_PATH):
        logging.error(f"Директория с базой данных не найдена: {CHROMA_DB_PATH}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection_names_map = {
            "stream": CHROMA_STREAM_COLLECTION_NAME,
            "assets": CHROMA_CONCEPTS_COLLECTION_NAME,
            "facts": CHROMA_FACTS_COLLECTION_NAME,
            "modalities": CHROMA_MODALITIES_COLLECTION_NAME
        }

        db_collections = {c.name for c in client.list_collections()}

        for name, const_name in collection_names_map.items():
            if const_name in db_collections:
                collection = client.get_collection(name=const_name)
                process_collection(collection, f"{name}.csv")
            else:
                logging.warning(f"Коллекция '{const_name}' не найдена в базе. Пропускаем.")

        print(f"\n--- Экспорт завершен. Файлы сохранены в '{os.path.abspath(OUTPUT_DIR)}' ---")

    except Exception as e:
        logging.critical(f"Критическая ошибка во время экспорта: {e}", exc_info=True)

if __name__ == "__main__":
    main()