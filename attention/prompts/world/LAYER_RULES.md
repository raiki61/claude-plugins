---
vars:
---
## Layers

Every row compares at exactly one layer:
- `architecture`: who does what. How the parts are divided and which part owns the work.
- `contract`: what crosses a boundary. The shape of requests, responses and state between parts, and when each may be sent.
- `implementation`: how one part does its work inside.

If a counterpart has something to say at two layers, give two rows. Do not let one layer's answer stand for another layer's conclusion: what a contract allows does not say which part should do the work, and a general structure does not say what products do.
