"""
Асинхронная работа с SQLite: пользователи, задачи, история выполнения.
"""
import time
from pathlib import Path

import aiosqlite

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "bot.db"


async def get_db() -> aiosqlite.Connection:
    """Создать подключение к БД."""
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Создать таблицы и заполнить начальными данными (если пусто)."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alice_care (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procedure TEXT NOT NULL UNIQUE,
                next_date INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alice_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                task_date TEXT NOT NULL,
                is_completed INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alice_task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                title TEXT NOT NULL,
                completed_by_name TEXT NOT NULL DEFAULT 'Неизвестный',
                completed_at TIMESTAMP NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recipe_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                ingredients TEXT NOT NULL,
                steps TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (category_id) REFERENCES recipe_categories(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS movie_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                torrent_id TEXT NOT NULL,
                magnet TEXT NOT NULL,
                qb_hash TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'movies',
                quality TEXT NOT NULL DEFAULT '',
                size_text TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'downloading',
                progress REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)
        await db.commit()

        # Заполняем начальными данными alice_care
        cursor = await db.execute("SELECT COUNT(*) FROM alice_care")
        row = await cursor.fetchone()
        if row[0] == 0:
            now = int(time.time())
            await db.execute(
                "INSERT INTO alice_care (procedure, next_date) VALUES (?, ?)",
                ("прививка", now - 86400 * 365),
            )
            await db.execute(
                "INSERT INTO alice_care (procedure, next_date) VALUES (?, ?)",
                ("от клещей", now - 86400 * 35),
            )
            await db.execute(
                "INSERT INTO alice_care (procedure, next_date) VALUES (?, ?)",
                ("от глистов", now - 86400 * 95),
            )
            await db.commit()
    finally:
        await db.close()


# ── Пользователи ──────────────────────────────────────────────────

async def add_user(telegram_id: int) -> None:
    """Сохранить пользователя (если ещё нет)."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, created_at) VALUES (?, ?)",
            (telegram_id, int(time.time())),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_users() -> list[int]:
    """Вернуть список telegram_id всех сохранённых пользователей."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT telegram_id FROM users")
        rows = await cursor.fetchall()
        return [row["telegram_id"] for row in rows]
    finally:
        await db.close()


# ── Уход за Элис (процедуры) ─────────────────────────────────────

async def get_alice_care() -> dict[str, int]:
    """Вернуть словарь {procedure: next_date_unix}."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT procedure, next_date FROM alice_care")
        rows = await cursor.fetchall()
        return {row["procedure"]: row["next_date"] for row in rows}
    finally:
        await db.close()


async def update_alice_care(procedure: str, next_date: int) -> None:
    """Обновить дату следующей процедуры."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE alice_care SET next_date = ? WHERE procedure = ?",
            (next_date, procedure),
        )
        await db.commit()
    finally:
        await db.close()


# ── Задачи (публичные, без user_id) ──────────────────────────────

async def get_all_tasks() -> list[dict[str, object]]:
    """Вернуть список ВСЕХ невыполненных задач (общий список)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, title, task_date FROM alice_tasks "
            "WHERE is_completed = 0 "
            "ORDER BY task_date ASC"
        )
        rows = await cursor.fetchall()
        return [
            {"id": row["id"], "title": row["title"], "task_date": row["task_date"]}
            for row in rows
        ]
    finally:
        await db.close()


async def create_task(title: str, task_date: str) -> int:
    """Создать задачу, вернуть её id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO alice_tasks (title, task_date) VALUES (?, ?)",
            (title, task_date),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_task(task_id: int, title: str | None = None, task_date: str | None = None) -> bool:
    """Обновить заголовок и/или дату задачи. Вернуть True если задача существует."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM alice_tasks WHERE id = ? AND is_completed = 0",
            (task_id,),
        )
        if not await cursor.fetchone():
            return False

        if title is not None:
            await db.execute(
                "UPDATE alice_tasks SET title = ? WHERE id = ?",
                (title.strip(), task_id),
            )
        if task_date is not None:
            await db.execute(
                "UPDATE alice_tasks SET task_date = ? WHERE id = ?",
                (task_date, task_id),
            )
        await db.commit()
        return True
    finally:
        await db.close()


async def complete_task_with_history(task_id: int, completed_by_name: str) -> bool:
    """Пометить задачу как выполненную и записать в историю.
    Возвращает True если задача существовала и была не завершена."""
    db = await get_db()
    try:
        # Получаем задачу
        cursor = await db.execute(
            "SELECT id, title, task_date FROM alice_tasks WHERE id = ? AND is_completed = 0",
            (task_id,),
        )
        task = await cursor.fetchone()
        if not task:
            return False

        # Записываем в историю
        await db.execute(
            "INSERT INTO alice_task_history (task_id, title, completed_by_name, completed_at) "
            "VALUES (?, ?, ?, ?)",
            (task["id"], task["title"], completed_by_name, int(time.time())),
        )

        # Помечаем как выполненную
        await db.execute(
            "UPDATE alice_tasks SET is_completed = 1 WHERE id = ?",
            (task_id,),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_task(task_id: int) -> bool:
    """Удалить задачу. Вернуть True если задача существовала."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM alice_tasks WHERE id = ?",
            (task_id,),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def return_task_from_history(history_id: int) -> bool:
    """Вернуть задачу из истории в активные (is_completed = 0).
    Если исходная задача удалена — пересоздаёт с сегодняшней датой.
    Возвращает True если история найдена и операция выполнена."""
    from datetime import date

    db = await get_db()
    try:
        # Найти запись в истории
        cursor = await db.execute(
            "SELECT task_id, title FROM alice_task_history WHERE id = ?",
            (history_id,),
        )
        history_row = await cursor.fetchone()
        if not history_row:
            return False

        task_id = history_row["task_id"]
        title = history_row["title"]

        # Проверить, существует ли исходная задача
        cursor = await db.execute(
            "SELECT id FROM alice_tasks WHERE id = ?",
            (task_id,),
        )
        task_exists = await cursor.fetchone()

        if task_exists:
            # Просто снимаем флаг завершённости — дата сохраняется
            await db.execute(
                "UPDATE alice_tasks SET is_completed = 0 WHERE id = ?",
                (task_id,),
            )
        else:
            # Задача была удалена — пересоздаём с сегодняшней датой
            today = date.today().isoformat()
            await db.execute(
                "INSERT INTO alice_tasks (title, task_date, is_completed) VALUES (?, ?, 0)",
                (title, today),
            )

        # Удалить запись из истории
        await db.execute(
            "DELETE FROM alice_task_history WHERE id = ?",
            (history_id,),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def get_due_tasks(date_str: str) -> list[dict[str, object]]:
    """Вернуть все невыполненные задачи, запланированные на указанную дату."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, title FROM alice_tasks "
            "WHERE task_date = ? AND is_completed = 0",
            (date_str,),
        )
        rows = await cursor.fetchall()
        return [
            {"id": row["id"], "title": row["title"]}
            for row in rows
        ]
    finally:
        await db.close()


# ── История задач ─────────────────────────────────────────────────

async def get_task_history() -> list[dict[str, object]]:
    """Вернуть историю выполненных задач, сгруппированную по датам выполнения."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, task_id, title, completed_by_name, completed_at "
            "FROM alice_task_history "
            "ORDER BY completed_at DESC"
        )
        rows = await cursor.fetchall()

        # Группируем по дате (YYYY-MM-DD)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(row["completed_at"], tz=timezone.utc)
            date_key = dt.strftime("%d.%m.%Y")
            if date_key not in grouped:
                grouped[date_key] = []
            grouped[date_key].append({
                "id": row["id"],
                "task_id": row["task_id"],
                "title": row["title"],
                "completed_by_name": row["completed_by_name"],
                "completed_at": row["completed_at"],
            })

        return [
            {"date": date_key, "items": items}
            for date_key, items in grouped.items()
        ]
    finally:
        await db.close()


# ── Рецепты: категории ────────────────────────────────────────────

async def get_recipe_categories() -> list[dict[str, object]]:
    """Список всех категорий рецептов."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, name FROM recipe_categories ORDER BY name ASC")
        rows = await cursor.fetchall()
        return [{"id": row["id"], "name": row["name"]} for row in rows]
    finally:
        await db.close()


async def create_recipe_category(name: str) -> int:
    """Создать категорию, вернуть её id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO recipe_categories (name) VALUES (?)",
            (name.strip(),),
        )
        await db.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        # Уже существует — вернуть id
        cur2 = await db.execute("SELECT id FROM recipe_categories WHERE name = ?", (name.strip(),))
        row = await cur2.fetchone()
        return row["id"] if row else 0
    finally:
        await db.close()


async def delete_recipe_category(category_id: int) -> bool:
    """Удалить категорию. Рецепты не удаляются — им выставляется category_id = NULL."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE recipes SET category_id = NULL WHERE category_id = ?",
            (category_id,),
        )
        cursor = await db.execute(
            "DELETE FROM recipe_categories WHERE id = ?",
            (category_id,),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ── Рецепты ────────────────────────────────────────────────────────

async def get_recipes(category_id: int | None = None) -> list[dict[str, object]]:
    """Список рецептов с JOIN категорий. Опциональная фильтрация по category_id."""
    db = await get_db()
    try:
        if category_id is not None:
            cursor = await db.execute(
                "SELECT r.id, r.title, r.ingredients, r.steps, r.image_url, "
                "r.category_id, c.name AS category_name "
                "FROM recipes r "
                "JOIN recipe_categories c ON r.category_id = c.id "
                "WHERE r.category_id = ? "
                "ORDER BY r.title ASC",
                (category_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT r.id, r.title, r.ingredients, r.steps, r.image_url, "
                "r.category_id, c.name AS category_name "
                "FROM recipes r "
                "JOIN recipe_categories c ON r.category_id = c.id "
                "ORDER BY r.title ASC"
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "ingredients": row["ingredients"],
                "steps": row["steps"],
                "image_url": row["image_url"],
                "category_id": row["category_id"],
                "category_name": row["category_name"],
            }
            for row in rows
        ]
    finally:
        await db.close()


async def create_recipe(
    title: str, category_id: int, ingredients: str, steps: str, image_url: str
) -> int:
    """Создать рецепт, вернуть его id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO recipes (title, category_id, ingredients, steps, image_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (title.strip(), category_id, ingredients.strip(), steps.strip(), image_url),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_recipe(recipe_id: int) -> dict[str, object] | None:
    """Получить один рецепт по id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT r.id, r.title, r.ingredients, r.steps, r.image_url, "
            "r.category_id, c.name AS category_name "
            "FROM recipes r "
            "JOIN recipe_categories c ON r.category_id = c.id "
            "WHERE r.id = ?",
            (recipe_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "ingredients": row["ingredients"],
            "steps": row["steps"],
            "image_url": row["image_url"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
        }
    finally:
        await db.close()


async def update_recipe(
    recipe_id: int, title: str, category_id: int,
    ingredients: str, steps: str, image_url: str | None = None,
) -> bool:
    """Обновить рецепт. Если image_url не None — обновить и путь к картинке."""
    db = await get_db()
    try:
        if image_url is not None:
            await db.execute(
                "UPDATE recipes SET title=?, category_id=?, ingredients=?, steps=?, image_url=? "
                "WHERE id=?",
                (title.strip(), category_id, ingredients.strip(), steps.strip(), image_url, recipe_id),
            )
        else:
            await db.execute(
                "UPDATE recipes SET title=?, category_id=?, ingredients=?, steps=? "
                "WHERE id=?",
                (title.strip(), category_id, ingredients.strip(), steps.strip(), recipe_id),
            )
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_recipe(recipe_id: int) -> dict[str, object] | None:
    """Удалить рецепт, вернуть его данные (для удаления файла картинки)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, image_url FROM recipes WHERE id = ?", (recipe_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        data = {"id": row["id"], "image_url": row["image_url"]}
        await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        await db.commit()
        return data
    finally:
        await db.close()


# ── Загрузки фильмов ──────────────────────────────────────────────

async def add_movie_download(
    title: str,
    torrent_id: str,
    magnet: str,
    category: str = "movies",
    quality: str = "",
    size_text: str = "",
) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO movie_downloads (title, torrent_id, magnet, category, quality, size_text, state, progress, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'downloading', 0.0, ?)",
            (title, torrent_id, magnet, category, quality, size_text, int(time.time())),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_movie_downloads() -> list[dict[str, object]]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, title, category, quality, size_text, state, progress, qb_hash, created_at, completed_at "
            "FROM movie_downloads ORDER BY created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def update_download_state(download_id: int, state: str, progress: float = 0.0, qb_hash: str = "") -> None:
    db = await get_db()
    try:
        if state == "completed":
            await db.execute(
                "UPDATE movie_downloads SET state = ?, progress = 100.0, completed_at = ? WHERE id = ?",
                (state, int(time.time()), download_id),
            )
        else:
            params = [state, progress]
            sql = "UPDATE movie_downloads SET state = ?, progress = ?"
            if qb_hash:
                sql += ", qb_hash = ?"
                params.append(qb_hash)
            sql += " WHERE id = ?"
            params.append(download_id)
            await db.execute(sql, params)
        await db.commit()
    finally:
        await db.close()


async def delete_movie_download(download_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM movie_downloads WHERE id = ?", (download_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ── Настройки (Settings) ──────────────────────────────────────────

async def get_setting(key: str) -> str:
    """Получить значение настройки из БД."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else ""
    finally:
        await db.close()


async def set_setting(key: str, value: str) -> None:
    """Сохранить настройку в БД."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_settings() -> dict[str, str]:
    """Получить все настройки."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()
