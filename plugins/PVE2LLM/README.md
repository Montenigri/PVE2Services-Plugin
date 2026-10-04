# PVE2 LLM — Winky

Winky is the PVE2Services assistant. It is an **in-process MCP client**: it
collects the read-only tools every plugin declares in its `plugin.yaml`
`mcp:` block, exposes them to a configurable LLM provider and answers questions
about the cluster.

## Providers

| Provider | `base_url` default | Auth |
|---|---|---|
| Ollama (locale) | `http://localhost:11434` | nessuna |
| OpenAI (o compatibile) | `https://api.openai.com/v1` | `api_key` (Bearer) — **solo** per l'API cloud |
| Anthropic | `https://api.anthropic.com` | `api_key` (`x-api-key`) |

> **Server OpenAI-compatibile locale** (vLLM, llama.cpp, Unsloth, …): imposta
> `provider: openai` e `base_url` verso il server (es. `http://host:8000/v1`).
> La `/v1` viene aggiunta automaticamente se la ometti e **non serve una API
> key**, perché un `base_url` custom è trattato come self-hosted. La chiave
> resta invece obbligatoria per l'API OpenAI ospitata (`api.openai.com`) e per
> Anthropic.

La chiave API è salvata cifrata da `ConnectorConfig` (`pve2llm`).

## Sicurezza e privacy

- **Solo lettura**: Winky offre esclusivamente i tool con `read_only=True`;
  nessun tool di sync/deploy/power viene registrato.
- I segreti di `connector_config` non vengono mai inviati al provider.
- Ogni chiamata a un tool è registrata nell'audit log (`[pve2llm]`).
- **SSRF**: la `base_url` del provider viene validata e gli host di metadata
  cloud (`169.254.169.254`, `metadata.google.internal`, `100.100.100.200`, …)
  sono bloccati; `localhost`/privati restano permessi per Ollama locale.
- **Egress dati**: domande e risultati dei tool vengono inviati al provider
  configurato. Con un provider cloud i dati escono dalla tua rete — valutane
  l'uso e preferisci un Ollama locale per dati sensibili.
- **Abuso/costi**: `/chat` è protetto da un rate limit configurabile
  (`rate_limit_per_minute`, default 20; 0 disabilita).
- **Payload**: i risultati dei tool vengono troncati oltre
  `max_tool_result_chars` (default 20000) per non inviare dump enormi.
- **Prompt injection**: i dati del cluster sono trattati come input non
  attendibile; il modello è istruito a non eseguire azioni e la modalità
  read-only limita comunque i danni.

## Endpoints

| Endpoint | Metodo | Descrizione |
|---|---|---|
| `/api/plugins/pve2llm/info` | GET | Metadati (include `assistant_name: "Winky"`) |
| `/api/plugins/pve2llm/config` | GET/POST | Configurazione provider/assistente |
| `/api/plugins/pve2llm/test` | POST | Verifica la connessione al provider |
| `/api/plugins/pve2llm/sync` | POST | No-op (plugin read-only) |
| `/api/plugins/pve2llm/tools` | GET | Tool MCP read-only disponibili |
| `/api/plugins/pve2llm/chat` | POST | Domanda a Winky (`{message, history}`) |
| `/admin/pve2llm` | GET | UI di configurazione e chat |

## Aggiungere tool a un plugin

Nel suo `plugin.yaml`:

```yaml
mcp:
  enabled: true
  tools:
    - name: list_things
      description: Cosa restituisce il tool.
      handler: "mcp_tools:list_things"   # module:function relativo al plugin
      capability: dns_records
      read_only: true
      input_schema:
        type: object
        properties: {}
        additionalProperties: false
```

Il core risolve l'handler e lo registra in-process; Winky lo rende disponibile
al modello automaticamente.
