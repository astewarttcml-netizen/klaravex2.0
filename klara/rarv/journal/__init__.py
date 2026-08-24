"""
app/agents/journal/
────────────────────
RARV journal team — the only entity allowed to write to the klaravex-vault.

Four agents implement the RARV cycle for a single note_submissions row:

  Reasoner  -> validates structure, decides accept / reject / clarify
  Writer    -> composes the final markdown + frontmatter
  Reflector -> reviews against existing vault notes for dupes / conflicts
  Verifier  -> computes vault path, final go / no-go before commit

The agents themselves are pure analysis — no DB writes, no git commands.
The heartbeat task (app/tasks/rarv_heartbeat.py) claims pending rows,
runs them through the four agents, then mutates DB state + commits the
markdown to the vault.

See CLAUDE.md "Single write path" and vault CONTEXT.md workstream B.
"""
from klara.rarv.journal.reasoner import RARVReasonerAgent
from klara.rarv.journal.writer import RARVWriterAgent
from klara.rarv.journal.reflector import RARVReflectorAgent
from klara.rarv.journal.verifier import RARVVerifierAgent

__all__ = [
    "RARVReasonerAgent",
    "RARVWriterAgent",
    "RARVReflectorAgent",
    "RARVVerifierAgent",
]
