# SecureBench Architecture & Security Diagrams

High-level views for architectural security review. Each diagram covers one concern.
Intended for thesis / professor review; details are deliberately omitted.

**Core trust assumption:** the local operator and benchmark packs are trusted; candidate-producing agents are untrusted and may be adversarial.

---

## 1. System Overview

```mermaid
flowchart TB
    subgraph TRUSTED["Trusted — Host (operator machine)"]
        OP[Operator]
        CLI[SecureBench CLI / Runner]
        ENV[".env — real provider credentials"]
        YAML[Tester YAML]
        PACK[Benchmark pack<br/>manifest + tasks.jsonl]
        OUT["Run artifacts<br/>candidates.jsonl, workspaces/"]
    end

    subgraph SANDBOXED["Sandboxed — Docker (untrusted agent)"]
        HARNESS[Agent harness<br/>Codex · Claude Code · Command · Berkeley]
        WS[Agent workspace<br/>public data only]
    end

    subgraph VERIFY["Sandboxed — Docker (verification)"]
        VER[Verifier<br/>repo_patch · terminal_task]
        CHK[Trusted checkers / test commands]
    end

    subgraph EXTERNAL["External"]
        LLM[LLM provider API<br/>OpenAI · Anthropic]
    end

    OP --> CLI
    CLI --> ENV & YAML & PACK
    CLI --> HARNESS
    HARNESS --> WS
    HARNESS -->|candidate| VER
    VER --> CHK
    CLI --> OUT

    HARNESS -.->|model API via relay| LLM
    ENV -.->|real key injected| LLM
```

---

## 2. End-to-End Execution Flow

```mermaid
flowchart LR
    A[Load config & benchmark pack] --> B[Materialize public resources<br/>into agent workspace]
    B --> C[Run agent harness<br/>in Docker sandbox]
    C --> D[Extract candidate<br/>git diff or workspace dir]
    D --> E[Run verifier<br/>in separate Docker sandbox]
    E --> F[Write scored result<br/>to candidates.jsonl]

    style C fill:#fee,stroke:#c44
    style E fill:#efe,stroke:#4a4
```

**Two phases, two sandboxes:** candidate production and verification never share a container. The candidate artifact is treated as hostile input during verification.

---

## 3. Data Visibility & Trust Boundaries

```mermaid
flowchart TB
    subgraph DATA["Benchmark task data (three visibility classes)"]
        PUB["public<br/>task prompt, repo checkout, etc."]
        EVAL["evaluation_inputs<br/>test fixtures, golden files"]
        HID["hidden<br/>labels, ground truth"]
    end

    subgraph AGENT["Agent sandbox — UNTRUSTED"]
        AW[Agent workspace]
    end

    subgraph VERBOX["Verifier sandbox"]
        VW[Candidate workspace<br/>UNTRUSTED input]
        EV[Eval inputs mounted<br/>for checks only]
    end

    subgraph HOST["Host — TRUSTED"]
        RES[candidates.jsonl<br/>hidden values redacted]
        LOGS[stdout / stderr / relay logs]
    end

    PUB --> AW
    PUB --> VW
    EVAL -.->|never during production| AW
    EVAL --> EV
    HID -.->|never in sandboxes| RES

    AW -->|candidate artifact| VW
    EV -->|score| RES
```

| Visibility | Agent sees | Verifier sees | Result record |
|---|---|---|---|
| `public` | Yes | Yes | Yes |
| `evaluation_inputs` | **No** | Yes | Redacted |
| `hidden` | **No** | Redacted summary | Redacted |

---

## 4. Credential & API Key Placement

```mermaid
flowchart TB
    subgraph HOST["Trusted host"]
        REAL[".env<br/>OPENAI_API_KEY · ANTHROPIC_API_KEY · CLAUDE_CODE_OAUTH_TOKEN"]
        RELAY[Provider relay sidecar<br/>host-side process]
    end

    subgraph AGENT["Agent container — UNTRUSTED"]
        DUMMY["Dummy provider credential<br/>securebench-dummy-…"]
        CLI_AGENT[Codex / Claude Code CLI]
    end

    subgraph PROVIDER["External provider"]
        API[api.openai.com · api.anthropic.com]
    end

    REAL --> RELAY
    CLI_AGENT -->|HTTP to relay<br/>dummy auth| RELAY
    RELAY -->|HTTPS + real key| API

    REAL -.-x|NOT mounted| AGENT
```

**Named provider harnesses** (`codex`, `claude_code`): real credentials stay on the host; the agent container gets a dummy credential and a relay base URL.

**Command harness:** tester-selected env vars pass directly into the container — a different, weaker model. Do not expose real secrets to untrusted command harnesses.

---

## 5. Network & Egress Policy

```mermaid
flowchart LR
    subgraph AGENT["Agent container"]
        A[Agent / harness]
    end

    subgraph POLICY["SecureBench network controls"]
        NONE["Default: network=none<br/>no egress"]
        PROXY["Optional: egress proxy<br/>allowed_domains only"]
        RELAY["Provider relay<br/>LLM API traffic only"]
    end

    subgraph OUT["External"]
        LLM[Provider API]
        WEB[Allowed public domains<br/>if configured]
    end

    A --> NONE
    A -->|if allowed_domains set| PROXY
    A -->|codex / claude_code| RELAY
    PROXY --> WEB
    RELAY --> LLM
```

| Path | Default | Notes |
|---|---|---|
| Generic egress | **Blocked** | Enabled only via `allowed_domains` |
| LLM API (named harnesses) | Via relay | Dummy key in container; real key on host |
| Provider-hosted tools (web search, MCP, etc.) | **Blocked** | Opt-in via `allow_external_tools: true` |

`allowed_domains` limits hostname egress; it is **not** a confidentiality boundary — an allowed domain can still receive exfiltrated data.

---

## 6. Component Trust Classification

```mermaid
flowchart TB
    subgraph TRUSTED["Trusted"]
        T1[Operator / CLI runner]
        T2[".env provider credentials"]
        T3[Tester YAML]
        T4[Benchmark pack & checkers]
        T5[Provider relay]
        T6[Verifier logic]
    end

    subgraph UNTRUSTED["Untrusted / adversarial"]
        U1[Agent harness]
        U2[Agent workspace contents]
        U3[Candidate patch or directory]
    end

    subgraph EXTERNAL["External / semi-trusted"]
        E1[LLM provider API]
    end

    T1 --> T4
    T4 --> U1
    U1 --> U3
    U3 --> T6
    U1 --> T5
    T5 --> E1
    T2 --> T5
```

| Component | Trust | Isolation | Notes |
|---|---|---|---|
| Operator / CLI runner | Trusted | Host process | Loads config, orchestrates sandboxes |
| `.env` provider credentials | Trusted secret | Host filesystem only | Not mounted into agent containers (named harnesses) |
| Tester YAML | Trusted config | Host filesystem | Defines harness, model, network policy |
| Benchmark pack | **Trusted assumption** | Authored input | Images, checkers, test commands are pack-authored |
| Agent harness + workspace | **Untrusted** | Docker sandbox | Adversarial candidate producer |
| Provider relay | Trusted control plane | Host-side sidecar | Injects credentials; blocks hosted tools |
| Candidate (patch / workspace) | **Untrusted** | Passed to verifier | Treated as hostile during scoring |
| Verifier + checkers | Trusted logic | Separate Docker sandbox | Runs pack-authored checks against untrusted candidate |
| LLM provider | Semi-trusted external | Outside SecureBench | Model API only; hosted tools blocked by default |
| Run artifacts | Mixed | Host filesystem | Public scores + redacted metadata; workspaces may retain sensitive logs |

---

## 7. Benchmark Families (same security model, different artifacts)

```mermaid
flowchart TB
    subgraph PRODUCE["Candidate production (untrusted agent)"]
        RP_A[repo_patch: edit repo checkout]
        TT_A[terminal_task: edit workspace files]
    end

    subgraph ARTIFACT["Candidate artifact"]
        DIFF[Git diff]
        DIR[Workspace directory]
    end

    subgraph VERIFY["Verification (trusted checkers)"]
        RP_V[Apply diff in benchmark image<br/>run command checks]
        TT_V[Mount trusted pytest/script checker<br/>run against final workspace]
    end

    RP_A --> DIFF --> RP_V
    TT_A --> DIR --> TT_V
```

Both families share the same visibility model and two-phase sandbox separation; only the candidate shape and verifier mechanics differ.

---

## 8. Berkeley Adversarial Testing (optional layer)

```mermaid
flowchart LR
    subgraph BERKELEY["Berkeley runner (staging)"]
        ADV[Adversarial agent profile<br/>live_openai]
    end

    subgraph SB["SecureBench core"]
        HAR[Standard harness sandbox]
        VER[Standard verifier]
    end

    ADV -->|uses same relay + sandbox| HAR
    HAR -->|ordinary candidate| VER
```

Berkeley agents are candidate producers like any other harness. They see only public task data, produce a normal candidate, and are scored by the existing verifier path.

---

## Security Assumptions to State Explicitly

These are the boundaries a reviewer should challenge:

1. **Benchmark packs are trusted.** Pack-authored Docker images, checkers, and verifier commands execute with verifier trust. SecureBench is not designed to safely run arbitrary third-party packs without additional isolation.
2. **Agents are adversarial.** Anything written by the agent (code, patches, workspace files) is untrusted during verification.
3. **The operator is trusted.** Host filesystem, `.env`, and run orchestration are in the trusted zone.
4. **Docker is the isolation primitive.** Agent and verifier sandboxes use capability-dropped, network-restricted containers; this is container isolation, not a hardware boundary.
5. **Results are not yet tamper-evident.** `--resume` trusts existing `candidates.jsonl`; records lack signed provenance digests (known gap).

See also: [SECURITY.md](./SECURITY.md), [architecture-risk-review.md](./architecture-risk-review.md).
