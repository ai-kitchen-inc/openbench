# memory-scratchpad

Persistent, user-editable markdown memory the agent can read, write,
and append to across turns and sessions. Use this to remember facts
that the user wants preserved — preferences, ongoing project context,
prior decisions, discovered constraints — without relying on the
conversation history (which is capped by context window length).

The scratchpad is stored as plain markdown. The user can open the
file in any editor and edit it directly, so content must stay
human-readable. Avoid dumping JSON, encoding raw data, or writing
content that only makes sense to the model.

Keys organize memory hierarchically. Use `default` for general notes,
and named keys for topical memory (e.g. `preferences`, `projects/q1`).

## Triggers

- User says "remember that ...", "keep in mind ...", "note that ...",
  or asks you to track something for later
- User references earlier context that is outside the current
  conversation ("as I mentioned last time ...")
- You discover a durable fact about the user or their project that
  will matter on future turns (preferred language, domain conventions,
  naming rules, tooling versions)
- User explicitly asks what you remember, or asks you to forget
  something

## Tools

- `read_memory(key)` — read the current content of a key
- `write_memory(key, content)` — overwrite a key's content
- `append_memory(key, content)` — add a new block to a key
- `list_memory_keys()` — list all available keys

## Dependencies

- (none — relies on the agent's injected ScratchpadStore)

## Version

0.1.0
