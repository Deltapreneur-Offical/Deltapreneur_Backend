# Bro

Bro is mounted at `/api/v1/ai` and is designed as the marketplace intelligence layer for domains, auctions, ventures, creators, CoCreation software, naming, brokerage, branding, and support.

## Environment

Set these values in the backend environment:

```env
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4.1-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_SITE_URL=https://co-brother-frontend.vercel.app
OPENROUTER_APP_NAME=Bro
```

If `OPENROUTER_API_KEY` is missing, the assistant returns a safe local fallback using real marketplace context so development can continue without provider secrets.

## Main Endpoints

- `POST /api/v1/ai/chat/stream` streams Server-Sent Events: `metadata`, `token`, `done`, and `error`.
- `GET /api/v1/ai/chats` lists authenticated user conversations.
- `PATCH /api/v1/ai/chats/{session_id}` renames a conversation.
- `DELETE /api/v1/ai/chats/{session_id}` soft-deletes a conversation.
- `GET /api/v1/ai/marketplace?q=` returns marketplace context.
- `POST /api/v1/ai/favorites` saves domains, ventures, auctions, creators, or software.
- `GET /api/v1/ai/preferences` and `PUT /api/v1/ai/preferences` manage personalization.

## Data Safety

The context builder retrieves real marketplace data before provider calls. Prompts instruct the model to avoid invented listings and to recommend only items found in the supplied context. Provider failures are hidden behind safe user-facing errors.

## Future-Ready Hooks

`semantic_search_service.py` currently performs deterministic keyword ranking and is intentionally shaped to be replaced by pgvector/embedding retrieval without changing the controller or frontend contract.
