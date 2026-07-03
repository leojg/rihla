# rihla-mcp

The MCP server for **[Rihla](https://github.com/leojg/rihla)** — flexible multi-leg,
multi-airport flight search that finds the cheapest route across an entire itinerary.

This is a launcher package: it installs `rihla[mcp]` and provides the `rihla-mcp`
command, so MCP clients can run the server directly:

```bash
uvx rihla-mcp
```

or in any MCP client config:

```json
{
  "mcpServers": {
    "rihla": {
      "command": "uvx",
      "args": ["rihla-mcp"],
      "env": { "TRAVELPAYOUTS_TOKEN": "your-token" }
    }
  }
}
```

It exposes two read-only tools: `resolve_airports` (quota-free IATA validation and
enrichment) and `search_trip` (the priced multi-leg search). Runs offline against
mock data with no keys; live prices need a free
[Travelpayouts](https://www.travelpayouts.com) token, optionally complemented by a
[SerpApi](https://serpapi.com) key for routes the primary source misses.

Full documentation, the CLI, and the Python API live in the main package:
**[rihla on PyPI](https://pypi.org/project/rihla/)** ·
**[github.com/leojg/rihla](https://github.com/leojg/rihla)**.

mcp-name: io.github.leojg/rihla

## License

Licensed under the Apache License 2.0 — see [LICENSE](LICENSE).
