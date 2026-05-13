import structlog
from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from resusbot.config import settings
from resusbot.telegram.billing_handlers import (
    cancelar_handler,
    historico_handler,
    plan_callback_handler,
    planos_handler,
    saldo_handler,
)
from resusbot.telegram.handlers import (
    help_handler,
    message_handler,
    search_handler,
    start_handler,
    stats_handler,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_application: Application | None = None  # type: ignore[type-arg]


def build_application() -> Application:  # type: ignore[type-arg]
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("search", search_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    # Billing commands (Fase 9)
    app.add_handler(CommandHandler("saldo", saldo_handler))
    app.add_handler(CommandHandler("planos", planos_handler))
    app.add_handler(CommandHandler("historico", historico_handler))
    app.add_handler(CommandHandler("cancelar", cancelar_handler))
    app.add_handler(CallbackQueryHandler(plan_callback_handler, pattern=r"^plan:"))
    # Mensagem livre (deve vir por último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app


async def setup_bot_commands(app: Application) -> None:  # type: ignore[type-arg]
    commands = [
        BotCommand("start", "Apresentação do bot"),
        BotCommand("search", "Pesquisar artigo científico"),
        BotCommand("saldo", "Ver créditos disponíveis"),
        BotCommand("planos", "Ver planos disponíveis"),
        BotCommand("historico", "Histórico de transações"),
        BotCommand("cancelar", "Cancelar renovação automática"),
        BotCommand("help", "Ajuda"),
        BotCommand("stats", "Suas estatísticas de uso"),
    ]
    await app.bot.set_my_commands(commands)
    log.info("telegram_commands_registered")


async def start_polling(app: Application) -> None:  # type: ignore[type-arg]
    log.info("telegram_polling_start")
    await app.initialize()
    await setup_bot_commands(app)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]


async def stop_polling(app: Application) -> None:  # type: ignore[type-arg]
    log.info("telegram_polling_stop")
    await app.updater.stop()  # type: ignore[union-attr]
    await app.stop()
    await app.shutdown()


async def setup_webhook(app: Application) -> None:  # type: ignore[type-arg]
    webhook_url = f"{settings.telegram_webhook_url}/{settings.telegram_webhook_secret}"
    await app.initialize()
    await setup_bot_commands(app)
    await app.start()
    await app.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.telegram_webhook_secret,
        drop_pending_updates=True,
    )
    log.info("telegram_webhook_set", url=webhook_url)
