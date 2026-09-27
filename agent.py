"""Triage agent that reads a ticket and applies the triage policy.

The agent is built with LangChain's create_agent, uses MCP tools to read tickets
from app.db, and returns a TriageDecision as structured output.
"""

import os
import sys
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient, StdioConnection
from pydantic import ValidationError

from triage_schema import TriageDecision


def _build_model():
    """Build the LLM model based on PROVIDER and MODEL env vars.

    PROVIDER controls which LLM to use:
    - 'gemini' (default): ChatGoogleGenerativeAI, reads GEMINI_API_KEY
    - 'groq': ChatGroq, reads GROQ_API_KEY

    MODEL overrides the provider's default model ID.

    Raises:
        ValueError: If PROVIDER is not 'gemini' or 'groq'
    """
    provider = os.getenv("PROVIDER", "gemini").lower()

    if provider == "gemini":
        model_id = os.getenv("MODEL", "gemini-3.8-flash")
        return ChatGoogleGenerativeAI(model=model_id)
    elif provider == "groq":
        model_id = os.getenv("MODEL", "openai/gpt-oss-120b")
        return ChatGroq(model=model_id)
    else:
        raise ValueError(
            f"Unknown PROVIDER: {provider!r}. "
            f"Supported providers: 'gemini', 'groq'"
        )


def _build_prompt() -> str:
    """Read the triage policy from TRIAGE_POLICY.md.

    Returns:
        The policy text as a string, used as the agent's system prompt.
    """
    policy_path = Path(__file__).parent / "TRIAGE_POLICY.md"
    return policy_path.read_text()


def _extract_decision(result: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate the structured output from the agent result.

    Args:
        result: The dict returned by agent.ainvoke()

    Returns:
        A JSON-serializable dict with keys: category, priority, route, rationale

    Raises:
        ValueError: If structured_response is missing
        ValidationError: If the response fails TriageDecision validation
    """
    structured = result.get("structured_response")
    if structured is None:
        raise ValueError("Agent did not return structured output")

    # If it's already a TriageDecision object, use it directly
    if isinstance(structured, TriageDecision):
        return structured.model_dump()

    # If it's a dict, validate and convert
    decision = TriageDecision(**structured)
    return decision.model_dump()


async def triage(ticket_id: str) -> dict[str, Any]:
    """Triage a support ticket and return a TriageDecision.

    Reads the ticket via get_ticket, looks up the customer via
    get_customer_history, applies the triage policy, and returns
    a decision as a dict.

    If the first attempt's structured output fails validation, retries once.
    A second validation failure stops the run with a clear error.

    Args:
        ticket_id: The ticket ID (e.g., "T-1042")

    Returns:
        A dict with keys: category, priority, route, rationale

    Raises:
        ValueError: If the structured output fails validation twice,
                   or if the agent returns no structured_response
        FileNotFoundError: If app.db is not found
    """
    # Build the MCP client for the triage server
    project_root = Path(__file__).parent
    mcp_server_path = project_root / "mcp" / "triage_server.py"

    client = MultiServerMCPClient(
        {
            "triage": StdioConnection(
                transport="stdio",
                command=sys.executable,
                args=[str(mcp_server_path)],
                cwd=str(project_root),
            )
        }
    )

    tools = await client.get_tools()

    model = _build_model()
    system_prompt = _build_prompt()

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        response_format=TriageDecision,
    )

    # Try to run the agent, with one retry on validation failure
    last_error = None
    for attempt in range(2):
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": f"Triage ticket {ticket_id}"}]},
                config={"recursion_limit": 10},
            )

            # Extract and validate the structured response
            return _extract_decision(result)

        except (ValidationError, ValueError) as e:
            last_error = e
            if attempt == 0:
                # First failure, retry
                continue
            else:
                # Second failure, raise with context
                if isinstance(e, ValidationError):
                    # Extract the field name from the validation error
                    field_name = None
                    if e.errors():
                        field_name = e.errors()[0].get("loc", (None,))[0]
                    raise ValueError(
                        f"Structured output validation failed twice "
                        f"on field '{field_name}': {e}"
                    ) from e
                else:
                    raise ValueError(
                        f"Structured output validation failed twice: {e}"
                    ) from e
