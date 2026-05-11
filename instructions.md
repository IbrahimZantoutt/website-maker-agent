# Agent Instructions

These rules apply to all agents. Read them before starting work. Follow any rule that is relevant to your task — skip rules that don't apply to what you're doing.

---

## UI & Styling Rules

- **Equal gaps**: When adding padding or gap to cards, containers, or any layout element, always make vertical and horizontal spacing equal. Do not use asymmetric values like `gap: 8px 16px` — use `gap: 8px` or `padding: 12px`.
- **Consistent border-radius**: Use the same border-radius across similar elements (e.g. all cards use `8px`, all buttons use `6px`). Do not mix different values within the same component family.
- **No inline styles for theme values**: Use CSS variables (e.g. `var(--accent)`, `var(--bg2)`) rather than hardcoded color hex values in inline styles.

## Code Quality Rules

- **Read before editing**: Always read a file in full before making any edits. Never patch based on assumptions.
- **No placeholder code**: Do not leave `TODO`, `pass`, or stub implementations in place. Either implement fully or do not add the block at all.
- **No debug prints in final output**: Remove any `print()`, `console.log()`, or `debugger` statements you add before finishing.

## File Handling Rules

- **Do not create redundant files**: Before creating a new file, check whether a suitable file already exists that could be extended.
- **Keep files focused**: Do not combine unrelated logic into one file. If a module grows beyond its original purpose, split it rather than expanding it.

---

*Add new rules above this line. Be specific — vague rules are ignored.*
