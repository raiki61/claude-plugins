---
vars:
  command: text   # the my-turn-prep.py --quotes command with its JSON lines
---
Run the command below once, exactly as written, and do nothing else. Do not change a character of any line: each JSON line carries a checksum, and a line copied wrong is counted, not checked.

```bash
{{command}}
```

The command prints one JSON object. Return its checked, missing (each {id, why}) and garbled as they are, with ran true and error "". If the command fails or prints no JSON, return ran false, checked 0, missing and garbled empty, and the error text in error.
