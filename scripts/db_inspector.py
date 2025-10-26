# rebuild_graph.py

import asyncio
import logging
import os
from tqdm import tqdm

# Убедимся, что наши модули правильно импортируются
from ltm import ltm, LTM_Manager
from graph_manager import graph_manager
from config import GRAPH_FILE_PATH

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def main():
    """
    Основная функция для полного перестроения графа на основе данных из ChromaDB.
    """
    logging.info("--- 🚀 НАЧАЛО ПЕРЕСБОРКИ ГРАФА ---")

    # 1. Проверка и удаление старого файла графа
    if os.path.exists(GRAPH_FILE_PATH):
        logging.warning(f"🗑️ Найден старый файл графа '{GRAPH_FILE_PATH}'. Удаляем его для чистой пересборки.")
        try:
            os.remove(GRAPH_FILE_PATH)
            # Важно: нужно пересоздать экземпляр graph_manager, чтобы он загрузил пустой граф
            # Это самый простой способ "сбросить" его состояние.
            # В реальном приложении здесь была бы функция reset().
            global graph_manager
            graph_manager = type(graph_manager)(graph_path=GRAPH_FILE_PATH)
            logging.info("✅ Старый граф удален, менеджер графа сброшен.")
        except OSError as e:
            logging.error(f"❌ Не удалось удалить старый файл графа: {e}")
            return
    else:
        logging.info("ℹ️ Старый файл графа не найден, начинаем с чистого листа.")

    # 2. Получение всех "Когнитивных Активов" из базы
    logging.info("🧠 Загрузка всех Когнитивных Активов из базы данных...")
    try:
        # ltm.assets_collection.get() без параметров вернет все записи (с лимитом по умолчанию, но для сотен/тысяч этого хватит)
        all_assets = ltm.assets_collection.get(include=["metadatas"])
        asset_ids = all_assets.get('ids', [])

        if not asset_ids:
            logging.error("❌ В базе не найдено ни одного Когнитивного Актива. Пересборка невозможна.")
            return

        logging.info(f"👍 Найдено {len(asset_ids)} активов для обработки.")
    except Exception as e:
        logging.error(f"❌ Ошибка при получении активов из ChromaDB: {e}")
        return

    # 3. Пересоздание узлов графа (важно, т.к. мы удалили старый)
    logging.info("✍️ Пересоздание узлов графа из основной коллекции 'stream'...")
    all_stream_records = ltm.stream_collection.get(include=["metadatas"])
    for i, node_id in enumerate(all_stream_records['ids']):
        meta = all_stream_records['metadatas'][i]
        graph_manager.add_node_if_not_exists(node_id, role=meta.get('role'), timestamp=meta.get('timestamp'))
    logging.info(f"✅ Создано {graph_manager.graph.number_of_nodes()} узлов.")

    # 4. Итеративная пересборка ребер для каждого актива
    logging.info("🔗 Начало пересборки ребер графа. Это может занять некоторое время...")

    # Используем tqdm для красивого прогресс-бара
    for asset_id in tqdm(asset_ids, desc="Обработка активов"):
        try:
            # Вызываем "секретную" внутреннюю функцию из ltm, которая делает именно то, что нам нужно!
            await ltm._rebuild_graph_for_asset(asset_id)
        except Exception as e:
            logging.warning(f"⚠️  Произошла ошибка при обработке актива {asset_id}: {e}")

    logging.info("--- ✅ ПЕРЕСБОРКА РЕБЕР ЗАВЕРШЕНА ---")
    logging.info(
        f"📊 Новый граф содержит: {graph_manager.graph.number_of_nodes()} узлов и {graph_manager.graph.number_of_edges()} рёбер.")

    # 5. Сохранение нового графа
    logging.info("💾 Сохранение нового графа на диск...")
    graph_manager.save_graph()
    logging.info(f"🎉 Новый граф успешно сохранен в '{GRAPH_FILE_PATH}'.")


if __name__ == "__main__":
    asyncio.run(main())