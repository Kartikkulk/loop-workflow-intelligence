## What and why

<!-- One or two sentences. Why, not just what. -->

## Scope

- [ ] Backend only (`apps/api/`)
- [ ] Frontend only (`apps/web/`)
- [ ] Collector (`collectors/`)
- [ ] Crosses the API boundary — **contract change included below**

## If this changes the API surface

- [ ] `make contract` re-run and `contracts/openapi.json` committed
- [ ] `make fixtures` re-run if a response shape changed
- [ ] Matching TypeScript types updated in `apps/web/lib/api/types.ts`

<!-- A backend change that alters a response without updating these breaks the
     frontend at runtime instead of at review time. -->

## Checks

- [ ] `make check` passes locally
- [ ] `make test-collector` passes (only if `collectors/` changed)
- [ ] No new `TODO`, bare `pass`, or placeholder return
- [ ] New env vars added to `.env.example`, with a comment
- [ ] Numbers shown in the UI are measured, not rounded up or invented

## Verified how

<!-- What you actually ran or clicked. "Tests pass" is not verification of a
     UI change; a screenshot or a described click-through is. -->
