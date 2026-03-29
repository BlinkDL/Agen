# Agen

Agen is a minimalist language for agent loops and state machines.

## Flow

Agen is **purely state-driven** and runs inside agen_loop:

Step 1: Find the first matching rule.
- If no rule matches, run stops.
- If `step_limit` is exceeded, runtime raises an error.

Step 2: Run its block, then go back to step 1.
- Inside the block, plain statements run in order.
- If any nested rule matches and runs, go back to step 1 too.

## Style

Agen uses UTF-8 symbols, as AI will code it.
- `(a=b)` and `(a=b)➜` are rules
- `a=b, c=d` is supported.
- Slots `■ ◆ ▲ ▼ ◀ ▶` for binding.
- `a.b` means `a[b]` when `a` is a dict; otherwise it's attribute access.
- Bare Rvalues default to literals.
    - Use `{...}` for explicit expressions and map literals.
        - Numbers, `Ø`, slots, and `[...]` are recognized directly and do not need `{}`.
    - Template strings are recognized when it contains slots or `{...}`.

## Examples

Try `npc.py` first. From `npc.agen`:
```
(npc=Ø)
    npc={name:emma, location:home}
    agenda=[wake_up, open_stall, close_stall]
    log=[], i=0

(task=Ø, i≠{len(agenda)}) ➜ task={agenda.{i}}, i+=1

(npc=■, ■.location=◆, ■.name=▲)
    (task=wake_up)
        log+=[{time:dawn, scene:◆, text:▲ wakes up and heads for the square.}]
        task=Ø

    (task=open_stall)
        ◆=market_square
        log+=[{time:morning, scene:◆, text:▲ opens the stall.}]
        task=Ø

    (task=close_stall)
        ◆=home
        log+=[{time:dusk, scene:◆, text:▲ counts coins and walks home at dusk.}]
        task=Ø
```

The corresponding Python version:
```python
for _ in range(step_limit):
    if npc == None:
        npc = {"name": "emma", "location": "home"}
        agenda = ["wake_up", "open_stall", "close_stall"]
        log = []; i = 0; continue

    if task == None and i != len(agenda):
        task = agenda[i]; i += 1; continue

    if task == "wake_up":
        log += [{"time": "dawn", "scene": npc['location'], "text": f"{npc['name']} wakes up and heads for the square."}]
        task = None; continue

    if task == "open_stall":
        npc["location"] = "market_square"
        log += [{"time": "morning", "scene": npc['location'], "text": f"{npc['name']} opens the stall."}]
        task = None; continue

    if task == "close_stall":
        npc["location"] = "home"
        log += [{"time": "dusk", "scene": npc['location'], "text": f"{npc['name']} counts coins and walks home at dusk."}]
        task = None; continue
```
---

From `s01.agen`:
```
(messages=■, response=◆)
    (■=Ø) ➜ ■=[{role:user, content:{query}}], phase=model

    (phase=model)
        (◆=Ø) ➜ ◆={QUERY(messages=■)}
        ■+=[{role:assistant, content:{◆.content}}]
        (◆.stop_reason=tool_use) ➜ phase=tool, i=0, results=[]
        phase=done

    (phase=tool)
        (i≠{len(◆.content)}, ◆.content.{i}=▲, output=▼)
            (▲.type≠tool_use) ➜ i+=1
            (▼=Ø) ➜ ▼={BASH(command={▲.input.command})}
            results+=[{type:tool_result, tool_use_id:{▲.id}, content:▼}]
            ▼=Ø, i+=1
        ■+=[{role:user, content:{results}}]
        phase=model, ◆=Ø
```

The corresponding Python version:
```python
for _ in range(step_limit):
    if messages is None:
        messages = [{"role": "user", "content": query}]; phase = "model"; continue

    if phase == "model":
        if response is None:
            response = QUERY(messages=messages); continue

        messages += [{"role": "assistant", "content": response.content}]

        if response.stop_reason == "tool_use":
            phase = "tool"; i = 0; results = []; continue

        phase = "done"; continue

    if phase == "tool":
        if i != len(response.content):
            if response.content[i]["type"] != "tool_use":
                i += 1; continue

            if output is None:
                output = BASH(command=response.content[i]["input"]["command"]); continue

            results += [{"type": "tool_result", "tool_use_id": response.content[i]["id"], "content": output}]
            output = None; i += 1; continue

        messages += [{"role": "user", "content": results}]
        phase = "model"; response = None; continue
```

## Advanced Examples

Try `s03.py`. If you can understand `s03.agen`, you are thinking in Agen 😊
```
(messages=■, response=◆, rounds_since_todo=◀)
    (■=Ø) ➜ ■=[{role:user, content:{query}}], phase=model, ◀=0

    (phase=model)
        (◆=Ø) ➜ ◆={QUERY(messages=■)}
        ■+=[{role:assistant, content:{◆.content}}]
        (◆.stop_reason=tool_use) ➜ phase=tool, i=0, results=[]
        phase=done

    (phase=tool)
        (i≠{len(◆.content)}, ◆.content.{i}=▲, output=▼)
            (▲.type≠tool_use) ➜ i+=1
            (▼=Ø) ➜ ▼={DISPATCH(name={▲.name}, input={▲.input})}
            results+=[{type:tool_result, tool_use_id:{▲.id}, content:▼}]
            ▼=Ø, i+=1
            (▲.name=todo) ➜ ◀=-1
        ■+=[{role:user, content:{results}}]
        phase=model, ◆=Ø, ◀+=1
        (◀>=3) ➜ results.insert(0, {type:text, text:<reminder>Update your todos.</reminder>})
```
