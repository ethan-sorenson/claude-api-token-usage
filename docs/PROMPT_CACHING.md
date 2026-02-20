# Prompt Caching for MCP Servers

## Overview

Your application now supports **Anthropic's Prompt Caching** to reduce API costs by up to **90%** for repeated conversation context.

**Important Note**: MCP tool definitions are loaded automatically by Claude and **cannot be directly cached** via the API. However, prompt caching works extremely well for **conversation history**, which grows with each turn and represents the majority of input tokens in long conversations.

## How It Works

### What Gets Cached?

When you enable prompt caching:
- **Conversation history** - All previous messages up to the second-to-last user message
- This includes both user messages and Claude's responses
- Cache persists for 5 minutes of inactivity

### MCP Tool Definitions

MCP tools are handled by Claude internally and:
- ❌ Cannot be cached via `cache_control` breakpoints
- ✅ Are efficiently managed by Claude's backend
- ✅ Don't grow over time (static per server)

### Caching Behavior

```
First Request (Cache Write) - 3-turn conversation:
┌─────────────────────────────────────────┐
│ Messages 1-2 (user + assistant)        │ ← Cached
│ (2,000 tokens)                          │
├─────────────────────────────────────────┤
│ Message 3 (current user message)       │
│ (100 tokens)                            │
└─────────────────────────────────────────┘
Cache Creation: 2,000 tokens × $0.00000375 = $0.0075
Input: 100 tokens × $0.000003 = $0.0003
Output: 500 tokens × $0.000015 = $0.0075
**Total Cost: $0.0153**

Second Request (Cache Hit) - 5-turn conversation:
┌─────────────────────────────────────────┐
│ Messages 1-4 (previous conversation)   │ ← Read from cache (90% discount!)
│ (4,500 tokens)                          │
├─────────────────────────────────────────┤
│ Message 5 (current user message)       │
│ (100 tokens)                            │
└─────────────────────────────────────────┘
Cache Read: 4,500 tokens × $0.0000003 = $0.00135
Input: 100 tokens × $0.000003 = $0.0003
Output: 500 tokens × $0.000015 = $0.0075
**Total Cost: $0.00915**

💰 **Savings grow with conversation length!**
10-turn conversation: ~60% cost savings
20-turn conversation: ~75% cost savings
```

## Configuration

### Enable/Disable Caching

In the UI, check the **"💾 Enable Prompt Caching"** checkbox below the "Enable MCP Servers" option.

- **Checked** (default): Caches conversation history
- **Unchecked**: No caching, pay full price for all tokens

### Global Override

In [app.py:58-60](app.py#L58-L60):
```python
# Prompt caching configuration
USE_PROMPT_CACHING = True  # Set to False to disable caching globally
```

Set to `False` to disable all caching regardless of UI checkbox.

### Cache Lifespan

- **Duration**: 5 minutes
- **Automatic**: Cache is refreshed if inactive for > 5 minutes
- **Scope**: Per conversation (different conversations don't share cache)

## Viewing Cache Metrics

The UI displays 3 new metrics when caching is active:

### 💾 Cache Write (Green)
- Tokens written to cache (first request with MCP)
- Costs 25% more than regular input tokens
- Only happens once per cache creation

### ⚡ Cache Hits (Cyan)
- Tokens read from cache (subsequent requests)
- Costs 90% less than regular input tokens
- Shows efficiency of caching

### 💰 Cache Savings (Yellow)
- Actual dollar savings from cache hits
- Calculated as: `(cache_hits × regular_price) - (cache_hits × cache_price)`

## Pricing

| Token Type | Price per 1M tokens | Notes |
|------------|---------------------|-------|
| **Input** | $3.00 | Regular input tokens |
| **Output** | $15.00 | Generated response tokens |
| **Cache Write** | $3.75 | 25% premium for caching |
| **Cache Read** | $0.30 | 90% discount! |

## Best Practices

### ✅ When to Use Caching

1. **Multiple turns with same MCP servers** - Cache persists across conversation
2. **Large tool sets** - More tools = more tokens = more savings
3. **Complex tool schemas** - Detailed descriptions benefit most

### ❌ When NOT to Use Caching

1. **Single-turn conversations** - Cache write penalty not worth it
2. **Frequently changing MCP configs** - Cache invalidates on changes
3. **Simple tools** - Overhead may exceed benefits

## Example Scenarios

### Scenario 1: HubSpot MCP (100+ tools)

```
Tool definitions: ~8,000 tokens

First Request:
- Cache Write: 8,000 tokens × $0.00000375 = $0.03
- Regular Input: 500 tokens × $0.000003 = $0.0015
- Total Input Cost: $0.0315

Next 10 Requests:
- Cache Read: 80,000 tokens (8k × 10) × $0.0000003 = $0.024
- Regular Input: 5,000 tokens × $0.000003 = $0.015
- Total Input Cost: $0.039

Without Caching (11 requests):
- 88,000 tokens × $0.000003 = $0.264

💰 Savings: $0.264 - $0.039 - $0.0315 = $0.1935 (73% cheaper!)
```

### Scenario 2: Popdock MCP (10 tools)

```
Tool definitions: ~1,000 tokens

First Request:
- Cache Write: 1,000 tokens × $0.00000375 = $0.00375
- Regular Input: 500 tokens × $0.000003 = $0.0015
- Total: $0.00525

Next 10 Requests:
- Cache Read: 10,000 tokens × $0.0000003 = $0.003
- Regular Input: 5,000 tokens × $0.000003 = $0.015
- Total: $0.018

Without Caching (11 requests):
- 11,000 tokens × $0.000003 = $0.033

💰 Savings: $0.033 - $0.018 - $0.00525 = $0.00975 (30% cheaper)
```

## Technical Details

### Implementation

The caching is implemented using **cache control breakpoints**:

```python
# In app.py
for i, server in enumerate(mcp_servers):
    # Only add cache_control to the last server (most efficient)
    if i == len(mcp_servers) - 1:
        server['cache_control'] = {"type": "ephemeral"}
```

This tells Claude to cache everything up to and including the last MCP server configuration.

### API Headers

```python
headers = {
    'anthropic-beta': 'mcp-client-2025-04-04,prompt-caching-2024-07-31'
}
```

The `prompt-caching-2024-07-31` beta enables the caching feature.

### Response Metadata

Claude returns cache metrics in the `usage` object:

```json
{
  "usage": {
    "input_tokens": 1500,
    "output_tokens": 500,
    "cache_creation_input_tokens": 8000,  // First request
    "cache_read_input_tokens": 8000       // Subsequent requests
  }
}
```

## Monitoring

### Logs

Check [logs/app.log](logs/app.log) for cache performance:

```
Anthropic API: Success - Input: 1,500 tokens (Cache Create: 8,000, Cache Read: 0), Output: 500 tokens
Anthropic API: Success - Input: 1,600 tokens (Cache Create: 0, Cache Read: 8,000), Output: 450 tokens
```

### UI Dashboard

The main interface shows:
- Real-time cache metrics
- Cost savings calculation
- Visual indicators when caching is active

## Troubleshooting

### Cache Not Working?

1. **Check `USE_PROMPT_CACHING` is `True`** in [app.py](app.py#L60)
2. **Verify MCP servers are enabled** - No servers = nothing to cache
3. **Check API response** - Look for `cache_creation_input_tokens` in logs
4. **Wait for second request** - Cache only shows savings after first request

### High Cache Write Costs?

This is normal for the first request! The savings come from subsequent requests reading from cache.

### Cache Invalidation?

Cache expires after 5 minutes of inactivity. This is controlled by Claude and cannot be changed.

## Future Enhancements

Potential improvements:
- [ ] Cache conversation history (not just MCP tools)
- [ ] System prompt caching
- [ ] Multiple cache breakpoints for different content types
- [ ] Cache analytics and optimization suggestions

## References

- [Anthropic Prompt Caching Documentation](https://docs.anthropic.com/claude/docs/prompt-caching)
- [MCP Client Beta](https://docs.anthropic.com/claude/docs/model-context-protocol)
- [Token Pricing](https://www.anthropic.com/pricing)
