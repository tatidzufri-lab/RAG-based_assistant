#!/usr/bin/env python3
"""
Единый Telegram бот с выбором модели: ChatGPT или GigaChat.

Пользователь переключается между моделями командой /mode.
Каждый пользователь хранит свой выбор — разные люди могут
одновременно общаться с разными моделями.

Запуск из корня проекта:
    python run_bot.py
"""

import sys
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# DatabaseLogger — автономный модуль без конфликтов, импорт безопасен
sys.path.insert(0, str(ROOT_DIR / 'assistant_api'))
from db_logger import DatabaseLogger
sys.path.pop(0)


# ─── Инициализация пайплайнов с изоляцией импортов ──────────────────────
#
# assistant_api/ и assistant_giga/ содержат модули с одинаковыми именами
# (rag_pipeline.py, vector_store.py, cache.py), но разными реализациями.
# Изолируем импорты через временное переключение sys.path и cwd.

CONFLICT_MODULES = ['rag_pipeline', 'vector_store', 'cache', 'gigachat_client']


def _init_in_directory(directory, factory):
    """
    Выполняет factory() с sys.path и cwd, указывающими на directory.
    После инициализации очищает sys.modules от конфликтующих имён.
    """
    saved_cwd = os.getcwd()
    saved = {n: sys.modules.pop(n) for n in CONFLICT_MODULES if n in sys.modules}

    sys.path.insert(0, directory)
    os.chdir(directory)

    try:
        return factory()
    finally:
        os.chdir(saved_cwd)
        if directory in sys.path:
            sys.path.remove(directory)
        for n in CONFLICT_MODULES:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


SHARED_DATA_PATH = str(ROOT_DIR / 'data')
SHARED_DATA_PATH_EN = str(ROOT_DIR / 'data_en')


def init_api_pipeline():
    """Инициализация RAG pipeline на OpenAI API (ChatGPT)."""
    api_dir = str(ROOT_DIR / 'assistant_api')
    cache_path = str(ROOT_DIR / 'assistant_api' / 'api_rag_cache.db')

    def factory():
        from rag_pipeline import RAGPipeline
        return RAGPipeline(
            collection_name="api_rag_collection",
            cache_db_path=cache_path,
            data_path=SHARED_DATA_PATH,
            model="gpt-4o-mini"
        )

    return _init_in_directory(api_dir, factory)


def init_api_pipeline_en():
    """ChatGPT по английской базе data_en/: своя коллекция и свой кеш."""
    api_dir = str(ROOT_DIR / 'assistant_api')
    cache_path = str(ROOT_DIR / 'assistant_api' / 'api_rag_cache_en.db')

    def factory():
        from rag_pipeline import RAGPipeline
        return RAGPipeline(
            collection_name="api_rag_collection_en",
            cache_db_path=cache_path,
            data_path=SHARED_DATA_PATH_EN,
            model="gpt-4o-mini",
            language="en",
        )

    return _init_in_directory(api_dir, factory)


def init_giga_pipeline():
    """Инициализация RAG pipeline на GigaChat."""
    giga_dir = str(ROOT_DIR / 'assistant_giga')
    cache_path = str(ROOT_DIR / 'assistant_giga' / 'gigachat_rag_cache.db')

    def factory():
        from rag_pipeline import RAGPipeline
        return RAGPipeline(
            collection_name="gigachat_rag_collection",
            cache_db_path=cache_path,
            data_path=SHARED_DATA_PATH,
            model="GigaChat"
        )

    return _init_in_directory(giga_dir, factory)


# ─── Единый Telegram бот ────────────────────────────────────────────────
#
# Два языка. Русский: ChatGPT и GigaChat по базе data/. Английский: ChatGPT
# по базе data_en/ (адаптированная версия ретрита). GigaChat в английском
# интерфейсе остается доступен, но отвечает по русской базе и по-русски.

import re

LANGS = ("ru", "en")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")

MODE_LABELS = {
    'ru': {'chatgpt': 'ChatGPT (OpenAI)', 'gigachat': 'GigaChat (Сбер)'},
    'en': {'chatgpt': 'ChatGPT (OpenAI)', 'gigachat': 'GigaChat (Sber, Russian only)'},
}

BUTTONS = {
    'ru': {'mode': "Сменить модель", 'stats': "Статистика", 'logs': "Мои логи", 'help': "Справка",
           'reindex': "Переиндексация", 'lang': "English 🇬🇧"},
    'en': {'mode': "Change model", 'stats': "Statistics", 'logs': "My logs", 'help': "Help",
           'reindex': "Reindex", 'lang': "Русский 🇷🇺"},
}
# Кнопки узнаются на любом языке: участник мог переключить язык между нажатиями
BUTTON_ACTIONS = {label: action for lang in BUTTONS for action, label in BUTTONS[lang].items()}

TEXTS = {
    'start': {
        'ru': "Добро пожаловать в RAG-ассистент!\n\nДоступные модели:\n{modes}\n\nТекущая модель: {current}\n\n"
              "Используйте кнопки меню внизу или просто напишите вопрос!",
        'en': "Welcome to the RAG assistant!\n\nAvailable models:\n{modes}\n\nCurrent model: {current}\n\n"
              "Use the menu buttons below or just type your question. The knowledge base covers the "
              "Know Yourself retreat, so ask anything a guest might want to know.",
    },
    'help': {
        'ru': "Как пользоваться ботом:\n\nНапишите вопрос — бот ответит на основе базы знаний.\n\nКнопки меню:\n"
              "  {mode} — переключить ChatGPT / GigaChat\n  {stats} — статистика системы\n"
              "  {logs} — экспорт ваших логов в CSV\n  {reindex} — обновить базу знаний\n  {help} — эта справка\n\n"
              "Также доступны /-команды:\n/mode  /stats  /logs  /reindex  /help  /language",
        'en': "How to use the bot:\n\nType a question, and the bot answers from the knowledge base.\n\nMenu buttons:\n"
              "  {mode} — switch between ChatGPT and GigaChat\n  {stats} — system statistics\n"
              "  {logs} — export your logs as CSV\n  {reindex} — rebuild the knowledge base\n  {help} — this help\n\n"
              "Commands:\n/mode  /stats  /logs  /reindex  /help  /language",
    },
    'mode_current': {'ru': "Текущая модель: {current}\n\nВыберите модель:", 'en': "Current model: {current}\n\nChoose a model:"},
    'mode_unavailable': {'ru': "Эта модель недоступна.", 'en': "This model is not available."},
    'mode_switched': {'ru': "Модель переключена на: {label}", 'en': "Model switched to: {label}"},
    'reindex_start': {'ru': "Переиндексация базы знаний...\nЭто может занять несколько минут.",
                      'en': "Rebuilding the knowledge base...\nThis may take a few minutes."},
    'reindex_done': {'ru': "Переиндексация завершена!\n\n{report}", 'en': "Reindexing complete!\n\n{report}"},
    'chunks': {'ru': "{label}: {count} чанков", 'en': "{label}: {count} chunks"},
    'error_item': {'ru': "{label}: ошибка — {e}", 'en': "{label}: error — {e}"},
    'stats': {
        'ru': "СТАТИСТИКА СИСТЕМЫ\n\nТекущая модель: {current}\n\nБаза знаний:\n  Документов (чанков): {chunks}\n"
              "  Модель: {model}\n\nКеш:\n  Записей: {cache}\n\nЛоги:\n  Всего запросов: {total}\n  Из кеша: {cached}\n"
              "  Уникальных пользователей: {users}\n  Среднее время ответа: {avg:.0f} мс",
        'en': "SYSTEM STATISTICS\n\nCurrent model: {current}\n\nKnowledge base:\n  Documents (chunks): {chunks}\n"
              "  Model: {model}\n\nCache:\n  Entries: {cache}\n\nLogs:\n  Total requests: {total}\n  From cache: {cached}\n"
              "  Unique users: {users}\n  Average response time: {avg:.0f} ms",
    },
    'error': {'ru': "Ошибка: {e}", 'en': "Error: {e}"},
    'no_logs': {'ru': "Логов пока нет.", 'en': "No logs yet."},
    'logs_caption': {'ru': "Ваши логи взаимодействий", 'en': "Your interaction logs"},
    'from_cache': {'ru': "(ответ из кеша)", 'en': "(cached answer)"},
    'lang_set': {'ru': "Хорошо, дальше говорим по-русски.", 'en': "Great, let's continue in English."},
}

BOT_COMMANDS = {
    'ru': [
        BotCommand("start", "Запустить бота"),
        BotCommand("mode", "Выбрать модель (ChatGPT / GigaChat)"),
        BotCommand("stats", "Статистика системы"),
        BotCommand("logs", "Экспорт логов в CSV"),
        BotCommand("reindex", "Переиндексировать базу знаний"),
        BotCommand("help", "Справка по командам"),
        BotCommand("language", "Сменить язык / Change language"),
    ],
    'en': [
        BotCommand("start", "Start the bot"),
        BotCommand("mode", "Choose a model (ChatGPT / GigaChat)"),
        BotCommand("stats", "System statistics"),
        BotCommand("logs", "Export logs as CSV"),
        BotCommand("reindex", "Rebuild the knowledge base"),
        BotCommand("help", "Help"),
        BotCommand("language", "Change language / Сменить язык"),
    ],
}
DESCRIPTION_EN = (
    "A RAG assistant for the Know Yourself retreat. Ask a question, and the bot answers strictly from "
    "the knowledge base. Switch between ChatGPT and GigaChat with /mode. Я говорю и по-русски: /language"
)
SHORT_DESCRIPTION_EN = "RAG assistant: answers strictly from the retreat knowledge base."


def lang_from_telegram(language_code):
    if not language_code:
        return 'ru'
    return 'ru' if language_code.lower().startswith(('ru', 'uk', 'be', 'kk')) else 'en'


def lang_from_text(text):
    if _CYRILLIC.search(text):
        return 'ru'
    if len(_LATIN_WORD.findall(text)) >= 3:
        return 'en'
    return None


def t(key, lang, **kw):
    text = TEXTS[key][lang]
    return text.format(**kw) if kw else text


class UnifiedTelegramBot:
    """Telegram бот с переключением между ChatGPT и GigaChat, на русском и английском."""

    def __init__(self, token: str, pipelines: dict, logger: DatabaseLogger, pipelines_en: dict | None = None):
        self.pipelines = pipelines
        self.pipelines_en = pipelines_en or {}
        self.logger = logger
        self.user_modes = {}
        self.user_langs = {}
        self.default_mode = list(pipelines.keys())[0]

        self.app = Application.builder().token(token).build()
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("mode", self.cmd_mode))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("logs", self.cmd_logs))
        self.app.add_handler(CommandHandler("reindex", self.cmd_reindex))
        self.app.add_handler(CommandHandler("language", self.cmd_language))
        self.app.add_handler(CommandHandler(["en", "ru"], self.cmd_lang_shortcut))
        self.app.add_handler(CallbackQueryHandler(self.on_mode_callback, pattern=r"^mode_"))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message)
        )

        self.app.post_init = self._post_init

    def _keyboard(self, lang):
        b = BUTTONS[lang]
        return ReplyKeyboardMarkup(
            [
                [KeyboardButton(b['mode']), KeyboardButton(b['stats'])],
                [KeyboardButton(b['logs']), KeyboardButton(b['reindex'])],
                [KeyboardButton(b['help']), KeyboardButton(b['lang'])],
            ],
            resize_keyboard=True,
        )

    async def _post_init(self, application):
        """Меню команд на двух языках и описание для англоязычных пользователей."""
        bot = application.bot
        await bot.set_my_commands(BOT_COMMANDS['ru'])
        for code in ('ru', 'uk'):
            await bot.set_my_commands(BOT_COMMANDS['ru'], language_code=code)
        await bot.set_my_commands(BOT_COMMANDS['en'], language_code='en')
        try:
            await bot.set_my_description(DESCRIPTION_EN, language_code='en')
            await bot.set_my_short_description(SHORT_DESCRIPTION_EN, language_code='en')
        except Exception as e:
            print(f"[-] Не удалось задать описание бота: {e}")

    def _get_user_mode(self, user_id: str) -> str:
        return self.user_modes.get(user_id, self.default_mode)

    def _lang(self, update: Update) -> str:
        user = update.effective_user
        user_id = str(user.id)
        if user_id not in self.user_langs:
            self.user_langs[user_id] = lang_from_telegram(user.language_code)
        return self.user_langs[user_id]

    def _set_lang(self, update: Update, lang: str):
        if lang in LANGS:
            self.user_langs[str(update.effective_user.id)] = lang

    def _pipeline(self, mode: str, lang: str):
        if lang == 'en' and mode in self.pipelines_en:
            return self.pipelines_en[mode]
        return self.pipelines[mode]

    # ── Команды ──

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # t.me/<бот>?start=en — ссылка с английской страницы сайта
        if context.args and context.args[0] in LANGS:
            self._set_lang(update, context.args[0])
        lang = self._lang(update)
        user_id = str(update.effective_user.id)
        current = self._get_user_mode(user_id)
        modes_list = "\n".join(f"  • {MODE_LABELS[lang][k]}" for k in self.pipelines)
        await update.message.reply_text(
            t('start', lang, modes=modes_list, current=MODE_LABELS[lang][current]),
            reply_markup=self._keyboard(lang),
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = self._lang(update)
        await update.message.reply_text(t('help', lang, **BUTTONS[lang]), reply_markup=self._keyboard(lang))

    async def cmd_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        new_lang = 'en' if self._lang(update) == 'ru' else 'ru'
        self._set_lang(update, new_lang)
        await update.message.reply_text(t('lang_set', new_lang), reply_markup=self._keyboard(new_lang))

    async def cmd_lang_shortcut(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        new_lang = update.message.text.lstrip('/').split('@')[0].split()[0].lower()
        self._set_lang(update, new_lang)
        await update.message.reply_text(t('lang_set', new_lang), reply_markup=self._keyboard(new_lang))

    async def cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = self._lang(update)
        user_id = str(update.effective_user.id)
        current = self._get_user_mode(user_id)

        buttons = []
        for key in self.pipelines:
            label = MODE_LABELS[lang][key]
            if key == current:
                label = f">> {label} <<"
            buttons.append([InlineKeyboardButton(label, callback_data=f"mode_{key}")])

        await update.message.reply_text(
            t('mode_current', lang, current=MODE_LABELS[lang][current]),
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def on_mode_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        lang = self._lang(update)

        mode_key = query.data.removeprefix("mode_")
        if mode_key not in self.pipelines:
            await query.edit_message_text(t('mode_unavailable', lang))
            return

        user_id = str(query.from_user.id)
        self.user_modes[user_id] = mode_key
        await query.edit_message_text(t('mode_switched', lang, label=MODE_LABELS[lang][mode_key]))

    async def cmd_reindex(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = self._lang(update)
        await update.message.reply_text(t('reindex_start', lang))

        results = []
        all_pipelines = [(MODE_LABELS[lang][k] + " · RU", p) for k, p in self.pipelines.items()]
        all_pipelines += [(MODE_LABELS[lang][k] + " · EN", p) for k, p in self.pipelines_en.items()]
        for label, pipeline in all_pipelines:
            try:
                count = pipeline.reindex()
                results.append(t('chunks', lang, label=label, count=count))
            except Exception as e:
                results.append(t('error_item', lang, label=label, e=e))

        await update.message.reply_text(t('reindex_done', lang, report="\n".join(results)))

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = self._lang(update)
        try:
            user_id = str(update.effective_user.id)
            current = self._get_user_mode(user_id)
            pipeline = self._pipeline(current, lang)
            stats = pipeline.get_stats()
            log_stats = self.logger.get_stats()

            await update.message.reply_text(t(
                'stats', lang,
                current=MODE_LABELS[lang][current],
                chunks=stats['vector_store']['count'],
                model=stats['model'],
                cache=stats['cache']['total_entries'],
                total=log_stats['total_requests'],
                cached=log_stats['cached_requests'],
                users=log_stats['unique_users'],
                avg=log_stats['avg_response_time_ms'],
            ))
        except Exception as e:
            await update.message.reply_text(t('error', lang, e=e))

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = self._lang(update)
        try:
            user_id = str(update.effective_user.id)
            csv_content = self.logger.export_to_csv(user_id=user_id)

            if not csv_content:
                await update.message.reply_text(t('no_logs', lang))
                return

            filename = f"logs_{user_id}_{int(time.time())}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(csv_content)

            with open(filename, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=t('logs_caption', lang)
                )
            os.remove(filename)
        except Exception as e:
            await update.message.reply_text(t('error', lang, e=e))

    # ── Обработка сообщений ──

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text

        action = BUTTON_ACTIONS.get(user_message)
        if action == 'mode':
            return await self.cmd_mode(update, context)
        if action == 'stats':
            return await self.cmd_stats(update, context)
        if action == 'logs':
            return await self.cmd_logs(update, context)
        if action == 'help':
            return await self.cmd_help(update, context)
        if action == 'reindex':
            return await self.cmd_reindex(update, context)
        if action == 'lang':
            return await self.cmd_language(update, context)

        # Вопрос на другом языке — отвечаем на нем
        detected = lang_from_text(user_message)
        if detected:
            self._set_lang(update, detected)
        lang = self._lang(update)

        user = update.effective_user
        user_id = str(user.id)
        username = user.username or user.first_name or "Unknown"

        mode = self._get_user_mode(user_id)
        pipeline = self._pipeline(mode, lang)

        await update.message.chat.send_action(action="typing")
        start_time = time.time()

        try:
            result = pipeline.query(user_message)
            response_time_ms = int((time.time() - start_time) * 1000)

            self.logger.log_interaction(
                query=user_message,
                response=result['answer'],
                source="telegram",
                user_id=user_id,
                username=username,
                from_cache=result['from_cache'],
                response_time_ms=response_time_ms
            )

            answer = result['answer']
            mode_label = MODE_LABELS[lang][mode]
            header = f"[{mode_label}]\n\n"

            max_len = 4000 - len(header)
            if len(answer) <= max_len:
                await update.message.reply_text(header + answer)
            else:
                parts = [answer[i:i + max_len] for i in range(0, len(answer), max_len)]
                for i, part in enumerate(parts):
                    prefix = header if i == 0 else ""
                    await update.message.reply_text(prefix + part)

            if result['from_cache']:
                await update.message.reply_text(t('from_cache', lang))

        except Exception as e:
            error_msg = t('error', lang, e=e)
            await update.message.reply_text(error_msg)
            self.logger.log_interaction(
                query=user_message,
                response=error_msg,
                source="telegram",
                user_id=user_id,
                username=username,
                from_cache=False,
                response_time_ms=int((time.time() - start_time) * 1000)
            )

    def run(self):
        print("Telegram бот запущен! Нажмите Ctrl+C для остановки.")
        self.app.run_polling()


# ─── Точка входа ────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        print("Ошибка: TELEGRAM_BOT_TOKEN не задан в .env")
        print("Получите токен у @BotFather в Telegram и впишите в .env")
        sys.exit(1)

    print("=" * 60)
    print("ИНИЦИАЛИЗАЦИЯ ЕДИНОГО TELEGRAM БОТА")
    print("=" * 60)

    pipelines = {}
    pipelines_en = {}

    # ChatGPT (OpenAI)
    if os.getenv("OPENAI_API_KEY"):
        try:
            print("\n[1/2] Инициализация ChatGPT (OpenAI)...")
            pipelines['chatgpt'] = init_api_pipeline()
            print("[+] ChatGPT готов")
            pipelines_en['chatgpt'] = init_api_pipeline_en()
            print("[+] ChatGPT (EN) готов")
        except Exception as e:
            print(f"[-] Ошибка ChatGPT: {e}")
    else:
        print("\n[-] OPENAI_API_KEY не задан — ChatGPT недоступен")

    # GigaChat (Сбер)
    if os.getenv("GIGACHAT_AUTH_KEY") and os.getenv("GIGACHAT_RQUID"):
        try:
            print("\n[2/2] Инициализация GigaChat...")
            pipelines['gigachat'] = init_giga_pipeline()
            print("[+] GigaChat готов")
        except Exception as e:
            print(f"[-] Ошибка GigaChat: {e}")
    else:
        print("\n[-] GIGACHAT_AUTH_KEY / GIGACHAT_RQUID не заданы — GigaChat недоступен")

    if not pipelines:
        print("\nНи одна модель не инициализирована. Проверьте ключи в .env")
        sys.exit(1)

    # Логгер
    print("\n[*] Инициализация логгера...")
    logger = DatabaseLogger(db_path=str(ROOT_DIR / "bot_logs.db"))
    print("[+] Логгер готов")

    available = ", ".join(MODE_LABELS['ru'][k] for k in pipelines)
    print(f"\nДоступные модели: {available}")
    print("=" * 60)

    bot = UnifiedTelegramBot(token=token, pipelines=pipelines, logger=logger, pipelines_en=pipelines_en)
    bot.run()


if __name__ == "__main__":
    main()
