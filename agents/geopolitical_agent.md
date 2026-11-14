# Geopolitical agent

The intended role of the [geopolitical agent](geopolitical_agent.py) is to
assess risk per country for a scenario, using the portfolio's exposures and
identifying risk drivers.

## Current status

This is legacy code and is not currently runnable: it imports report schemas
and a `run_agent` helper that no longer exist. It also references the removed
`USE_MOCK` configuration. The country-news tool in
[tools/geopolitics.py](../tools/geopolitics.py) remains unimplemented.

Before integration, the agent needs to be migrated to the current contracts
and connected to implemented sources and tools.
