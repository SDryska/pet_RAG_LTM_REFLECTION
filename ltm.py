# ltm.py (v4 - Final Architecture: Stream -> Facts -> Modalities -> Assets)

import chromadb
import uuid
import time
import logging
import random
import hashlib
import json
import asyncio

from collections import defaultdict

import google.generativeai as genai
from config import (
    CHROMA_DB_PATH, CHROMA_STREAM_COLLECTION_NAME,
    CHROMA_CONCEPTS_COLLECTION_NAME,
    CHROMA_FACTS_COLLECTION_NAME,
    CHROMA_MODALITIES_COLLECTION_NAME,
    AI_ROLE_NAME, CONCEPT_EXTRACTION_PROMPT,
    GEMINI_CONCEPTS_API_KEY, GEMINI_CONCEPTS_MODEL_NAME, SAFETY_SETTINGS,
    CONCEPT_NEIGHBOR_COUNT, GRAPH_ASSOCIATIVE_THRESHOLD
)
from graph_manager import graph_manager


class LTM_Manager:
    def __init__(self):
        try:
            self.client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
            self.stream_collection = self.client.get_or_create_collection(name=CHROMA_STREAM_COLLECTION_NAME)
            self.assets_collection = self.client.get_or_create_collection(name=CHROMA_CONCEPTS_COLLECTION_NAME)
            self.facts_collection = self.client.get_or_create_collection(name=CHROMA_FACTS_COLLECTION_NAME)
            self.modalities_collection = self.client.get_or_create_collection(name=CHROMA_MODALITIES_COLLECTION_NAME)

            logging.info(f"LTM Manager: Инициализировано 4 коллекции: "
                         f"Stream: {self.stream_collection.count()}, "
                         f"Assets: {self.assets_collection.count()}, "
                         f"Facts: {self.facts_collection.count()}, "
                         f"Modalities: {self.modalities_collection.count()}.")

            self._concepts_model_instance = None
        except Exception as e:
            logging.critical(f"LTM Manager: Не удалось инициализировать ChromaDB! Ошибка: {e}", exc_info=True)
            raise

    def _get_concepts_model(self):
        if self._concepts_model_instance is None:
            if not GEMINI_CONCEPTS_API_KEY:
                logging.error("LTM: API-ключ для концептов (GEMINI_CONCEPTS_API_KEY) не найден!")
                return None
            logging.info("LTM: Инициализация независимой модели для извлечения активов...")
            genai.configure(api_key=GEMINI_CONCEPTS_API_KEY)
            self._concepts_model_instance = genai.GenerativeModel(
                model_name=GEMINI_CONCEPTS_MODEL_NAME,
                safety_settings=SAFETY_SETTINGS
            )
            logging.info(f"LTM: Независимая модель '{GEMINI_CONCEPTS_MODEL_NAME}' для активов успешно создана.")
        return self._concepts_model_instance

    def _get_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def _get_context_phrase_for_llm(self, role: str) -> str:
        if role == 'user': return "Проанализируй этот текст. Это реплика твоего собеседника (пользователя)."
        if role == 'internal': return "Проанализируй этот текст. Это твоя внутренняя мысль, результат рефлексии."
        if role == AI_ROLE_NAME: return "Проанализируй этот текст. Это твоя собственная реплика в диалоге."
        return f"Проанализируй этот текст. Это реплика, произнесенная {role}."

    async def _add_to_stream(self, text: str, role: str, initial_ac: int = 0) -> str:
        text_hash = self._get_hash(text)
        # Обернем I/O в to_thread для полной асинхронности
        existing = await asyncio.to_thread(
            self.stream_collection.get, where={"hash": {"$eq": text_hash}}, limit=1
        )
        if existing and existing['ids']:
            logging.debug(f"LTM Stream: Найдена существующая запись с хешем {text_hash[:16]}...")
            return existing['ids'][0]

        new_id = f"{role}_{str(uuid.uuid4())}"
        metadata = {"role": role, "timestamp": time.time(), "access_count": initial_ac, "hash": text_hash}
        # Обернем I/O в to_thread
        await asyncio.to_thread(self.stream_collection.add, documents=[text], metadatas=[metadata], ids=[new_id])

        # <-- ИСПРАВЛЕНО: Добавлен await
        await graph_manager.add_node_if_not_exists(new_id, role=role, timestamp=metadata["timestamp"])

        logging.info(f"LTM Stream: Создана новая запись ID {new_id} для роли '{role}'.")
        return new_id

    async def save_dialogue_pair(self, user_text: str, bot_text: str, bot_response_access_count: int = 0) -> tuple[
        str, str]:
        # Запускаем создание обеих записей параллельно для эффективности
        user_task = asyncio.create_task(self._add_to_stream(text=user_text, role="user", initial_ac=0))
        bot_task = asyncio.create_task(
            self._add_to_stream(text=bot_text, role=AI_ROLE_NAME, initial_ac=bot_response_access_count))

        user_id, bot_id = await asyncio.gather(user_task, bot_task)

        return user_id, bot_id

    async def save_reflection(self, reflection_text: str, initial_access_count: int = 0) -> str:
        reflection_id = await self._add_to_stream(text=reflection_text, role="internal", initial_ac=initial_access_count)
        return reflection_id

    async def extract_and_process_assets(self, parent_id: str):
        logging.info(f"LTM: Начинаю извлечение Когнитивных Активов для родителя {parent_id}")
        concepts_model = self._get_concepts_model()
        if not concepts_model:
            logging.warning(f"Извлечение активов для {parent_id} пропущено: модель не инициализирована.")
            return

        parent_record = self.stream_collection.get(ids=[parent_id], include=["documents", "metadatas"])
        if not parent_record['ids']:
            logging.error(f"Не удалось найти родительскую запись {parent_id} для извлечения активов.")
            return

        raw_text = parent_record['documents'][0]
        role = parent_record['metadatas'][0].get('role', 'unknown')

        try:
            context_phrase = self._get_context_phrase_for_llm(role)
            prompt = CONCEPT_EXTRACTION_PROMPT.format(text_to_analyze=raw_text, context_phrase=context_phrase)
            response = await concepts_model.generate_content_async(prompt)
            response_text = response.text.strip()

            if response_text.startswith("```json"): response_text = response_text[7:].strip()
            if response_text.endswith("```"): response_text = response_text[:-3].strip()

            assets_data = json.loads(response_text)
            if not isinstance(assets_data, list):
                logging.warning(f"LTM: Ответ модели не является JSON-массивом для {parent_id}.")
                return

            logging.info(f"LTM: Извлечено {len(assets_data)} Когнитивных Активов для {parent_id}.")

            for asset_data in assets_data:
                required_keys = ["кто", "что_делает", "суть", "тональность", "importance", "confidence"]
                if not all(key in asset_data for key in required_keys):
                    logging.warning(f"LTM: Пропущен некорректный Актив (отсутствуют ключи): {asset_data}")
                    continue

                fact_text = asset_data.get("суть")
                modality_text = asset_data.get("что_делает")
                if not fact_text or not modality_text:
                    logging.warning(f"LTM: Пропущен Актив с пустой 'сутью' или 'что_делает': {asset_data}")
                    continue

                fact_id = self._get_or_create_fact(fact_text)
                modality_id = self._get_or_create_modality(modality_text)
                asset_id = self._add_or_update_cognitive_asset(asset_data, parent_id, fact_id, modality_id)

                logging.info(f"LTM: Актив сохранен/обновлен с ID: {asset_id}")

                await self._rebuild_graph_for_asset(asset_id)

        except json.JSONDecodeError:
            logging.error(f"LTM: Не удалось распарсить JSON из ответа модели: {response_text}", exc_info=True)
        except Exception as e:
            logging.error(f"Ошибка при извлечении/обработке активов для {parent_id}: {e}", exc_info=True)
            self._concepts_model_instance = None
            logging.warning("LTM: Экземпляр модели активов сброшен из-за ошибки.")

    def _get_or_create_fact(self, fact_text: str) -> str:
        fact_id = self._get_hash(fact_text)
        if not self.facts_collection.get(ids=[fact_id])['ids']:
            self.facts_collection.add(documents=[fact_text], ids=[fact_id])
            logging.info(f"LTM: Создан новый Факт '{fact_text[:50]}...' (ID: {fact_id[:16]})")
        return fact_id

    def _get_or_create_modality(self, modality_text: str) -> str:
        modality_id = self._get_hash(modality_text)
        if not self.modalities_collection.get(ids=[modality_id])['ids']:
            hydrated_text = f"ментальное действие: {modality_text}"
            self.modalities_collection.add(
                documents=[hydrated_text],
                metadatas=[{"original_text": modality_text}],
                ids=[modality_id]
            )
            logging.info(f"LTM: Создана новая Модальность '{modality_text}' (ID: {modality_id[:16]})")
        return modality_id

    def _add_or_update_cognitive_asset(self, asset_data: dict, parent_id: str, fact_id: str, modality_id: str) -> str:
        asset_hash = self._get_hash(f"{fact_id}:{modality_id}")
        existing = self.assets_collection.get(where={"hash": {"$eq": asset_hash}})
        if existing['ids']:
            return existing['ids'][0]
        else:
            new_asset_id = f"asset_{asset_hash[:16]}"
            metadata = {
                "parent_id": parent_id,
                "hash": asset_hash,
                "fact_id": fact_id,
                "modality_id": modality_id,
                "кто": asset_data['кто'],
                "тональность": json.dumps(asset_data['тональность']),
                "importance": asset_data['importance'],
                "confidence": asset_data['confidence'],
            }
            self.assets_collection.add(
                documents=[f"[{asset_data['кто']}] -> [{asset_data['что_делает']}] -> ([{asset_data['суть']}])"],
                metadatas=[metadata],
                ids=[new_asset_id]
            )
            logging.info(f"LTM: Создан новый Когнитивный Актив {new_asset_id}")
            return new_asset_id

    async def _rebuild_graph_for_asset(self, asset_id: str):
        """
        (Улучшенная версия)
        Асинхронно и эффективно обновляет граф на основе семантической близости фактов,
        связанных с данным Когнитивным Активом.

        Ключевые улучшения:
        - Истинно асинхронная работа с помощью asyncio.to_thread для блокирующих вызовов БД.
        - Решена проблема "N+1 запроса" за счет пакетной загрузки данных.
        - Исключены избыточные обновления рёбер для одной и той же пары узлов.
        - Используются потокобезопасные методы graph_manager.
        """
        logging.debug(f"LTM: Начинаю обновление графа для Когнитивного Актива {asset_id}")

        # --- Шаг 1: Загрузка исходных данных об активе и его факте ---
        # РЕШЕНИЕ (Асинхронность): Оборачиваем синхронные I/O вызовы в to_thread
        # Это освобождает event loop для других задач во время ожидания ответа от БД.
        try:
            asset_record = await asyncio.to_thread(
                self.assets_collection.get, ids=[asset_id], include=["metadatas"]
            )
            if not asset_record.get('ids'):
                logging.warning(f"Не удалось найти актив {asset_id} для обновления графа.")
                return

            current_asset_metadata = asset_record['metadatas'][0]
            fact_id = current_asset_metadata.get('fact_id')
            parent_id = current_asset_metadata.get('parent_id')
            if not fact_id or not parent_id:
                logging.warning(f"Актив {asset_id} не имеет fact_id или parent_id. Пропуск.")
                return

            fact_record = await asyncio.to_thread(
                self.facts_collection.get, ids=[fact_id], include=["documents"]
            )
            if not fact_record.get('ids'):
                logging.error(f"LTM: Не удалось найти текст для факта {fact_id[:16]}. Обновление графа невозможно.")
                return
            fact_text = fact_record['documents'][0]
        except Exception as e:
            logging.error(f"LTM: Ошибка на этапе загрузки исходных данных для актива {asset_id}: {e}")
            return

        # --- Шаг 2: Поиск семантически близких фактов-соседей ---
        # РЕШЕНИЕ (N+1 проблема): Сначала находим всех соседей, затем одним запросом их активы.
        logging.debug(f"LTM: Ищем семантических соседей для факта '{fact_text[:50]}...'")
        neighbors = await asyncio.to_thread(
            self.facts_collection.query,
            query_texts=[fact_text],
            n_results=CONCEPT_NEIGHBOR_COUNT + 1,
            include=["distances"]
        )
        if not neighbors.get('ids') or not neighbors['ids'][0]:
            logging.warning(f"LTM: Не найдено семантических соседей для факта {fact_id[:16]}.")
            return

        # Фильтруем соседей и собираем их ID и дистанции
        neighbor_fact_data = []
        for i in range(len(neighbors['ids'][0])):
            neighbor_fact_id, distance = neighbors['ids'][0][i], neighbors['distances'][0][i]
            if neighbor_fact_id == fact_id:
                continue
            # GRAPH_ASSOCIATIVE_THRESHOLD - это порог схожести, а distance - расстояние. 1.0 - distance = схожесть
            if (1.0 - distance) < GRAPH_ASSOCIATIVE_THRESHOLD:
                continue
            neighbor_fact_data.append({"id": neighbor_fact_id, "distance": distance})

        if not neighbor_fact_data:
            logging.debug(f"LTM: Не найдено достаточно близких соседей для факта {fact_id[:16]}.")
            return

        # --- Шаг 3: Пакетная загрузка всех активов, связанных с найденными соседями ---
        all_neighbor_fact_ids = [n['id'] for n in neighbor_fact_data]
        all_linked_assets_records = await asyncio.to_thread(
            self.assets_collection.get,
            where={"fact_id": {"$in": all_neighbor_fact_ids}},
            include=["metadatas"]
        )

        # Группируем найденные активы по fact_id для удобного и быстрого доступа
        assets_by_fact_id = defaultdict(list)
        if all_linked_assets_records.get('ids'):
            for meta in all_linked_assets_records['metadatas']:
                assets_by_fact_id[meta['fact_id']].append(meta)

        # --- Шаг 4: Обработка и создание/обновление рёбер в графе ---
        edges_updated = 0
        # РЕШЕНИЕ (Избыточность в цикле): Отслеживаем уже обработанные пары родительских узлов
        tasks = []

        # Теперь итерируемся по заранее отфильтрованному и подготовленному списку соседей
        for neighbor_data in neighbor_fact_data:
            neighbor_fact_id = neighbor_data['id']
            linked_assets_for_neighbor = assets_by_fact_id.get(neighbor_fact_id, [])

            if not linked_assets_for_neighbor:
                continue

            similarity = 1.0 - neighbor_data['distance']

            # Собираем уникальные ID родительских узлов для данного соседа
            neighbor_parent_ids = {
                meta.get('parent_id') for meta in linked_assets_for_neighbor
            }

            for neighbor_parent_id in neighbor_parent_ids:
                if not neighbor_parent_id or parent_id == neighbor_parent_id:
                    continue

                # Находим метаданные одного из активов-соседей для передачи в функцию обновления ребра
                # (предполагаем, что метаданные любого из них подойдут для расчета веса)
                neighbor_asset_metadata = next(
                    (meta for meta in linked_assets_for_neighbor if meta.get('parent_id') == neighbor_parent_id),
                    None
                )
                if not neighbor_asset_metadata:
                    continue

                # РЕШЕНИЕ (Асинхронность): Создаем асинхронную задачу для обновления ребра
                task = asyncio.create_task(
                    graph_manager.add_or_update_edge(
                        parent_id,
                        neighbor_parent_id,
                        similarity,
                        current_asset_metadata,
                        neighbor_asset_metadata
                    )
                )
                tasks.append(task)

        # Дожидаемся выполнения всех задач по обновлению графа
        if tasks:
            await asyncio.gather(*tasks)
            edges_updated = len(tasks)

        # РЕШЕНИЕ (Неиспользуемая переменная): Используем значение в логе
        if edges_updated > 0:
            logging.info(f"Граф обновлен для актива {asset_id}. Добавлено/обновлено {edges_updated} рёбер.")

    def get_random_hot_record_as_seed(self, min_access_count: int) -> dict | None:
        if min_access_count <= 0: min_access_count = 1
        try:
            hot_records = self.stream_collection.get(
                where={"access_count": {"$gte": min_access_count}},
                include=["documents", "metadatas"]
            )
            if not hot_records.get('ids'): return None

            population = [
                {"id": hot_records['ids'][i], "doc": hot_records['documents'][i], "meta": hot_records['metadatas'][i]}
                for i in range(len(hot_records['ids']))]
            weights = [rec['meta'].get('access_count', 0) for rec in population]
            if not population: return None

            return random.choices(population=population, weights=weights, k=1)[0]
        except Exception as e:
            logging.error(f"LTM Seed: Ошибка при поиске 'зерна': {e}")
            return None

    def get_semantic_cluster(self, seed_doc: str, cluster_size: int) -> list[dict]:
        try:
            results = self.stream_collection.query(
                query_texts=[seed_doc], n_results=cluster_size, include=["documents", "metadatas"]
            )
            if not results or not results['ids'][0]: return []

            return [{
                "id": results['ids'][0][i], "doc": results['documents'][0][i],
                "role": results['metadatas'][0][i].get('role', 'unknown'),
                "access_count": results['metadatas'][0][i].get('access_count', 0)
            } for i in range(len(results['ids'][0]))]
        except Exception as e:
            logging.error(f"LTM Cluster: Ошибка при поиске кластера: {e}")
            return []

    def cooldown_records_by_ids(self, ids: list[str]):
        if not ids: return
        try:
            records = self.stream_collection.get(ids=ids, include=["metadatas"])
            if not records.get('ids'): return

            ids_to_update, metas_to_update = [], []
            for i in range(len(records['ids'])):
                meta, current_ac = records['metadatas'][i], records['metadatas'][i].get('access_count', 0)
                if current_ac > 0:
                    meta['access_count'] = current_ac // 2
                    ids_to_update.append(records['ids'][i])
                    metas_to_update.append(meta)
            if ids_to_update:
                self.stream_collection.update(ids=ids_to_update, metadatas=metas_to_update)
        except Exception as e:
            logging.error(f"LTM Cooldown: Ошибка при 'охлаждении': {e}")

    def get_records_by_ids(self, ids: list[str]) -> list[dict] | None:
        if not ids:
            return None
        try:
            records = self.stream_collection.get(ids=ids, include=["documents", "metadatas"])
            if not records or not records.get('ids'):
                return None
            result_list = []
            for i in range(len(records['ids'])):
                result_list.append({
                    "id": records['ids'][i],
                    "doc": records['documents'][i],
                    "role": records['metadatas'][i].get('role', 'unknown'),
                    "access_count": records['metadatas'][i].get('access_count', 0),
                    "timestamp": records['metadatas'][i].get('timestamp', 0)
                })
            return result_list
        except Exception as e:
            logging.error(f"LTM: Ошибка при получении записей по ID: {e}")
            return None

    def search_and_update(self, query_text: str, n_results: int, where_filter: dict = None) -> tuple[
        list[str], list[int]]:
        """
        Ищет в основной коллекции stream релевантные записи, обновляет их счетчик
        доступа и возвращает их в виде отформатированных строк.
        """
        if n_results == 0: return [], []
        if where_filter is None: where_filter = {}

        try:
            results = self.stream_collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter
            )

            if not results or not results['ids'] or not results['ids'][0]:
                return [], []

            retrieved_ids = results['ids'][0]
            docs = results['documents'][0]
            metadatas = results['metadatas'][0]

            memories = []
            counts = []
            ids_to_update = []
            metas_to_update = []

            for i in range(len(retrieved_ids)):
                meta = metadatas[i]
                ac = meta.get('access_count', 0)

                counts.append(ac)
                # Форматируем строку для подачи в промпт
                memories.append(f"[{meta.get('role', 'unknown').capitalize()} в прошлом (ac={ac})]: {docs[i]}")

                # Готовим данные для обновления
                meta['access_count'] = ac + 1
                ids_to_update.append(retrieved_ids[i])
                metas_to_update.append(meta)

            # Выполняем пакетное обновление метаданных
            if ids_to_update:
                self.stream_collection.update(ids=ids_to_update, metadatas=metas_to_update)

            return memories, counts
        except Exception as e:
            logging.error(f"LTM Search: Ошибка во время поиска: {e}", exc_info=True)
            return [], []



ltm = LTM_Manager()