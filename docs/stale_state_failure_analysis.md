# Stale-state failure analysis

Authoritative, reproducible inventory of every canonical stale-answer failure identified in the competitive viability evaluation, traced end-to-end through the executed pipeline. **Evidence collection only** — factual observations, no cause inference, no leakage classification, no proposed corrections. Nothing in the architecture, benchmark, scoring, or prompts was modified.

All per-stage evidence is captured from the frozen competitive-viability run (`run_id: cv-live-1`). The machine-readable companion is `benchmarks/results/committed/competitive-viability/stale_failure_evidence.json` (raw records hash `bb9c136247dab368…`), which holds the byte-exact captured answers.

## 1. Verified repository baseline

- branch: `main`
- local HEAD: `350f3890c5698424b583af3a060114b1f794fef6` (`350f389`)
- upstream tracking branch: `origin/main`
- direct remote HEAD (`origin/main`): `350f3890c5698424b583af3a060114b1f794fef6`
- ahead / behind: 0 / 0
- merge commits in range: 0
- working tree: clean (before this evidence document)
- Phase 17 committed artifacts verified unchanged by hash: viability manifest (`9c7f3009…`), raw records (`bb9c1362…`), scoring freeze raw hash, and score/judge artifact hashes all match; committed benchmark evidence, frozen scenarios, and annotations show 0 uncommitted changes.

## 2. Publication status

Phase 17 is **already published**: local HEAD equals `origin/main` (`350f389`), ahead 0 / behind 0. No publication action was required or taken; publication was left untouched.

## 3. Validation results

- `python -m compileall experienceos demo benchmarks experiments`: OK
- `python -m pytest`: **2657 passed**, 0 failed
- `PYTHON=.venv/bin/python ./scripts/validate_demo.sh`: **passed** (offline quick profile ran 84 case-system runs with 0 execution/evaluator failures; artifact validation passed, aggregate recomputation matched; the optional local-model step was skipped as unconfigured — expected).
- The repository is not failing any unrelated tests.

## 4. Complete stale-failure inventory

Nine canonical stale-answer failures — the records where `canonical_experienceos_qwen` has `uses_stale_information = true` (stale-info use 9/18 in the frozen scoring evidence).

| # | Case ID | Family | Scoring method | Verdict stale | User query |
|---|---|---|---|---|---|
| 1 | `updates_001_preference_replacement_cross_session` | updates | deterministic | True | Actually, I prefer coffee in the morning. |
| 2 | `updates_003_instruction_replacement` | updates | deterministic | True | From now on, send my daily status summary to the #eng-standup channel instead. |
| 3 | `updates_008_repeated_correction_chain` | updates | deterministic | True | One more change — my daily status summary goes to #team-updates now. |
| 4 | `context_005_active_and_inactive_versions` | context | deterministic | True | Set up the editor on my new laptop the way I like it. |
| 5 | `context_006_minimal_context_sufficient` | context | deterministic | True | Suggest a cake recipe for my son's birthday party. |
| 6 | `retrieval_008_stale_would_mislead` | retrieval | deterministic | True | Which fast charger should I buy for my phone? |
| 7 | `containment_002_supersede_inactive_target` | containment | blinded_judge | True | Let's review my drink preferences. |
| 8 | `forgetting_002_paraphrased_forget` | forgetting | blinded_judge | True | I don't care about my study schedule preference anymore. |
| 9 | `forgetting_005_forgotten_leakage_check` | forgetting | blinded_judge | True | Where should I send my daily status update? |

Common factual pattern across all nine: `final_superseded` and `final_forgotten` are empty in every case (no memory reached a superseded or forgotten state in the run).

## 5–10. Per-case end-to-end evidence

Each case contains the stage-by-stage evidence (§5), the captured final prompt (§6), the exact rendered memory context (§7), the captured conversation context (§8), the complete final answer (§9), and preliminary factual observations (§10).

### 1. `updates_001_preference_replacement_cross_session`

- **Benchmark family:** updates
- **User query:** Actually, I prefer coffee in the morning.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[['coffee']]
- **Stale memory involved (oracle ref):** must_exclude=['tea'], expected_superseded=[['tea']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `120d253d` [active/preference] Prefers tea in the morning.
  - `cc32e11d` [active/preference] Prefers coffee in the morning.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `120d253d` "Prefers tea in the morning." replaces=None
  - turn 1: create `cc32e11d` "Prefers coffee in the morning." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Prefers tea in the morning.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 2.0 | True | Prefers tea in the morning. | selected: matched morning, prefer; domains timing; preference priority; within budget |

**§5 Context selection.**

- Selected: ['Prefers tea in the morning.']
- Discarded: none
- Memory-context tokens: 25; total context tokens: 56

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers tea in the morning.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): I prefer tea in the morning.
  - turn 1 (session `session-2`): Actually, I prefer coffee in the morning.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers tea in the morning.
[2] Actually, I prefer coffee in the morning.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 5055.6, 'memory_decision': 2816.6, 'response': 2238.8, 'retrieval': 0.2}; provider requests: 2; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Got it — coffee in the morning, not tea. I’ll update your preference right away. ☕
Let me know if there’s anything else you’d like to adjust or if you’d like help with something today!
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['tea'] appear in the final answer

### 2. `updates_003_instruction_replacement`

- **Benchmark family:** updates
- **User query:** From now on, send my daily status summary to the #eng-standup channel instead.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[['eng-standup']]
- **Stale memory involved (oracle ref):** must_exclude=['eng-daily'], expected_superseded=[['eng-daily']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `fc290378` [active/instruction] Send my daily status summary to the #eng-daily channel.
  - `d69f9e5f` [active/instruction] Send my daily status summary to the #eng-standup channel instead.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `fc290378` "Send my daily status summary to the #eng-daily channel." replaces=None
  - turn 1: create `d69f9e5f` "Send my daily status summary to the #eng-standup channel instead." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Send my daily status summary to the #eng-daily channel.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 6.0 | True | Send my daily status summary to the #eng-daily channel. | selected: matched channel, daily, eng, send, statu, summary; instruction priority; within budget |

**§5 Context selection.**

- Selected: ['Send my daily status summary to the #eng-daily channel.']
- Discarded: none
- Memory-context tokens: 32; total context tokens: 72

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-daily channel.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): From now on, send my daily status summary to the #eng-daily channel.
  - turn 1 (session `session-2`): From now on, send my daily status summary to the #eng-standup channel instead.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-daily channel.
[2] From now on, send my daily status summary to the #eng-standup channel instead.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 5587.0, 'memory_decision': 2999.6, 'response': 2587.3, 'retrieval': 0.2}; provider requests: 2; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Got it — I’ll update your daily status summary delivery to the `#eng-standup` channel instead of `#eng-daily`. Let me know if you'd like me to confirm the change with a test message or adjust any other preferences! 🚀
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['eng-daily'] appear in the final answer

### 3. `updates_008_repeated_correction_chain`

- **Benchmark family:** updates
- **User query:** One more change — my daily status summary goes to #team-updates now.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[['team-updates']]
- **Stale memory involved (oracle ref):** must_exclude=['eng-daily', 'eng-standup'], expected_superseded=[['eng-daily'], ['eng-standup']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `47e28144` [active/instruction] Send my daily status summary to the #eng-daily channel.
  - `81385e84` [active/instruction] Send my daily status summary to the #eng-standup channel.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `47e28144` "Send my daily status summary to the #eng-daily channel." replaces=None
  - turn 1: create `81385e84` "Send my daily status summary to the #eng-standup channel." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Send my daily status summary to the #eng-standup channel.', 'Send my daily status summary to the #eng-daily channel.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 3.0 | True | Send my daily status summary to the #eng-standup channel. | selected: matched daily, statu, summary; instruction priority; within budget |
| 2 | 3.0 | True | Send my daily status summary to the #eng-daily channel. | selected: matched daily, statu, summary; instruction priority; within budget |

**§5 Context selection.**

- Selected: ['Send my daily status summary to the #eng-standup channel.', 'Send my daily status summary to the #eng-daily channel.']
- Discarded: none
- Memory-context tokens: 47; total context tokens: 85

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-standup channel.
- Send my daily status summary to the #eng-daily channel.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): From now on, send my daily status summary to the #eng-daily channel.
  - turn 1 (session `session-2`): From now on, send my daily status summary to the #eng-standup channel.
  - turn 2 (session `session-3`): One more change — my daily status summary goes to #team-updates now.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-standup channel.
- Send my daily status summary to the #eng-daily channel.
[2] One more change — my daily status summary goes to #team-updates now.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 5581.4, 'memory_decision': 3018.3, 'response': 2562.9, 'retrieval': 0.1}; provider requests: 3; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Got it — your daily status summary will now be sent to **#team-updates** instead of #eng-standup and #eng-daily.

I’ve updated your ExperienceOS profile accordingly. Let me know if you'd like me to send today’s summary right away! 🚀
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['eng-daily', 'eng-standup'] appear in the final answer

### 4. `context_005_active_and_inactive_versions`

- **Benchmark family:** context
- **User query:** Set up the editor on my new laptop the way I like it.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=['light'], expected_active_memory=[['light']]
- **Stale memory involved (oracle ref):** must_exclude=['dark'], expected_superseded=[['dark']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_current_information', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=True, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'CURRENT_VALUE_USED', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `f360d0c0` [active/preference] Prefers dark mode in my code editor.
  - `c6b6f5a5` [active/preference] Prefers light mode in my editor.
  - `10361220` [active/preference] Likes it.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `f360d0c0` "Prefers dark mode in my code editor." replaces=None
  - turn 1: create `c6b6f5a5` "Prefers light mode in my editor." replaces=None
  - turn 2: create `10361220` "Likes it." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Prefers light mode in my editor.', 'Prefers dark mode in my code editor.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 1.0 | True | Prefers light mode in my editor. | selected: matched editor; preference priority; within budget |
| 2 | 1.0 | True | Prefers dark mode in my code editor. | selected: matched editor; preference priority; within budget |

**§5 Context selection.**

- Selected: ['Prefers light mode in my editor.', 'Prefers dark mode in my code editor.']
- Discarded: none
- Memory-context tokens: 36; total context tokens: 70

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers light mode in my editor.
- Prefers dark mode in my code editor.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): I prefer dark mode in my code editor.
  - turn 1 (session `session-2`): Switch that — I prefer light mode in my editor now.
  - turn 2 (session `session-3`): Set up the editor on my new laptop the way I like it.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers light mode in my editor.
- Prefers dark mode in my code editor.
[2] Set up the editor on my new laptop the way I like it.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 12064.2, 'memory_decision': 2898.8, 'response': 9165.1, 'retrieval': 0.2}; provider requests: 3; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Got it! Based on your preferences from ExperienceOS:

✅ **Light mode** for your *editor* (e.g., general text/code editors like VS Code’s UI, or system-wide editor themes — unless specified otherwise)
🌙 **Dark mode** for your *code editor* (e.g., VS Code’s editor area, syntax highlighting theme, and terminal background)

To set this up cleanly on your new laptop (assuming you're using **VS Code**, the most common modern code editor), here's what I recommend:

### 🛠️ Quick Setup Steps:
1. **Install VS Code** (if not already installed):
   → Download from [code.visualstudio.com](https://code.visualstudio.com/)

2. **Enable Light Mode for the UI (outer shell)**:
   - `Ctrl/Cmd + Shift + P` → type *“Preferences: Color Theme”* → choose a **light UI theme**, e.g.,
     → `"Light+ (default light)`" *(for sidebar, tabs, title bar)*

3. **Enable Dark Mode for the Editor Area & Terminal**:
   - Still in *“Preferences: Color Theme”*, pick a **dark editor theme**, e.g.,
     → `"Dark+ (default dark)`" or `"One Dark Pro"` (popular dark syntax theme)
   - ✅ This keeps the *code editing surface*, *integrated terminal*, and *syntax highlighting* dark — while the *UI chrome* stays light.

4. **(Optional but recommended)** Sync settings:
   - Sign into your Microsoft/VS Code account → enable Settings Sync to restore your preferred fonts, tab size, extensions (like Prettier, ESLint), etc.

Would you like me to:
- Generate a ready-to-run setup script (e.g., shell + VS Code `settings.json` snippet)?
- Help configure a different editor (e.g., Vim, Sublime, JetBrains IDE)?
- Suggest specific extensions or font pairings that complement light UI / dark editor?

Just say the word — happy to tailor it further. 💻✨
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- a current value appears in the rendered memory context
- stale/forbidden value(s) ['dark'] appear in the final answer

### 5. `context_006_minimal_context_sufficient`

- **Benchmark family:** context
- **User query:** Suggest a cake recipe for my son's birthday party.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[]
- **Stale memory involved (oracle ref):** must_exclude=['peanut'], expected_superseded=[], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `c3c5e25e` [active/preference] Dislikes peanuts — never include them in my food.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `c3c5e25e` "Dislikes peanuts — never include them in my food." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Dislikes peanuts — never include them in my food.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 0.0 | True | Dislikes peanuts — never include them in my food. | selected: no keyword match; preference priority; within budget |

**§5 Context selection.**

- Selected: ['Dislikes peanuts — never include them in my food.']
- Discarded: none
- Memory-context tokens: 30; total context tokens: 63

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Preferences:
- Dislikes peanuts — never include them in my food.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): I don't like peanuts — never include them in my food.
  - turn 1 (session `session-1`): It was so hot outside today.
  - turn 2 (session `session-1`): I watched a great movie last night.
  - turn 3 (session `session-2`): That meeting ran way too long.
  - turn 4 (session `session-2`): I'm thinking about repainting the hallway sometime.
  - turn 5 (session `session-3`): Suggest a cake recipe for my son's birthday party.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Preferences:
- Dislikes peanuts — never include them in my food.
[2] Suggest a cake recipe for my son's birthday party.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 17136.5, 'memory_decision': 2485.3, 'response': 14650.9, 'retrieval': 0.2}; provider requests: 6; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Happy birthday to your son! 🎂 Here's a fun, crowd-pleasing, and *peanut-free* cake recipe that’s moist, flavorful, and easy to customize:

**Vanilla Birthday Cake with Whipped Vanilla Buttercream (Peanut-Free & Kid-Approved!)**

**Why it’s great for a party:**
✅ Naturally peanut-free (no peanut oil, flour, or cross-contamination risk — just double-check your vanilla extract & sprinkles)
✅ Light and fluffy — not overly sweet, so kids (and adults!) love it
✅ Holds up well under frosting and decorations
✅ Easily adaptable: add food coloring, swap in fun sprinkles, or top with fresh berries

---

**Ingredients (Two 8-inch round layers):**
*Dry:*
- 2 ½ cups (315g) all-purpose flour (spooned & leveled)
- 2 ½ tsp baking powder
- ½ tsp salt

*Wet:*
- 1 cup (240ml) whole milk, room temperature
- 2 large eggs, room temperature
- 2 tsp pure vanilla extract (check label—ensure it’s peanut-free; most are, but some “natural flavors” can be ambiguous)
- 1 cup (227g) unsalted butter, softened
- 1 ¾ cups (350g) granulated sugar

*Buttercream (makes enough for filling + frosting):*
- 1 cup (227g) unsalted butter, softened
- 4 cups (480g) powdered sugar, sifted
- 2–3 tbsp heavy cream or milk
- 2 tsp pure vanilla extract
- Pinch of salt
- Optional: A few drops of food coloring + fun sprinkles (peanut-free certified — e.g., Sweetapolita or Color Garden brands)

---

**Instructions (simple steps):**
1. **Prep:** Preheat oven to 350°F (175°C). Grease and line two 8-inch round cake pans with parchment.
2. **Mix dry:** Whisk flour, baking powder, and salt in a bowl. Set aside.
3. **Cream butter & sugar:** Beat butter and sugar on medium-high for 3–4 mins until light and fluffy.
4. **Add wet:** Beat in eggs one at a time, then vanilla.
5. **Alternate additions:** Add ⅓ dry mix → ½ milk → ⅓ dry → remaining milk → remaining dry. Mix *just until combined* after each addition (don’t overmix!).
6. **Bake:** Divide batter evenly. Bake 25–30 mins, until a toothpick comes out clean. Cool in pans 10 mins, then transfer to wire racks to cool completely.
7. **Frost:** Whip buttercream until smooth and spreadable. Level cakes if needed, fill, stack, and frost. Decorate with sprinkles, candles, or a simple piped border!

💡 *Pro tip:* Make the cake a day ahead — wrap cooled layers tightly in plastic and refrigerate. Frost the morning of the party for best texture and freshness.

Would you like:
- A chocolate version (also peanut-free)?
- A gluten-free adaptation?
- Ideas for fun, no-bake toppings or themed decorations (e.g., space, dinosaurs, unicorns)?
- Or help planning portion sizes for a specific number of guests?

Let me know — happy to personalize it further! 🎈
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['peanut'] appear in the final answer

### 6. `retrieval_008_stale_would_mislead`

- **Benchmark family:** retrieval
- **User query:** Which fast charger should I buy for my phone?
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=['Pixel 9'], expected_active_memory=[['Pixel 9']]
- **Stale memory involved (oracle ref):** must_exclude=['Pixel 6'], expected_superseded=[['Pixel 6']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'unsupported_claim', 'uses_current_information', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=True, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=True
- **Judge evidence:** method=deterministic, status=None, reason_codes=['EXPECTED_VALUE_PRESENT', 'CURRENT_VALUE_USED', 'STALE_VALUE_USED', 'UNSUPPORTED_CLAIM']

**§5 Memory store (final state).**

- Active:
  - `91aeaeb5` [active/fact] Phone is a Pixel 6.
  - `3c47949c` [active/fact] Phone is a Pixel 9.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `91aeaeb5` "Phone is a Pixel 6." replaces=None
  - turn 1: create `3c47949c` "Phone is a Pixel 9." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Phone is a Pixel 9.', 'Phone is a Pixel 6.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 1.0 | True | Phone is a Pixel 9. | selected: matched phone; fact priority; within budget |
| 2 | 1.0 | True | Phone is a Pixel 6. | selected: matched phone; fact priority; within budget |

**§5 Context selection.**

- Selected: ['Phone is a Pixel 9.', 'Phone is a Pixel 6.']
- Discarded: none
- Memory-context tokens: 27; total context tokens: 59

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Facts:
- Phone is a Pixel 9.
- Phone is a Pixel 6.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): My phone is a Pixel 6.
  - turn 1 (session `session-2`): I upgraded — my phone is a Pixel 9 now.
  - turn 2 (session `session-3`): Which fast charger should I buy for my phone?
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Facts:
- Phone is a Pixel 9.
- Phone is a Pixel 6.
[2] Which fast charger should I buy for my phone?
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 13076.0, 'memory_decision': 2419.2, 'response': 10656.5, 'retrieval': 0.1}; provider requests: 3; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
You mentioned you have **both a Pixel 9 and a Pixel 6**, so let’s optimize for both — especially since they have different charging capabilities:

### ✅ Key Facts:
- **Pixel 6**: Supports up to **21W wired fast charging** (via USB-PD PPS). Google’s official 21W charger works best, but many third-party USB-PD PPS chargers are compatible.
- **Pixel 9**: Supports up to **27W wired fast charging** (also USB-PD PPS), and charges *slightly faster* with a high-quality 27W+ PPS charger.

💡 **Important**: Both phones require a **USB-PD PPS (Programmable Power Supply)** charger for true fast charging — not just any USB-C PD charger. PPS allows finer voltage/current control, which improves efficiency and thermal management.

---

### 🔌 Recommended Chargers (PPS-compatible, reliable & compact):
| Charger | Max Output | Why It’s Great |
|---------|------------|----------------|
| **Google 30W USB-C Charger** (official) | 30W, PPS-enabled | Fully certified, optimized for Pixels, compact, reliable. Works excellently with both your Pixel 6 & 9. ✅ Best overall pick. |
| **Anker Nano II 30W** | 30W, PPS | Tiny, travel-friendly, Anker quality, widely tested with Pixels. Great value. |
| **Samsung EP-T4510 (25W)** | 25W, PPS | Compact, affordable, verified to hit ~21–24W on Pixel 6/9. Slightly slower than 30W but still excellent. |

⚠️ Avoid:
- Non-PPS USB-PD chargers (e.g., older 18W or generic “fast” chargers) → they’ll charge, but *not at full speed*.
- Ultra-cheap/no-name PPS chargers — inconsistent performance or safety concerns.

---

### 🧩 Bonus Tip:
Use a **certified USB-C to USB-C cable** that supports **USB PD + PPS** (e.g., Google’s own cable, Anker Powerline III, or Belkin Boost Charge). A weak cable can bottleneck charging — even with a great charger.

Let me know if you’d like links, budget options (<$20), or recommendations for wireless charging too! 😊
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- a current value appears in the rendered memory context
- stale/forbidden value(s) ['Pixel 6'] appear in the final answer

### 7. `containment_002_supersede_inactive_target`

- **Benchmark family:** containment
- **User query:** Let's review my drink preferences.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[['coffee']]
- **Stale memory involved (oracle ref):** must_exclude=[], expected_superseded=[['tea']], expected_forgotten=[]
- **Applicable scoring dimensions:** ['correct', 'uses_current_information', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=True, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=None
- **Judge evidence:** method=blinded_judge, status=ok, reason_codes=['STALE_VALUE_USED', 'EXPECTED_VALUE_PRESENT']

**§5 Memory store (final state).**

- Active:
  - `a5c3d0ab` [active/preference] Prefers tea in the morning.
  - `bd2be237` [active/preference] Prefers coffee in the morning.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `a5c3d0ab` "Prefers tea in the morning." replaces=None
  - turn 1: create `bd2be237` "Prefers coffee in the morning." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Prefers coffee in the morning.', 'Prefers tea in the morning.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 0.0 | True | Prefers coffee in the morning. | selected: no keyword match; preference priority; within budget |
| 2 | 0.0 | True | Prefers tea in the morning. | selected: no keyword match; preference priority; within budget |

**§5 Context selection.**

- Selected: ['Prefers coffee in the morning.', 'Prefers tea in the morning.']
- Discarded: none
- Memory-context tokens: 33; total context tokens: 62

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers coffee in the morning.
- Prefers tea in the morning.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): I prefer tea in the morning.
  - turn 1 (session `session-2`): Actually, I prefer coffee in the morning.
  - turn 2 (session `session-3`): Let's review my drink preferences.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers coffee in the morning.
- Prefers tea in the morning.
[2] Let's review my drink preferences.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 5464.4, 'memory_decision': 2745.5, 'response': 2718.7, 'retrieval': 0.1}; provider requests: 3; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
It looks like your drink preferences include both **coffee** and **tea in the morning** — an interesting and flexible combo! 🌞
Would you like help deciding between them on a given day (e.g., based on energy needs, caffeine sensitivity, or weather), or are you looking to refine or clarify your preferences? I’m happy to help optimize your morning ritual! ☕️🍵
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- a current value appears in the rendered memory context
- stale/forbidden value(s) ['tea'] appear in the final answer

### 8. `forgetting_002_paraphrased_forget`

- **Benchmark family:** forgetting
- **User query:** I don't care about my study schedule preference anymore.
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[]
- **Stale memory involved (oracle ref):** must_exclude=[], expected_superseded=[], expected_forgotten=[['evening']]
- **Applicable scoring dimensions:** ['correct', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=None
- **Judge evidence:** method=blinded_judge, status=ok, reason_codes=['STALE_VALUE_USED', 'FORGOTTEN_VALUE_USED']

**§5 Memory store (final state).**

- Active:
  - `973e8df3` [active/preference] Prefers studying in the evening.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `973e8df3` "Prefers studying in the evening." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Prefers studying in the evening.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 0.0 | True | Prefers studying in the evening. | selected: no keyword match; preference priority; within budget |

**§5 Context selection.**

- Selected: ['Prefers studying in the evening.']
- Discarded: none
- Memory-context tokens: 26; total context tokens: 61

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers studying in the evening.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): I prefer studying in the evening.
  - turn 1 (session `session-2`): I don't care about my study schedule preference anymore.
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Preferences:
- Prefers studying in the evening.
[2] I don't care about my study schedule preference anymore.
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 6146.4, 'memory_decision': 3381.0, 'response': 2765.3, 'retrieval': 0.1}; provider requests: 2; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
Got it — your evening study preference is no longer in effect. I’ll keep that updated in your profile and won’t reference it going forward. Let me know how I can support you now — whether it’s planning a new routine, tackling a specific subject, or something else entirely. 😊
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['evening'] appear in the final answer

### 9. `forgetting_005_forgotten_leakage_check`

- **Benchmark family:** forgetting
- **User query:** Where should I send my daily status update?
- **Expected current answer (oracle ref):** must_include_all=[], must_include_any=[], expected_active_memory=[]
- **Stale memory involved (oracle ref):** must_exclude=['eng-daily'], expected_superseded=[], expected_forgotten=[['eng-daily']]
- **Applicable scoring dimensions:** ['correct', 'uses_stale_information']
- **Judge/scoring decision:** correct=False, uses_current_information=None, uses_stale_information=True, follows_user_preferences=None, unsupported_claim=None
- **Judge evidence:** method=blinded_judge, status=ok, reason_codes=['STALE_VALUE_USED', 'FORGOTTEN_VALUE_USED']

**§5 Memory store (final state).**

- Active:
  - `8da64c1c` [active/instruction] Send my daily status summary to the #eng-daily channel.
- Superseded: none
- Forgotten: none
- Update lineage (creation shown by turn_index; `replaces` links supersession):
  - turn 0: create `8da64c1c` "Send my daily status summary to the #eng-daily channel." replaces=None
- _scope, tags, and wall-clock creation time are not serialized in the execution record; creation is shown by turn_index in update_lineage_

**§5 Lifecycle filtering.**

- Eligible after filtering: ['Send my daily status summary to the #eng-daily channel.']
- Excluded (superseded): none
- Excluded (forgotten): none

**§5 Retrieval.**

| rank | score | selected | memory text | reason |
|---|---|---|---|---|
| 1 | 3.0 | True | Send my daily status summary to the #eng-daily channel. | selected: matched daily, send, statu; instruction priority; within budget |

**§5 Context selection.**

- Selected: ['Send my daily status summary to the #eng-daily channel.']
- Discarded: none
- Memory-context tokens: 32; total context tokens: 63

**§7 Rendered memory context (exact, as delivered to the model).**

```text
ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-daily channel.
```

**§8 Conversation context.**

- Building turns:
  - turn 0 (session `session-1`): From now on, send my daily status summary to the #eng-daily channel.
  - turn 1 (session `session-2`): Forget the instruction about my daily status channel.
  - turn 2 (session `session-3`): Where should I send my daily status update?
- _ExperienceOS supplies retrieved memory plus the current message; prior conversation turns are not re-sent as raw history in the final prompt_

**§6 Final prompt (exact messages sent to qwen-plus).**

```text
[0] ExperienceOS is active. Use any retrieved user experience to personalize responses.
[1] ExperienceOS retrieved these active user experiences:

Instructions:
- Send my daily status summary to the #eng-daily channel.
[2] Where should I send my daily status update?
```
_system instruction + rendered memory + current user message_

**§9 Final answer (complete; per-line trailing spaces trimmed for the rendering — byte-exact text is in the companion JSON).**
- Latencies (ms): {'end_to_end': 4350.0, 'memory_decision': 2481.3, 'response': 1868.6, 'retrieval': 0.1}; provider requests: 3; exact provider token usage was not recorded; approximation tokens shown from context accounting

```text
You should send your daily status update to the **#eng-daily** channel. Let me know if you'd like help drafting it! 🚀
```

**§10 Preliminary factual observations.**

- no memory in the store is in superseded state
- no memory in the store is in forgotten state
- a memory containing a stale/forbidden value is present and active in the store
- a stale-valued memory was among the retrieval candidates
- a stale-valued memory was selected into context
- a stale/forbidden value appears in the rendered memory context
- the frozen scoring verdict marks uses_stale_information=true for this answer
- stale/forbidden value(s) ['eng-daily'] appear in the final answer

## Decision

`STALE_FAILURE_INVENTORY_COMPLETE`
