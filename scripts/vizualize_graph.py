# vizualize_graph.py
# v2.7.1 - Исправлена ошибка SyntaxError с f-string

import pickle
import networkx as nx
from pyvis.network import Network
import logging
import os
import subprocess
import threading
import time
import json
import sys
import webbrowser
import math

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    from config import GRAPH_FILE_PATH, AI_ROLE_NAME
except ImportError:
    logging.warning("Не удалось импортировать config.py, используются значения по умолчанию")
    GRAPH_FILE_PATH = "logs/mind_graph.gpickle"
    AI_ROLE_NAME = "assistant"


def check_api_server():
    import requests
    try:
        response = requests.get("http://127.0.0.1:8000/health", timeout=1)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def run_memory_api():
    def target():
        logging.info("🚀 Попытка запуска API сервера (если еще не запущен)...")
        if check_api_server():
            logging.info("🔄 API сервер уже запущен")
            return

        try:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "memory_api_server:app", "--host", "127.0.0.1", "--port", "8000"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except FileNotFoundError:
            logging.error("❌ 'uvicorn' не найден. Установите его: pip install uvicorn[standard]")
        except Exception as e:
            logging.error(f"❌ Неожиданная ошибка при запуске сервера: {e}")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    for _ in range(10):
        if check_api_server():
            logging.info("✅ API сервер успешно запущен")
            return True
        time.sleep(1)

    logging.warning("⚠️  API сервер не отвечает, но продолжаем... Данные по клику на узлы будут недоступны.")
    return False


def load_graph():
    try:
        if not os.path.exists(GRAPH_FILE_PATH):
            logging.error(f"❌ Файл графа '{GRAPH_FILE_PATH}' не найден")
            return None

        with open(GRAPH_FILE_PATH, 'rb') as f:
            graph = pickle.load(f)
        logging.info(f"✅ Граф успешно загружен из '{GRAPH_FILE_PATH}'")
        return graph
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки графа: {e}")
        return None


# --- НОВЫЙ БЛОК: Подготовка данных для JS ---
def prepare_data_for_js(graph):
    """
    Преобразует данные графа в формат, удобный для JavaScript.
    Это позволяет выполнять всю фильтрацию на стороне клиента без перезагрузки.
    """
    nodes_data = []
    edges_data = []

    color_map = {'internal': '#5BC0DE', 'user': '#5CB85C', AI_ROLE_NAME: '#D9534F'}

    for node_id, attrs in graph.nodes(data=True):
        role = attrs.get('role', 'unknown')
        nodes_data.append({
            "id": node_id,
            "label": ' ',
            "color": color_map.get(role, '#808080'),
            "size": 10,
            "title": f"<b>ID:</b> {node_id}<br><b>Роль:</b> {role}",
            "role": role  # Добавляем чистое поле для фильтрации
        })

    min_weight, max_weight = (1.0, 1.0)
    if graph.number_of_edges() > 0:
        weights = [attrs.get('cumulative_weight', 1.0) for u, v, attrs in graph.edges(data=True)]
        min_weight = min(weights) if weights else 1.0
        max_weight = max(weights) if weights else 1.0

    for u, v, attrs in graph.edges(data=True):
        edge_type = attrs.get('type', 'unknown')
        weight = attrs.get('cumulative_weight', 1.0)
        width = max(0.5, min(weight * 0.2, 3.0))

        edges_data.append({
            "from": u,
            "to": v,
            "color": 'rgba(0,0,0,0.3)' if edge_type == 'structural' else 'rgba(100,100,100,0.3)',
            "width": width,
            "dashes": edge_type == 'associative',
            "title": f"<b>Тип:</b> {edge_type}<br><b>Вес:</b> {weight:.2f}",
            "type": edge_type,  # Чистое поле для фильтрации
            "weight": weight  # Чистое поле для фильтрации
        })

    # Округляем веса для слайдера
    min_weight_rounded = math.floor(min_weight * 10) / 10
    max_weight_rounded = math.ceil(max_weight * 10) / 10

    return nodes_data, edges_data, min_weight_rounded, max_weight_rounded


# --- КОНЕЦ НОВОГО БЛОКА ---


def create_pyvis_network(nodes_data, edges_data):
    """Создает сеть pyvis из подготовленных данных."""
    net = Network(
        height='95vh',
        width='100%',
        notebook=False,
        cdn_resources='in_line',
        bgcolor='#ffffff',
        font_color='#000000'
    )

    if not nodes_data:
        # Если нет узлов, ничего не делаем
        return net

    # Извлекаем список ID узлов для первого аргумента
    node_ids = [d['id'] for d in nodes_data]

    # Создаем словарь свойств для именованных аргументов,
    # ИСКЛЮЧАЯ 'id' и наш кастомный атрибут 'role'
    node_properties = {
        k: [d[k] for d in nodes_data]
        for k in nodes_data[0]
        if k not in ['id', 'role']  # <--- ИЗМЕНЕНИЕ ЗДЕСЬ
    }

    net.add_nodes(node_ids, **node_properties)

    for edge in edges_data:
        net.add_edge(edge['from'], edge['to'],
                     color=edge['color'], width=edge['width'],
                     dashes=edge['dashes'], title=edge['title'])

    return net


def configure_physics(net):
    physics_config = {
        "edges": {"smooth": {"type": "continuous", "roundness": 0.2}},
        "physics": {
            "enabled": True,
            "solver": "barnesHut",
            "barnesHut": {
                "gravitationalConstant": -8000, "centralGravity": 0.1, "springLength": 200,
                "springConstant": 0.04, "damping": 0.95, "avoidOverlap": 0.2
            },
            "stabilization": {"enabled": True, "iterations": 1000, "updateInterval": 25, "fit": True},
            "timestep": 0.5, "adaptiveTimestep": True, "maxVelocity": 30, "minVelocity": 0.1
        },
        "interaction": {"hover": True, "selectConnectedEdges": False, "dragNodes": True, "dragView": True,
                        "zoomView": True}
    }
    net.set_options(json.dumps(physics_config))


# --- ОБНОВЛЕННЫЙ И ИСПРАВЛЕННЫЙ БЛОК: Добавление JS с фильтрацией изолированных узлов ---
def add_custom_js(html_content, all_nodes_json, all_edges_json, min_weight, max_weight):
    # Добавлен чекбокс и логика для скрытия изолированных узлов
    custom_js = f"""<style>
#memory-panel{{position:fixed;top:10px;right:10px;width:35%;height:90vh;overflow:auto;border:2px solid #ddd;border-radius:8px;padding:15px;background:#fff;font-family:'Segoe UI',Arial,sans-serif;font-size:14px;z-index:1000;box-shadow:0 4px 6px rgba(0,0,0,.1)}}
#memory-panel h3{{margin-top:0;color:#333;border-bottom:2px solid #eee;padding-bottom:10px}}
.loading{{text-align:center;color:#666;font-style:italic}}
.error{{color:#d9534f;background:#f2dede;padding:10px;border-radius:4px;border:1px solid #ebccd1}}
#controls-container{{position:fixed;bottom:10px;left:10px;z-index:1000;display:flex;flex-direction:column;gap:10px;}}
.control-panel{{background:rgba(255,255,255,0.9);padding:10px;border-radius:8px;border:1px solid #ddd;font-family:'Segoe UI',Arial,sans-serif;font-size:12px;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
.control-panel h4{{margin:0 0 8px 0;font-size:13px;border-bottom:1px solid #eee;padding-bottom:5px}}
.control-panel button{{margin:2px;padding:5px 10px;border:1px solid #ccc;border-radius:4px;background:#f8f9fa;cursor:pointer;font-size:11px}}
.control-panel button:hover{{background:#e9ecef}}
.control-panel button.active{{background:#007bff;color:white}}
.filter-group label{{display:inline-block;margin-right:10px;user-select:none;}}
#weight-slider-container label{{display:block;margin-bottom:5px;}}
</style>
<div id="memory-panel"><div class="loading">👆 Кликните на узел для просмотра данных</div></div>
<div id="controls-container">
    <div id="filter-controls" class="control-panel">
        <h4>Фильтрация</h4>
        <div class="filter-group">
            <strong>Роли узлов:</strong>
            <label><input type="checkbox" class="filter-cb" id="filter-role-user" checked> User</label>
            <label><input type="checkbox" class="filter-cb" id="filter-role-{AI_ROLE_NAME}" checked> Assistant</label>
            <label><input type="checkbox" class="filter-cb" id="filter-role-internal" checked> Internal</label>
        </div>
        <div class="filter-group" style="margin-top:8px;">
            <strong>Типы рёбер:</strong>
            <label><input type="checkbox" class="filter-cb" id="filter-type-structural" checked> Structural</label>
            <label><input type="checkbox" class="filter-cb" id="filter-type-associative" checked> Associative</label>
        </div>
        <div id="weight-slider-container" style="margin-top:8px;">
            <label for="filter-weight">Мин. вес ребра: <span id="weight-value">{min_weight:.2f}</span></label>
            <input type="range" id="filter-weight" min="{min_weight}" max="{max_weight}" value="{min_weight}" step="0.1" style="width:100%;">
        </div>
        <!-- НОВЫЙ ЧЕКБОКС -->
        <div class="filter-group" style="margin-top:8px; border-top: 1px solid #eee; padding-top: 8px;">
             <label><input type="checkbox" class="filter-cb" id="filter-hide-isolated"> Скрывать изолированные узлы</label>
        </div>
        <!-- КОНЕЦ НОВОГО ЧЕКБОКСА -->
        <div style="margin-top:10px; text-align:right;">
            <button id="apply-filters-btn">Применить</button>
            <button id="reset-filters-btn">Сбросить</button>
        </div>
    </div>
    <div id="physics-controls" class="control-panel">
        <h4>Управление физикой</h4>
        <button id="physics-toggle" class="active">🔄 Физика вкл</button>
        <button id="stabilize-btn">⚡ Стабилизировать</button>
        <button id="fit-btn">🎯 Показать все</button>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    const allNodes = {all_nodes_json};
    const allEdges = {all_edges_json};
    let currentNodeId = null;
    let physicsEnabled = true;

    // --- ОБНОВЛЕННАЯ Логика фильтрации ---
    function applyFilters() {{
        console.log("Applying filters...");
        const visibleRoles = {{
            'user': document.getElementById('filter-role-user').checked,
            '{AI_ROLE_NAME}': document.getElementById('filter-role-{AI_ROLE_NAME}').checked,
            'internal': document.getElementById('filter-role-internal').checked
        }};
        const visibleTypes = {{
            'structural': document.getElementById('filter-type-structural').checked,
            'associative': document.getElementById('filter-type-associative').checked
        }};
        const minWeight = parseFloat(document.getElementById('filter-weight').value);
        // НОВАЯ ЛОГИКА: Читаем состояние чекбокса
        const hideIsolated = document.getElementById('filter-hide-isolated').checked;

        // Шаг 1: Фильтруем узлы по ролям
        let preliminaryNodes = allNodes.filter(node => visibleRoles[node.role]);
        const preliminaryNodeIds = new Set(preliminaryNodes.map(n => n.id));

        // Шаг 2: Фильтруем рёбра по типу, весу и наличию узлов на обоих концах
        const filteredEdges = allEdges.filter(edge => 
            visibleTypes[edge.type] &&
            edge.weight >= minWeight &&
            preliminaryNodeIds.has(edge.from) &&
            preliminaryNodeIds.has(edge.to)
        );

        // НОВАЯ ЛОГИКА: Фильтруем узлы дальше, если нужно
        let finalNodes;
        if (hideIsolated) {{
            // Если чекбокс активен, нам нужны только те узлы, которые участвуют в отфильтрованных рёбрах
            const connectedNodeIds = new Set();
            filteredEdges.forEach(edge => {{
                connectedNodeIds.add(edge.from);
                connectedNodeIds.add(edge.to);
            }});
            finalNodes = preliminaryNodes.filter(node => connectedNodeIds.has(node.id));
        }} else {{
            // Иначе, просто используем узлы, отфильтрованные по ролям
            finalNodes = preliminaryNodes;
        }}

        // Обновляем данные в сети
        nodes.clear();
        edges.clear();
        nodes.add(finalNodes);
        edges.add(filteredEdges);

        console.log(`Граф обновлен: ${{finalNodes.length}} узлов, ${{filteredEdges.length}} рёбер`);
    }}

    document.getElementById('apply-filters-btn').addEventListener('click', applyFilters);

    document.getElementById('reset-filters-btn').addEventListener('click', function() {{
        document.querySelectorAll('.filter-cb').forEach(cb => cb.checked = cb.id !== 'filter-hide-isolated');
        document.getElementById('filter-hide-isolated').checked = false; // Сбрасываем и новый чекбокс

        const weightSlider = document.getElementById('filter-weight');
        weightSlider.value = weightSlider.min;
        document.getElementById('weight-value').textContent = parseFloat(weightSlider.min).toFixed(2);

        nodes.clear();
        edges.clear();
        nodes.add(allNodes);
        edges.add(allEdges);
        console.log("Фильтры сброшены. Показан полный граф.");
    }});

    document.getElementById('filter-weight').addEventListener('input', function() {{
        document.getElementById('weight-value').textContent = parseFloat(this.value).toFixed(2);
    }});

    // --- Логика управления физикой и кликами (без изменений) ---
    setTimeout(() => {{
        if (typeof network === 'undefined') {{
            console.error("Pyvis 'network' object not found!");
            return;
        }}

        network.on("stabilizationIterationsDone", function() {{
            setTimeout(() => {{
                network.setOptions({{ physics: {{ enabled: false }} }});
                physicsEnabled = false;
                const toggleBtn = document.getElementById("physics-toggle");
                toggleBtn.textContent = "🔄 Физика выкл";
                toggleBtn.classList.remove("active");
                console.log("🔒 Физика автоматически отключена после стабилизации");
            }}, 500);
        }});

        document.getElementById("physics-toggle").addEventListener("click", function() {{
            physicsEnabled = !physicsEnabled;
            network.setOptions({{ physics: {{ enabled: physicsEnabled }} }});
            this.textContent = physicsEnabled ? "🔄 Физика вкл" : "🔄 Физика выкл";
            this.classList.toggle("active", physicsEnabled);
            console.log(`🔧 Физика ${{physicsEnabled ? 'включена' : 'отключена'}} вручную`);
        }});

        document.getElementById("stabilize-btn").addEventListener("click", function() {{
            if (!physicsEnabled) {{
                network.setOptions({{ physics: {{ enabled: true }} }});
                physicsEnabled = true;
                const toggleBtn = document.getElementById("physics-toggle");
                toggleBtn.textContent = "🔄 Физика вкл";
                toggleBtn.classList.add("active");
            }}
            network.stabilize();
            console.log("⚡ Запущена стабилизация графа");
        }});

        document.getElementById("fit-btn").addEventListener("click", function() {{
            network.fit();
            console.log("🎯 Граф масштабирован для показа всех узлов");
        }});

        network.on("click", function(e) {{
            const panel = document.getElementById("memory-panel");
            if (e.nodes.length > 0) {{
                let nodeId = e.nodes[0];
                currentNodeId = nodeId;
                panel.innerHTML = '<div class="loading">⏳ Загрузка данных узла: ' + nodeId + '</div>';

                fetch(`http://127.0.0.1:8000/memory/${{nodeId}}`)
                    .then(response => {{
                        if (!response.ok) {{ throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`); }}
                        return response.text();
                    }})
                    .then(data => {{ if (currentNodeId === nodeId) {{ panel.innerHTML = data; }} }})
                    .catch(error => {{
                        console.error("Ошибка загрузки данных:", error);
                        if (currentNodeId === nodeId) {{
                            panel.innerHTML = `<div class="error"><strong>❌ Ошибка загрузки данных</strong><br>Узел: <code>${{nodeId}}</code><br>Ошибка: ${{error.message}}<br><br><small>Убедитесь, что API сервер запущен на порту 8000</small></div>`;
                        }}
                    }});
            }} else {{
                panel.innerHTML = '<div class="loading">👆 Кликните на узел для просмотра данных</div>';
                currentNodeId = null;
            }}
        }});

        network.on("hoverNode", function() {{ document.body.style.cursor = "pointer"; }});
        network.on("blurNode", function() {{ document.body.style.cursor = "default"; }});

        console.log("🎯 Улучшенный визуализатор графа готов к работе!");

    }}, 100);
}});
</script>"""

    if "</body>" in html_content:
        return html_content.replace("</body>", custom_js + "</body>")
    return html_content + custom_js


def visualize_interactive():
    logging.info("--- 🎨 Запуск интерактивного визуализатора графа ---")

    graph = load_graph()
    if graph is None:
        return False

    if graph.number_of_nodes() == 0:
        logging.warning("⚠️  Граф пуст. Визуализация невозможна.")
        return False

    logging.info(f"📊 Граф содержит {graph.number_of_nodes()} узлов и {graph.number_of_edges()} рёбер")

    nodes_data, edges_data, min_w, max_w = prepare_data_for_js(graph)

    net = create_pyvis_network(nodes_data, edges_data)

    configure_physics(net)

    html_path = "interactive_graph_visualization.html"
    html_content = net.generate_html()

    all_nodes_json = json.dumps(nodes_data)
    all_edges_json = json.dumps(edges_data)
    html_content = add_custom_js(html_content, all_nodes_json, all_edges_json, min_w, max_w)

    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        full_path = os.path.abspath(html_path)
        logging.info(f"✅ HTML файл сохранён: {full_path}")

        try:
            webbrowser.open(f"file://{full_path}")
            logging.info("🌐 Страница открыта в браузере")
        except Exception as e:
            logging.warning(f"⚠️  Не удалось открыть браузер: {e}")
            logging.info(f"Откройте вручную: file://{full_path}")

        return True

    except Exception as e:
        logging.error(f"❌ Ошибка сохранения HTML: {e}")
        return False


def main():
    logging.info("🚀 Запуск системы визуализации графа")
    api_started = run_memory_api()
    viz_created = visualize_interactive()

    if viz_created:
        logging.info("✅ Система успешно запущена!")
        logging.info("🔬 Используйте новую панель фильтров слева внизу для управления отображением графа.")
        if api_started:
            logging.info("💡 Кликайте на узлы для просмотра данных")
        else:
            logging.warning("⚠️  API сервер недоступен - данные узлов не будут загружаться")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("👋 Завершение работы...")
    else:
        logging.error("❌ Ошибка создания визуализации")


if __name__ == "__main__":
    main()