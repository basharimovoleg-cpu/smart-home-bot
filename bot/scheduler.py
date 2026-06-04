"""
Планировщик: ежедневная проверка задач для Элис и отправка уведомлений.
"""
import datetime
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_all_users, get_due_tasks

logger = logging.getLogger(__name__)


async def check_due_tasks(bot: Bot) -> None:
    """Проверить БД: если есть задачи на сегодня — отправить напоминание."""
    today = datetime.date.today().isoformat()
    logger.info(f"Scheduler: checking tasks for {today}")

    try:
        tasks = await get_due_tasks(today)
        if not tasks:
            logger.info("Scheduler: no due tasks today")
            return

        users = await get_all_users()
        if not users:
            logger.info("Scheduler: no users to notify")
            return

        for task in tasks:
            task_text = f"🔔 *Напоминание*\n\n📋 {task['title']}"
            for user_id in users:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=task_text,
                        parse_mode="Markdown",
                    )
                    logger.info(f"Scheduler: notified user {user_id} about task {task['id']}")
                except Exception as e:
                    logger.warning(f"Scheduler: failed to notify user {user_id}: {e}")

    except Exception as e:
        logger.error(f"Scheduler: error checking due tasks: {e}")


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Настроить ежедневную задачу (каждый день в 9:00)."""
    scheduler.add_job(
        check_due_tasks,
        trigger="cron",
        hour=9,
        minute=0,
        args=[bot],
        id="daily_task_check",
        replace_existing=True,
    )
    logger.info("Scheduler: daily task check configured (9:00 daily)")
