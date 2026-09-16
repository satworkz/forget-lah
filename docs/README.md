# forget-lah documentation

**Want to change the test records?** Use [CLINIC_SIMULATOR.md](CLINIC_SIMULATOR.md) to edit schedules and notes, add slots and create fresh scenarios.

**Connecting your own Claude account? Start with [CLAUDE_SETUP.md](CLAUDE_SETUP.md)** for account/key setup, the connection check and the remaining delivery steps.

**Already running the app? Start with [AGENT_RUNTIME.md](AGENT_RUNTIME.md)** for the new agent buttons, three demo flows and technical explanation. On a new computer, first use [TEAM_START_HERE.md](TEAM_START_HERE.md) for installation. Its [PDF version](forget-lah_Team_Quick_Start.pdf) is the preserved v0.1 foundation guide; the M2a agent instructions are in AGENT_RUNTIME.md.

Markdown (`.md`) files are editable documents. GitHub displays them as formatted pages; in VS Code, press **Ctrl+Shift+V** to preview them. The application does not need these documents to run, but keeping them with the source helps the team maintain instructions alongside code changes.

| Document | Purpose | Who needs it? |
| --- | --- | --- |
| [PATIENT_SIMULATOR.md](PATIENT_SIMULATOR.md) | Test reminder, confirmation, acknowledgement and automatic completion | Everyone testing follow-up |
| [CLAUDE_SETUP.md](CLAUDE_SETUP.md) | Own Claude account, private configuration, live check, provider switching and delivery order | Everyone setting up live inference |
| [AGENT_RUNTIME.md](AGENT_RUNTIME.md) | Current agent demo, technical components, contracts, state and organiser configuration | Everyone using M2a |
| [CASE_JOURNEY.md](CASE_JOURNEY.md) | Read the full case history, component activities and input/output evidence | Everyone learning or debugging a flow |
| [DEMO_RESET.md](DEMO_RESET.md) | Enable the reset button and recreate a clean demo safely | Demo presenters |
| [contracts/agent-decision-v1.json](contracts/agent-decision-v1.json) | Complete machine-readable model decision schema | Agent/API developers |
| [TEAM_START_HERE.md](TEAM_START_HERE.md) | Install, start, sign in and test the available flows | Everyone getting started |
| [FIRST_RUN.md](FIRST_RUN.md) | Short link to the team guide; retained for existing references | No separate reading required |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | What is implemented and what is still pending | Developers and demo presenters |
| [LIVE_CLAUDE_VALIDATION.md](LIVE_CLAUDE_VALIDATION.md) | Verified direct-Claude dental journey, usage, fixes and steps to repeat it | Developers and demo presenters |
| [VALIDATION.md](VALIDATION.md) | Recorded test results and their limits | Developers and testers |
| [NEXT_MILESTONE.md](NEXT_MILESTONE.md) | Upcoming implementation work | Developers planning the next milestone |
| [design/](design/forget-lah_README.md) | Detailed architecture, contracts, data design and planning | Developers needing design background |

The design folder is the preserved earlier design pack. Its `forget-lah` filenames and wording are historical; the current project and repository are **forget-lah**, and Python imports use **forget_lah**. Use the team guide for executable startup steps and IMPLEMENTATION_STATUS.md for current behaviour. Do not treat every feature described in the design pack as already implemented.

Keep the Markdown sources for maintenance and the PDF for easy sharing. No documentation files need to be deleted to run the app.
