# graph_fallback_server.py
# Альтернативный сервер, который читает данные напрямую из графа

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import pickle
import networkx as nx
import sys
import os

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Пытаемся импортировать конфиг
try:
    from config import GRAPH_FILE_PATH, AI_ROLE_NAME
except ImportError:
    print("⚠️  Не найден config.py, использую значения по умолчанию")
    GRAPH_FILE_PATH = "graph.pkl"
    AI_ROLE_NAME = "assistant"

app = FastAPI(title="Graph Memory API", description="API для получения данных узлов из NetworkX графа")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальная переменная для графа
graph = None
graph_error = None


def load_graph():
    """Загрузка графа при старте сервера"""
    global graph, graph_error
    try:
        if not os.path.exists(GRAPH_FILE_PATH):
            graph_error = f"Файл графа не найден: {GRAPH_FILE_PATH}"
            print(f"❌ {graph_error}")
            return False

        with open(GRAPH_FILE_PATH, 'rb') as f:
            graph = pickle.load(f)

        print(f"✅ Граф загружен: {graph.number_of_nodes()} узлов, {graph.number_of_edges()} рёбер")
        return True

    except Exception as e:
        graph_error = f"Ошибка загрузки графа: {str(e)}"
        print(f"❌ {graph_error}")
        return False


# Загружаем граф при запуске
load_graph()


@app.get("/")
async def root():
    return {
        "message": "Graph Memory API Server",
        "graph_loaded": graph is not None,
        "nodes": graph.number_of_nodes() if graph else 0,
        "edges": graph.number_of_edges() if graph else 0
    }


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "graph_available": graph is not None,
        "graph_error": graph_error,
        "graph_file": GRAPH_FILE_PATH
    }


@app.get("/reload")
async def reload_graph():
    """Перезагрузка графа"""
    success = load_graph()
    return {
        "success": success,
        "graph_available": graph is not None,
        "error": graph_error
    }


@app.get("/nodes")
async def list_nodes():
    """Список всех узлов"""
    if graph is None:
        raise HTTPException(status_code=503, detail="Граф недоступен")

    nodes_info = []
    for node_id, attrs in graph.nodes(data=True):
        nodes_info.append({
            "id": node_id,
            "role": attrs.get('role', 'unknown'),
            "attributes": attrs
        })

    return {"nodes": nodes_info, "count": len(nodes_info)}


@app.get("/memory/{node_id}")
async def get_memory(node_id: str):
    if graph is None:
        raise HTTPException(status_code=503, detail=f"Граф недоступен: {graph_error}")

    try:
        # Проверяем, существует ли узел
        if node_id not in graph.nodes():
            raise HTTPException(status_code=404, detail=f"Узел {node_id} не найден в графе")

        # Получаем атрибуты узла
        attrs = graph.nodes[node_id]
        role = attrs.get('role', 'unknown')

        # Получаем соседей
        neighbors = list(graph.neighbors(node_id))

        # Получаем рёбра
        edges_info = []
        for neighbor in neighbors:
            edge_data = graph.get_edge_data(node_id, neighbor, {})
            edges_info.append({
                "to": neighbor,
                "type": edge_data.get('type', 'unknown'),
                "weight": edge_data.get('cumulative_weight', 1.0)
            })

        # Пытаемся найти текстовое содержимое в атрибутах
        content = attrs.get('content', attrs.get('text', attrs.get('document', 'Содержимое не найдено')))

        # Формируем HTML-ответ
        html_content = f"""
        <div style="font-family: Arial, sans-serif;">
            <h3 style="color: #333; margin-top: 0;">Узел: {node_id}</h3>
            <p><strong>Роль:</strong> <span style="color: {'#5CB85C' if role == 'user' else '#D9534F' if role == AI_ROLE_NAME else '#5BC0DE'};">{role.capitalize()}</span></p>
            <p><strong>Соседей:</strong> {len(neighbors)}</p>

            <hr style="margin: 15px 0;">

            <h4>Содержимое:</h4>
            <div style="background: #f5f5f5; padding: 10px; border-radius: 5px; max-height: 300px; overflow-y: auto; border-left: 4px solid #ddd;">
                {content}
            </div>

            <hr style="margin: 15px 0;">

            <h4>Все атрибуты:</h4>
            <div style="background: #f9f9f9; padding: 10px; border-radius: 5px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px;">
                {format_attributes(attrs)}
            </div>

            {f'''
            <hr style="margin: 15px 0;">
            <h4>Связи ({len(edges_info)}):</h4>
            <div style="max-height: 150px; overflow-y: auto;">
                {''.join([f"<div style='margin: 5px 0; padding: 5px; background: #f0f0f0; border-radius: 3px;'><strong>{edge['to']}</strong> ({edge['type']}) - вес: {edge['weight']:.2f}</div>" for edge in edges_info[:10]])}
                {f"<div style='color: #666; font-style: italic;'>... и ещё {len(edges_info) - 10}</div>" if len(edges_info) > 10 else ""}
            </div>
            ''' if edges_info else ''}
        </div>
        """

        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка при получении данных узла {node_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


def format_attributes(attrs):
    """Форматирование атрибутов для отображения"""
    if not attrs:
        return "Нет атрибутов"

    formatted = []
    for key, value in attrs.items():
        if isinstance(value, str) and len(value) > 100:
            value = value[:100] + "..."
        formatted.append(f"<strong>{key}:</strong> {value}")

    return "<br>".join(formatted)


if __name__ == "__main__":
    import uvicorn

    print("🚀 Запуск Graph Memory API Server...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")