# Remediation agent

The intended role of the [remediation agent](remediation_agent.py) is to
propose portfolio trades based on the risk assessment and investor profile.
The existing legacy code includes a mock trade and a prompt for the model.

## Current status

This is legacy code and is not currently runnable: it imports removed schemas
and the removed `run_agent` helper, and references the removed `USE_MOCK`
configuration. It needs migration to the current data contracts and validation
of its proposed trades before integration.
