# Claw-a-thon AI Agent Vung Tau

Simple GreenNode AgentBase agent that answers questions from a Supabase table.

## Local configuration

Copy `.env.example` to `.env` and fill in:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` or `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_TABLE`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

Optional:

- `SUPABASE_SELECT` limits returned columns, for example `id,name,total,created_at`
- `MAX_ROWS` caps rows sent to the LLM, default `100`
- `SYSTEM_PROMPT_PATH` points to the Markdown system prompt, default `prompts/system_prompt.md`

`SUPABASE_URL` can be either the Supabase REST URL (`https://...supabase.co`) or
a direct Postgres connection string (`postgresql://...`).

## Invoke

Open the web UI:

```text
GET /
```

Upload files:

```text
POST /uploads
```

Files are stored in `UPLOAD_DIR` (`/tmp/agent_uploads` by default). On AgentBase
this is runtime-local storage: it is suitable for demos and one-replica usage,
but not durable across redeploys or replica replacement. For production, move
uploads to Supabase Storage or another object store.

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"message":"Tóm tắt dữ liệu này", "limit": 20}'
```

Exact-match filters are supported:

```json
{
  "message": "Tổng hợp các dòng của Vũng Tàu",
  "filters": {
    "city": "Vung Tau"
  },
  "limit": 50
}
```
