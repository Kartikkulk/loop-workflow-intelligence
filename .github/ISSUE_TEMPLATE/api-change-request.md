---
name: API change request
about: Frontend needs a field or endpoint that does not exist yet
labels: 'api-contract'
---

## What the console needs

<!-- The exact shape. Be concrete — this becomes the Pydantic model. -->

```json
{
  "field_name": "type and example value"
}
```

## Which endpoint

<!-- e.g. GET /api/v1/clusters/{id} -->

## Why the console cannot derive it

<!-- If it can be computed from data already returned, do that instead: fewer
     round trips and no contract change. Say why it can't. -->

## Blocking?

- [ ] Blocking — the screen cannot ship without it
- [ ] Not blocking — there is a reasonable fallback in the meantime

<!-- Do not add this to apps/web/lib/api/types.ts before the backend lands it.
     A type that lies is worse than a type that is missing, because tsc then
     stops protecting you. -->
