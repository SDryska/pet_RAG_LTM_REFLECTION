# Digital Genesis: Telegram Bot с векторной памятью и системой рефлексии

Telegram-бот на базе Google Gemini AI с реализацией долгосрочной памяти, семантического поиска и автоматических циклов рефлексии.

## Описание проекта

Система реализует Telegram-бот со следующим функционалом:
- Векторная долгосрочная память (ChromaDB) с семантической индексацией
- Извлечение когнитивных активов: разложение текста на атомарные единицы знания
- Автоматические циклы рефлексии с анализом кластеров памяти для генерации новых инсайтов
- Построение графа знаний с взвешиванием узлов по PageRank
- Контекстно-зависимая генерация ответов на основе извлечённой памяти

## Архитектура

### Основные компоненты

```
digital_genesis/
├── main.py                 # Telegram-бот с обработчиками сообщений и планировщиком рефлексии
├── config.py              # Конфигурация, API ключи, системные промпты
├── ltm.py                 # Абстракция долгосрочной памяти поверх ChromaDB
├── graph_manager.py       # Построение графа и анализ
├── scripts/               # Утилиты для инспекции и обслуживания
│   ├── db_inspector.py
│   ├── concepts_analyze.py
│   ├── memory_cleaner.py
│   └── ...
├── db/                    # Хранилище ChromaDB
├── logs/                  # Логирование (pickle формат)
└── export/                # CSV экспорты коллекций
```

### Ключевые модули

| Модуль | Назначение |
|--------|-----------|
| `main.py` | Обработчики сообщений, управление циклом рефлексии, обработка ошибок |
| `config.py` | API credentials, параметры LLM, шаблоны промптов |
| `ltm.py` | Управление коллекциями ChromaDB, семантический поиск, персистентность памяти |
| `graph_manager.py` | Построение графа, вычисление PageRank, механизмы затухания |

## Технологический стек

- **aiogram 3.x**: асинхронный wrapper для Telegram Bot API
- **google-generativeai**: интеграция с Gemini API
- **chromadb**: векторная БД для семантического поиска
- **apscheduler**: планировщик фоновых задач
- **networkx**: алгоритмы работы с графами
- **python-dotenv**: управление переменными окружения

## Установка и запуск

### Требования

- Python 3.10+
- Telegram Bot API токен
- Google Gemini API credentials

### Шаги установки

1. Клонирование репозитория:
```bash
git clone https://github.com/yourusername/digital_genesis.git
cd digital_genesis
```

2. Создание виртуального окружения:
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

3. Установка зависимостей:
```bash
pip install -r requirements.txt
```

4. Конфигурация переменных окружения в `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_api_key
GEMINI_CONCEPTS_API_KEY_2=your_concepts_key
```

5. Запуск бота:
```bash
python main.py
```

## Конфигурация системы

Критичные параметры в `config.py`:

### Конфигурация LLM
```python
GEMINI_MODEL_NAME = 'gemini-2.5-flash'          # Основная модель
GEMINI_CONCEPTS_MODEL_NAME = 'gemini-2.0-flash' # Модель анализа
```

### Параметры памяти
```python
DIALOGUE_SEARCH_RESULT_COUNT = 5      # Окно контекста диалогов
THOUGHT_SEARCH_RESULT_COUNT = 2       # Окно контекста внутренних мыслей
CHROMA_DB_PATH = "db"                 # Путь к БД
```

### Система рефлексии
```python
REFLECTION_INTERVAL_SECONDS = 300     # Частота цикла (5 минут)
REFLECTION_MIN_ACCESS_COUNT = 2       # Порог активации
REFLECTION_CLUSTER_SIZE = 5           # Размер семантического кластера
```

### Граф знаний
```python
GRAPH_DECAY_FACTOR = 0.995            # Затухание веса рёбер за цикл
GRAPH_DECAY_THRESHOLD = 0.01          # Минимальный порог веса
GRAPH_SAVE_INTERVAL_SECONDS = 600     # Интервал сохранения
```

## Система памяти

### ChromaDB коллекции

1. **stream** - история диалогов (сообщения пользователя/бота)
2. **cognitive_assets** - извлечённые единицы знаний из текста
3. **facts** - фактическая информация
4. **modalities** - метаданные о типе информации

### Структура записей памяти

Каждая запись содержит:
- `id`: UUID идентификатор
- `doc`: текстовое содержание
- `role`: источник (user/FOFE/internal)
- `access_count`: счётчик обращений к записи
- `timestamp`: временная метка создания/обновления

## Извлечение когнитивных активов

Текст разлагается на структурированные когнитивные активы:

```json
{
  "кто": "я",                        // Агент (я или пользователь)
  "что_делает": "считает",           // Глагол ментального действия
  "суть": "основное утверждение",    // Ядро высказывания
  "тональность": ["уверенная"],      // Эмоциональные маркеры
  "importance": 8,                   // Оценка релевантности (1-10)
  "confidence": 9                    // Уверенность извлечения (1-10)
}
```

## Цикл рефлексии

Автоматический процесс, выполняющийся с интервалом `REFLECTION_INTERVAL_SECONDS`:

1. **Выбор зерна**: случайная высокочастотная запись (access_count > REFLECTION_MIN_ACCESS_COUNT)
2. **Кластеризация**: семантический поиск соседей (k=REFLECTION_CLUSTER_SIZE)
3. **Анализ**: отправка кластера в Gemini для синтеза
4. **Генерация**: новый инсайт сохраняется как внутренняя мысль
5. **Персистентность**: запись в коллекцию stream
6. **Затухание**: снижение access_count записей кластера

## Утилиты

Скрипты в директории `scripts/` для обслуживания и анализа системы:

```bash
# db_inspector.py - Перестроение графа из данных ChromaDB
python scripts/db_inspector.py

# concepts_analyze.py - Анализ коллекции когнитивных активов на предмет семантических дубликатов
python scripts/concepts_analyze.py

# force_reflection.py - Ручной запуск цикла рефлексии с параметрами
python scripts/force_reflection.py

# vizualize_graph.py - Визуализация графа знаний через интерактивное web-представление
python scripts/vizualize_graph.py

# memory_cleaner.py - Очистка памяти: удаление дубликатов и коротких сообщений
python scripts/memory_cleaner.py

# analyze_graph.py - Анализ структуры графа, вывод статистики и центральных узлов
python scripts/analyze_graph.py

# memory_hygiene_inspector.py - Проверка целостности и качества данных в памяти
python scripts/memory_hygiene_inspector.py

# memory_api_server.py - REST API сервер для доступа к памяти (legacy)
python scripts/memory_api_server.py

# graph_fallback_server.py - Резервный сервер для работы с графом (legacy)
python scripts/graph_fallback_server.py

# great_migration.py - Утилита для миграции данных между версиями (legacy)
python scripts/great_migration.py
```

**Примечание**: скрипты в директории `scripts/` — это legacy код. Они могут требовать установки дополнительных зависимостей, не указанных в `requirements.txt`, или адаптации под текущую версию кода.

## Логирование

Три потока логирования:

- **ThoughtProcess**: общие логи приложения (stdout)
- **Reflections**: логи генерации инсайтов (logs/reflections.log)
- **Concepts**: логи извлечения активов (stdout)

## Важные замечания

1. **Credentials**: файл `.env` должен содержать валидные API ключи; никогда не коммитить в версионный контроль
2. **База данных**: директория ChromaDB создаётся автоматически при первом запуске
3. **Хранилище**: персистентные данные в директориях `db/`, `logs/`, и `export/`
4. **Расходы API**: мониторить использование Gemini API; настроить лимиты если необходимо
5. **Рост памяти**: затухание access_count может потребовать периодического обслуживания

## Аспекты безопасности

- API ключи управляются исключительно через переменные окружения
- `.env` исключён через `.gitignore`
- Фильтры безопасности Gemini конфигурируются через `SAFETY_SETTINGS`
- Отсутствует валидация входных данных для защиты от malicious prompts (использовать только с доверенными пользователями)
