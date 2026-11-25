# RAG assistant with quality control

A Telegram bot that answers questions about a women's retreat using the retreat's own documents. It runs on two models you can switch between, ChatGPT and GigaChat, and answer quality is checked automatically with RAGAS metrics.

This is a practice project. The retreat, "Know Yourself" («Познай себя»), is a training scenario of a retreat center, not a real organization. Case study: [tatidzufri.com/en/case/rag-assistant](https://tatidzufri.com/en/case/rag-assistant).

![Switching models and comparing answers](demo/bot_model_switching.png)

## About the project

The bot follows the RAG pattern. It first finds the relevant fragments in the knowledge base, then passes them to the model, which writes the answer. That keeps answers grounded in the retreat documents instead of the model's guesses.

The user picks the model right in Telegram with the `/mode` command, so the same question can be put to ChatGPT and GigaChat and the answers compared.

## The task

People interested in a retreat ask the same things again and again: what the program includes, how to prepare, what to pack, who the retreat is for. The assistant had to answer these on its own and politely decline off-topic questions, such as marketing strategy or internal data.

The second half of the task: answers have to be accurate, and that has to be checkable. So the system has logging, statistics, log export and automatic quality evaluation built in.

## How it works

1. **Knowledge base.** Retreat documents from `data/` are split into meaningful fragments and stored in a ChromaDB vector database. The `/reindex` command rebuilds it after the documents change.
2. **Search and answer.** For each question the bot finds the closest fragments with semantic search and hands them to the selected model.
3. **Two models.** ChatGPT (`gpt-4o-mini`, embeddings `text-embedding-3-small`) and GigaChat by Sber. Each has its own pipeline and its own vector store.
4. **Cache.** If the same question was asked before, the answer comes from the cache without a new model call.
5. **Logs and statistics.** Every request is written to SQLite. "Statistics" shows the current model, knowledge base size, cache, request count and average response time; "Logs" exports the journal to CSV.
6. **RAGAS evaluation.** `evaluate_compare.py` runs both models over 50 test questions and computes three metrics: Faithfulness, Context Precision and Answer Relevancy.

## What it looks like

**Start and statistics.** The greeting with the list of models, system statistics and the CSV log export.

![Bot start and statistics](demo/bot_start_and_stats.png)

**Two models, one question** (screenshot at the top). Asked about time for silence and solitude, GigaChat gives a detailed answer with schedule specifics. After switching with `/mode`, ChatGPT answers more briefly.

**RAGAS comparison.** A summary table across the three metrics and six topic groups: what the product is, audience, program, logistics and packing, rules and contact, declining off-topic questions.

![Model comparison](demo/evaluation_comparison.png)

## Results

- On my test run of 50 questions the two models scored almost the same on RAGAS: 0.8412 for ChatGPT and 0.8413 for GigaChat. ChatGPT sticks to the context more closely, GigaChat scores higher on answer relevancy.
- The accuracy of every answer can be checked automatically rather than by eye.
- The system moves to another domain easily: replace the documents in `data/` and run `/reindex`.

## Tech stack

| Technology | What it's for |
|---|---|
| **Python** | Project language, 3.12 in the container |
| **OpenAI API** | ChatGPT answers (`gpt-4o-mini`) and search embeddings |
| **GigaChat API** | The second model, by Sber, for answers and embeddings |
| **ChromaDB** | Vector store: keeps document fragments and searches by meaning |
| **SQLite** | Answer cache and request log |
| **python-telegram-bot** | Bot interface: commands, menu buttons, file export |
| **RAGAS** | Automatic answer quality metrics |
| **LangChain** | Connects OpenAI embeddings to RAGAS |
| **Docker Compose** | Runs the bot on the server. Metrics are computed outside the container so the image doesn't pull in heavy evaluation libraries |

## Repository structure

- `run_bot.py`: starts the bot with both models.
- `evaluate_compare.py`: RAGAS comparison of the models.
- `data/`: retreat documents for the knowledge base (in Russian).
- `assistant_api/`: the OpenAI pipeline (search, cache, logs, Telegram wrapper).
- `assistant_giga/`: the same pipeline on GigaChat, plus the API client and the certificate for connecting to GigaChat.
- `requirements.txt`: all dependencies, including evaluation. `requirements-bot.txt`: the bot only.
- `demo/`: screenshots.

## Running it

Create `.env` in the project root:

```env
OPENAI_API_KEY=
GIGACHAT_RQUID=
GIGACHAT_AUTH_KEY=
TELEGRAM_BOT_TOKEN=
```

Locally:

```bash
pip install -r requirements.txt
python run_bot.py              # the bot
python evaluate_compare.py     # model evaluation, optional
```

On a server with Docker Compose (bot only):

```bash
touch bot_logs.db
docker compose up -d --build
```

Create `bot_logs.db` before the first start, otherwise Docker creates a directory in its place. The vector stores are mounted from `assistant_api/chroma_db` and `assistant_giga/chroma_db`. If they are empty, the bot indexes the documents itself on first start.

## Author

Tetiana Dziubas, AI automation engineer. I build Telegram bots, RAG assistants and LLM agents that take routine work off small teams. Case studies and contact: [tatidzufri.com/en](https://tatidzufri.com/en/).
