Type: grilling
Status: open
Blocked by: 65

## Question

User scenario: a database of 6+ tables, 10+ columns each, each table with
its own business meaning and JOIN rules; the user wants SKILLS as procedural
memory so the agent explores and reaches the SSOT (a table, or a wiki like
the LangGraph docs). What reusable prebuilt nodes fall out? Candidates to
design: a **Schema Explorer** tool family (generalize chinook's
list/schema/FK tools to any SQL source), a **Skill Library** node (procedural
memory: business + JOIN rules as retrievable skill files, deepagents-style
3-level disclosure), a **Glossary/SSOT** node (wiki or table-backed
definitions with citation), and a prebuilt **Data Analyst Team** composing
them (Team node, ticket 56). Decide after ticket 65 lands the memory
mapping.
