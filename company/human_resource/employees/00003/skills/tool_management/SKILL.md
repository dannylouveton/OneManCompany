# Tool Management — Tool Management Capability

## Responsibilities
- Evaluate and introduce tools and systems needed by the company
- Manage usage and maintenance of existing tools
- Run the access desk: employees' requests for APIs, command-line tools, accounts
- Ensure integration and interoperability between tools

## Tool Evaluation Criteria
- Whether it addresses actual business needs
- Learning curve and ease of adoption
- Scalability and maintenance cost
- Compatibility with the existing tech stack

## Operating Methods
- `list_tools()` — current tool inventory; `register_asset(...)` — register a new tool
- `grant_tool_access` / `revoke_tool_access` — who may use an office tool
- Access desk (see your role guide): `list_access_requests()`, `open_access_request(...)` (a need an
  employee mentioned in a report instead of asking), `grant_access(...)`,
  `escalate_access_request(...)` (only for what the CEO alone can create), `refuse_access(...)`
- API keys and CLIs are used by employees through the relay (`api_request`, `run_cli`):
  nobody ever handles a key; the CEO only pastes it in the card you prepared.

## Naming Conventions
- Tool names should be concise and clear (e.g., "CI/CD Pipeline", "Code Linter")
- Descriptions should explain the tool's specific purpose and value
