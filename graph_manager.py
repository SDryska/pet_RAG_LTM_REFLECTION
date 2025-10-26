# graph_manager.py
# Версия для архитектуры v3.0 "Когнитивные Активы"
# Улучшено: добавлена асинхронность и потокобезопасность для работы в asyncio-среде.

import networkx as nx
import os
import pickle
import logging
import asyncio
from config import GRAPH_STRUCTURAL_THRESHOLD

class GraphManager:
    """
    Класс для управления графом мыслей.
    Отвечает за загрузку, сохранение и модификацию графа.
    Эта версия потокобезопасна для использования в асинхронной среде.
    """
    def __init__(self, graph_path: str):
        """
        Инициализирует менеджер графа, загружает граф и создает блокировку
        для безопасного асинхронного доступа.
        """
        self.graph_path = graph_path
        self.graph = self._load_graph()
        self.lock = asyncio.Lock()  # Блокировка для обеспечения потокобезопасности
        logging.info(f"Graph Manager: Граф загружен из '{self.graph_path}'. "
                     f"Узлов: {self.graph.number_of_nodes()}, "
                     f"Рёбер: {self.graph.number_of_edges()}")

    def _load_graph(self) -> nx.Graph:
        """Загружает граф с диска или создает новый, если файл не найден."""
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logging.error(f"Graph Manager: Ошибка загрузки графа из {self.graph_path}: {e}. Создается новый граф.")
                return nx.Graph()
        else:
            logging.info(f"Graph Manager: Файл графа не найден по пути {self.graph_path}. Создается новый граф.")
            return nx.Graph()

    def save_graph(self):
        """
        Сохраняет текущее состояние графа на диск.
        Эта операция остается синхронной, так как pickle не имеет нативного async API.
        Ее следует вызывать с помощью `asyncio.to_thread` в асинхронном коде.
        """
        try:
            os.makedirs(os.path.dirname(self.graph_path), exist_ok=True)
            # При сохранении мы не используем lock, так как предполагается,
            # что эта операция будет вызываться редко (например, по таймеру),
            # а не одновременно с модификациями. Если нужна 100% гарантия,
            # можно сделать и этот метод асинхронным с lock.
            with open(self.graph_path, 'wb') as f:
                pickle.dump(self.graph, f, pickle.HIGHEST_PROTOCOL)
            logging.info(f"Graph Manager: Граф успешно сохранен в '{self.graph_path}'. "
                         f"Узлов: {self.graph.number_of_nodes()}, Рёбер: {self.graph.number_of_edges()}")
        except Exception as e:
            logging.error(f"Graph Manager: Не удалось сохранить граф: {e}")

    async def add_node_if_not_exists(self, node_id: str, **attrs):
        """
        (Асинхронно) Добавляет узел, если он еще не существует, и обновляет его атрибуты.
        """
        async with self.lock:
            if not self.graph.has_node(node_id):
                self.graph.add_node(node_id, **attrs)
            else:
                # Обновляем атрибуты, если узел уже существует
                nx.set_node_attributes(self.graph, {node_id: attrs})

    async def add_or_update_edge(self, node1_id: str, node2_id: str, similarity_score: float, asset1_meta: dict, asset2_meta: dict):
        """
        (Асинхронно и потокобезопасно) Добавляет или обновляет ребро,
        взвешивая его на основе семантической близости, важности (importance)
        и уверенности (confidence) породивших его Когнитивных Активов.
        """
        if node1_id == node2_id:
            return

        # Захватываем блокировку, чтобы безопасно изменять граф из разных корутин
        async with self.lock:
            # Извлекаем оценки из метаданных
            imp1 = asset1_meta.get('importance', 5)
            conf1 = asset1_meta.get('confidence', 5)
            imp2 = asset2_meta.get('importance', 5)
            conf2 = asset2_meta.get('confidence', 5)

            # Рассчитываем итоговый вес, где максимальное значение = similarity_score
            # Формула: близость * среднее_арифметическое(важность*уверенность / 100)
            # Делим на 100, т.к. imp и conf от 1 до 10, их произведение до 100.
            weight_modifier = ((imp1 * conf1) + (imp2 * conf2)) / 200.0
            final_weight = similarity_score * weight_modifier

            link_type = 'structural' if similarity_score > GRAPH_STRUCTURAL_THRESHOLD else 'associative'

            if self.graph.has_edge(node1_id, node2_id):
                edge = self.graph[node1_id][node2_id]
                # Добавляем новый, взвешенный вес к кумулятивному
                edge['cumulative_weight'] = edge.get('cumulative_weight', 0) + final_weight
                edge['shared_concepts_count'] = edge.get('shared_concepts_count', 0) + 1
                edge['max_similarity'] = max(edge.get('max_similarity', 0), similarity_score)
                # Если связь стала структурной, повышаем ее статус
                if link_type == 'structural' and edge.get('type') == 'associative':
                    edge['type'] = 'structural'
            else:
                self.graph.add_edge(
                    node1_id,
                    node2_id,
                    type=link_type,
                    max_similarity=similarity_score,
                    shared_concepts_count=1,
                    cumulative_weight=final_weight  # Начальный вес
                )


# --- Инициализация синглтона ---
from config import GRAPH_FILE_PATH

# Создаем единственный экземпляр менеджера, который будет использоваться во всем приложении
graph_manager = GraphManager(graph_path=GRAPH_FILE_PATH)