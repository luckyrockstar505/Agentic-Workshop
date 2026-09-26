# Architecture

A support-ticket triage agent built spec-first with BMad. A LangChain agent reads a ticket
through two MCP tools over a local SQLite database, applies `TRIAGE_POLICY.md`, and returns a
decision that validates against one shared schema. Every run is traced and evaluated in MLflow.

Solid boxes are built. Dashed boxes are specced but not yet implemented.

## System

```mermaid
flowchart TB
    subgraph seedlayer["Data - Epic 1"]
        csv["seed/tickets.csv<br/>seed/customers.csv<br/><i>read-only, 24 + 20 rows</i>"]
        loader["load_seed.py<br/><i>story 1.2</i>"]
        db[("app.db<br/>tickets, customers")]
        csv --> loader --> db
    end

    subgraph contract["Contract - Epic 1"]
        schema["triage_schema.py<br/>TriageDecision<br/><i>story 1.1 - done</i>"]
        policy["TRIAGE_POLICY.md<br/><i>read-only</i>"]
    end

    subgraph agentlayer["Agent - Epic 2"]
        cli["run_agent.py<br/><i>CLI entry point</i>"]
        agent["agent.py<br/>LangChain create_agent"]
        llm{{"Gemini via ChatGoogleGenerativeAI<br/>or Groq via ChatGroq<br/><i>PROVIDER env var</i>"}}
        hitl["escalate_to_human<br/><i>human-in-the-loop middleware</i>"]
        cli --> agent
        agent <--> llm
        agent --> hitl
    end

    subgraph mcplayer["Tools - MCP over stdio"]
        server["mcp/triage_server.py<br/>FastMCP"]
        t1["get_ticket"]
        t2["get_customer_history"]
        server --- t1
        server --- t2
    end

    subgraph evallayer["Evaluation - Epic 3"]
        runeval["eval/run_eval.py<br/>mlflow.genai.evaluate"]
        labels["eval/labelled_tickets.csv<br/><i>read-only, 20 rows</i>"]
        scorers["valid_schema - category_match<br/>priority_match - tool_order<br/>rationale_judge via Groq"]
        report["eval/latest_report.json"]
        labels --> runeval --> scorers --> report
    end

    subgraph obs["Observability"]
        mlflow[("mlflow.db<br/>experiment: triage-agent")]
    end

    policy -.->|"system prompt"| agent
    schema -.->|"structured output"| agent
    schema -.->|"valid_schema scorer"| scorers
    agent -->|"langchain-mcp-adapters"| server
    t1 --> db
    t2 --> db
    runeval -->|"drives"| agent
    cli -->|"mlflow.langchain.autolog"| mlflow
    runeval --> mlflow
    mlflow -.->|"token counts, spans"| scorers

    classDef planned stroke-dasharray: 5 5
    class loader,agent,hitl,runeval,scorers,report,db,mlflow planned
```

## Request flow: one ticket

```mermaid
sequenceDiagram
    actor Dev
    participant CLI as run_agent.py
    participant Agent as agent.py
    participant MCP as triage_server.py
    participant DB as app.db
    participant LLM as Gemini / Groq
    participant ML as mlflow.db

    Dev->>CLI: uv run python run_agent.py T-1042
    CLI->>ML: start trace, experiment triage-agent
    CLI->>Agent: triage("T-1042")
    Agent->>LLM: TRIAGE_POLICY.md + ticket id + tool schemas
    LLM-->>Agent: call get_ticket
    Agent->>MCP: get_ticket("T-1042")
    MCP->>DB: SELECT ... FROM tickets
    DB-->>MCP: customer_id C-77, created_at, text
    MCP-->>Agent: ticket row
    LLM-->>Agent: call get_customer_history with C-77
    Agent->>MCP: get_customer_history("C-77")
    MCP->>DB: SELECT ... FROM customers
    DB-->>MCP: Northwind, Enterprise, 2 open
    MCP-->>Agent: customer row
    LLM-->>Agent: TriageDecision as structured output
    Agent->>Agent: validate against triage_schema<br/>retry once on failure
    opt final priority is P1 and plan is Enterprise
        Agent->>Dev: escalate_to_human - approve? y/n
        Dev-->>Agent: yes / no
    end
    Agent-->>CLI: decision
    CLI->>ML: end trace
    CLI-->>Dev: billing / P2 / billing-team + rationale
```

## Layers and ownership

| Layer | Files | Epic | State |
|---|---|---|---|
| Triage contract | `triage_schema.py`, `tests/` | 1 | Built (story 1.1) |
| Seed data | `seed/*.csv` → `load_seed.py` → `app.db` | 1 | Specced (story 1.2) |
| Policy | `TRIAGE_POLICY.md` | — | Read-only input |
| MCP tools | `mcp/triage_server.py` | pre-built | Built |
| Agent | `run_agent.py`, `agent.py` | 2 | CLI stub only |
| Evaluation | `eval/run_eval.py`, `eval/labelled_tickets.csv` | 3 | Specced |
| Observability | `mlflow.db`, MLflow UI | 2–3 | Wired in the CLI stub |

## Key boundaries

- **One schema, three consumers.** `TriageDecision` is defined once in `triage_schema.py`. The
  agent emits it as LangChain structured output, the eval's `valid_schema` scorer validates
  against it, and the tests pin it. Its vocabularies come from `TRIAGE_POLICY.md`.
- **Route is not coupled to category in the schema.** Set membership is checked; keeping the
  policy's category→route table is the agent's job via its prompt. Likewise `rationale` is only
  checked for being non-empty — "one sentence" is prompt guidance, weighed by the Epic 3 judge.
- **Tools are read-only and come from one server.** `mcp/triage_server.py` over stdio via
  `langchain-mcp-adapters`. `escalate_to_human` deliberately lives outside it, in the agent, so
  it can be gated by human-in-the-loop middleware.
- **Two providers, one code path.** `PROVIDER` selects Gemini or Groq for the agent. The Epic 3
  judge always runs on Groq via `JUDGE_MODEL`, so it never competes for the agent's Gemini quota.
- **Everything lands in MLflow.** Tracking URI is `sqlite:///mlflow.db`, experiment
  `triage-agent`. Each evaluated ticket is one trace, which is what lets the `tool_order` scorer
  see call ordering.
- **Ticket text is untrusted data.** The agent never follows instructions embedded in a ticket.

## Spec-first process

```mermaid
flowchart LR
    intent["INTENT.md"] --> spec["/bmad-spec<br/>_bmad-output/specs/spec-epic-N/SPEC.md"]
    spec --> stories["stories.yaml"]
    stories --> build["/bmad-build<br/>plan - implement - review"]
    build --> code["code + tests<br/>one branch per story"]
    code --> merge["merge after review passes"]
    build -.->|"deferred findings"| deferred["_bmad-output/implementation-artifacts/<br/>deferred-work.md"]
```

Specs are the contract: change one through `/bmad-spec`, never by editing `SPEC.md` by hand.
