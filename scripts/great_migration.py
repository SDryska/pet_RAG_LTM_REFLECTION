# check_chroma.py
import chromadb
import time
import os

# Убедитесь, что путь к базе данных тот же, что и в вашем config.py
DB_PATH = "db"
COLLECTION_NAME = "test_collection"

print(f"--- НАЧАЛО ДИАГНОСТИКИ CHROMA DB ---")
print(f"Путь к базе данных: {os.path.abspath(DB_PATH)}")

try:
    # 1. Инициализируем клиент
    client = chromadb.PersistentClient(path=DB_PATH)
    print("Шаг 1: Клиент ChromaDB успешно инициализирован.")

    # 2. Создаем или получаем тестовую коллекцию
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    print(f"Шаг 2: Коллекция '{COLLECTION_NAME}' получена/создана. Текущее количество записей: {collection.count()}")

    # Очистим тестовую запись, если она осталась с прошлого раза
    collection.delete(ids=["test-doc-1"])

    # 3. Добавляем один документ. В этот момент ChromaDB ДОЛЖНА начать
    # скачивание/инициализацию модели эмбеддингов.
    print("Шаг 3: Добавляю тестовый документ 'Это тест'. Ожидайте, это может занять до минуты...")
    collection.add(
        documents=["Это тест"],
        metadatas=[{'source': 'test'}],
        ids=["test-doc-1"]
    )
    print("Шаг 3.1: Команда .add() выполнена. Начинаю проверку результата.")

    # 4. Ждем и проверяем, появился ли эмбеддинг
    embedding_result = None
    for i in range(45):
        print(f"  Попытка {i + 1}/45: Проверяю наличие эмбеддинга...")
        record = collection.get(ids=["test-doc-1"], include=["embeddings"])
        if record and record['embeddings'] and record['embeddings'][0] is not None:
            print("\n[✓✓✓] УСПЕХ! Эмбеддинг успешно создан.")
            embedding_result = record['embeddings'][0]
            break
        time.sleep(1)

    # 5. Выводим финальный результат
    print("\n--- РЕЗУЛЬТАТ ДИАГНОСТИКИ ---")
    if embedding_result:
        print("Статус: OK")
        print(f"ChromaDB работает корректно и смогла создать эмбеддинг.")
        print(f"Фрагмент эмбеддинга: {embedding_result[:5]}...")
    else:
        print("[XXX] ПРОВАЛ!")
        print("ChromaDB НЕ СМОГЛА создать эмбеддинг за 45 секунд.")
        print("Наиболее вероятная причина: нет доступа к интернету или блокировка файрволом,")
        print("необходимые для скачивания модели эмбеддингов с Hugging Face.")

    # Очистка
    collection.delete(ids=["test-doc-1"])
    print("\n--- ДИАГНОСТИКА ЗАВЕРШЕНА ---")

except Exception as e:
    print(f"\n[!!!] КРИТИЧЕСКАЯ ОШИБКА во время диагностики: {e}")