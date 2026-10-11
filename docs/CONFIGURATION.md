# Configuration

Use a copied YAML file and protected environment variables. No shared-host secret paths or credentials are bundled.

GLM Coding Plan:

```yaml
zai:
  api_key: "${ZAI_API_KEY}"
  base_url: "https://api.z.ai/api/coding/paas/v4/"
mcp:
  servers: {}
```

Defaults are `zai.glm-5.3-flash?reasoning=low` for both roles. These are separate fresh contexts, not two different models. Select explicit models with `--extractor` and `--reviewer`.

MiniMax's Anthropic-compatible subscription endpoint can be configured separately:

```yaml
anthropic:
  api_key: "${MINIMAX_API_KEY}"
  base_url: "https://api.minimax.io/anthropic"
```

Use an explicit compatible model ID, for example `--reviewer 'anthropic.MiniMax-M3.1-Flash-Preview?reasoning=low'`, after checking availability on your account. MiniMax M3.1 Preview image support and adaptive reasoning are registered through FastAgent’s native runtime model metadata API; this avoids silently dropping images for an unknown model name. See [MiniMax’s API contract](https://platform.minimax.io/docs/api-reference/text-anthropic-api). There is no automatic quota fallback or rerouting to a paid provider.

Each FastAgent worker gets a fresh context, up to 16 tool/model turns, and its own catalog MCP process. Runs are sequential, with default 90-second per-worker and 180-second total job deadlines, and one repair round. `--pages 78`, `--pages 1,3-5` and `--pages all` select input. Interrupted runs retain artifacts; `--resume` reuses accepted unchanged pages and resumes a matching tool-saved candidate at the reviewer stage after interruption. Use bounded subsets to process long catalogs. Complex pages can use `--call-timeout 300 --deadline 360`; a retained review checkpoint can be continued with `--resume` instead of paying for extraction again. Model output truncation, schema failure, timeout and incomplete review never count as accepted.
