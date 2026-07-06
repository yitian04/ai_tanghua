# Local CLI tools

This project can use external vectorization tools without changing the Windows
system `PATH`. Put the executable and its required DLL files under `tools/`.

Recommended layout:

```text
tools/
  VTracer/
    vtracer.exe
  Potrace/
    potrace.exe
```

Detection order:

1. Project-local `tools/` directories
2. System `PATH`
3. Common Windows install locations such as `C:/Program Files` and `D:/Program Files`

AutoTrace has been removed from the workflow because the Windows executable is
not reliable in this environment. Potrace and VTracer are outline SVG backends;
they do not produce true centerlines from thick strokes.

The `tools/` binaries are ignored by git. Keep only this README under version
control.