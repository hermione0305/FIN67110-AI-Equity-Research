# Purdue GenAI Studio models available to this account

Discovered with the API_KEY stored locally in .env. The key is not included here.
Discovery time: 2026-11-05T15:14:59.893263+00:00

Configured model: `gpt-oss:120b` (vLLM).

Base URL: `https://genai.rcac.purdue.edu/api`
Chat endpoint: `https://genai.rcac.purdue.edu/api/chat/completions`

The initial live short request returned HTTP 200, finish reason `stop`, and `{"ok": true}`
using `gpt-oss:120b`. It used 76 prompt tokens and 65 completion tokens (141 total).
No full COST report was run during this migration.

## Model IDs

- `codellama:latest`
- `deepseek-r1:1.5b`
- `deepseek-r1:14b`
- `deepseek-r1:32b`
- `deepseek-r1:7b`
- `devstral-small-2:latest`
- `gemma3:12b`
- `gemma3:1b`
- `gemma3:27b`
- `gemma4:26b-a4b`
- `gpt-oss:120b`
- `gpt-oss:latest`
- `llama3.1:70b-instruct-q4_K_M`
- `llama3.1:latest`
- `llama3.2:latest`
- `llama3.3:70b`
- `llama4:latest`
- `llava:latest`
- `medgemma:27b`
- `mistral:latest`
- `phi4:latest`
- `qwen2.5:72b`
- `qwen3-coder:latest`
- `qwen3-vl:32b`
- `qwen3.8:27b`
- `qwen3:1.7b`
- `qwen3:14b`
- `qwen3:30b`
- `qwen3:32b`
- `qwen3:4b`
- `qwen3:8b`
- `qwq:32b-fp16`
- `qwq:latest`

Source: authenticated Purdue `GET /api/models`.
API documentation: https://docs.rcac.purdue.edu/services/genai/api/
Hosted-model/backend documentation: https://docs.rcac.purdue.edu/services/genai/models/

The final migrated-adapter check also succeeded. Live SDK check record:
`provider_checks/purdue_20261105T151820_07b6956a.json`.
