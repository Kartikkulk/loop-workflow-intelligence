# Not the folder to load

This directory holds only the files specific to Edge — today just
`manifest.json`. The observing logic lives in `collectors/shared/` and is
copied in at build time.

Loading *this* folder unpacked fails with:

```
Could not load JavaScript 'content.js' for script.
Could not load manifest.
```

because `content.js` is not here. Build first, then load the output:

```bash
make collectors
```

Then `edge://extensions` -> Developer mode -> **Load unpacked** ->
`collectors/dist/edge`

See ../README.md for why the split exists.
