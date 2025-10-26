# memory_api_server.py
# Сервер FastAPI для отдачи "воспоминаний" по ID узла

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Безопасный импорт LTM с обработкой всех возможных ошибок
ltm = None
ltm_error = None

try:
    from ltm import ltm as ltm_instance

    ltm = ltm_instance
    print("✅ LTM успешно импортирован")
except ImportError as e:
    ltm_error = f"ImportError: {e}"
    print(f"⚠️  Предупреждение: Не удалось импортировать ltm модуль: {e}")
except TypeError as e:
    ltm_error = f"TypeError при инициализации LTM: {e}"
    print(f"⚠️  Предупреждение: Ошибка инициализации LTM: {e}")
    print("💡 Похоже на проблему с версией google-generativeai библиотеки")
except Exception as e:
    ltm_error = f"Общая ошибка: {e}"
    print(f"⚠️  Предупреждение: Неожиданная ошибка при загрузке LTM: {e}")

print(f"🔍 Статус LTM: {'Доступен' if ltm else 'Недоступен'}")

app = FastAPI(title="Memory API", description="API для получения данных узлов графа")

# Разрешаем CORS для локального просмотра HTML
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Memory API Server запущен успешно"}


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "ltm_available": ltm is not None,
        "ltm_error": ltm_error if ltm is None else None
    }


@app.get("/memory/{node_id}")
async def get_memory(node_id: str):
    if ltm is None:
        raise HTTPException(status_code=503, detail="LTM модуль недоступен")

    try:
        # Получаем данные из коллекции
        result = ltm.stream_collection.get(
            ids=[node_id],
            include=["documents", "metadatas"]
        )

        if not result["ids"] or len(result["ids"]) == 0:
            raise HTTPException(status_code=404, detail=f"Узел {node_id} не найден")

        # Извлекаем данные
        doc = result["documents"][0] if result["documents"] else "Нет документа"
        meta = result["metadatas"][0] if result["metadatas"] else {}

        role = meta.get("role", "unknown").capitalize()
        access_count = meta.get("access_count", 0)

        # Формируем HTML-ответ
        html_content = f"""
        <div style="font-family: Arial, sans-serif;">
            <h3 style="color: #333; margin-top: 0;">Узел: {node_id}</h3>
            <p><strong>Роль:</strong> {role}</p>
            <p><strong>Количество обращений:</strong> {access_count}</p>
            <hr style="margin: 15px 0;">
            <div style="background: #f5f5f5; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto;">
                <strong>Содержимое:</strong><br>
                {doc}
            </div>
        </div>
        """

        return HTMLResponse(content=html_content)

    except Exception as e:
        print(f"Ошибка при получении данных узла {node_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    print("🚀 Запуск Memory API Server...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")