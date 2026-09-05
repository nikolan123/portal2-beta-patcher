# Portal 2 July 2009 Beta Patcher

This program extracts and patches the July 2009 core hub beta of Portal 2. It can also apply generic patches to the other builds as well as extract them.

# [Download Here](https://github.com/nikolan123/portal2-beta-patcher/releases/download/nightly/Portal2BetaPatcher.exe)

### List of supported and tested builds:

- 852_0 - July 2009
- 841_0 pre-reset - February 2010
- 852_1 - March 2009

For 852_0, you need these 2 files:

- `852_0_90b0fe8e_3a6ea6546058bfe1a396d5167a869f626e26b9118eee9c95594d08e2b87c169f.blob` with SHA-256 `3a6ea6546058bfe1a396d5167a869f626e26b9118eee9c95594d08e2b87c169f`
- `852_0_678f4a6a_ae227e4c03f23bf10cd2dc3032dd5007c699f761aec9acc63989a95787f22276.dat` with SHA-256 `ae227e4c03f23bf10cd2dc3032dd5007c699f761aec9acc63989a95787f22276`

See the [full patches list](src/patches/README.md) for what each patch does and which builds support it. Feel free to contribute.

The goal was to have a way to easily fix the build without redistributing it or any Valve stuff.

### Run from source

You need Python 3.12 or newer.

If you have uv (recommended):

1. Run `uv run python .\src\main.py`

If you don't have uv:

1. (optional) Do `python -m venv .venv` then `.venv\scripts\activate`
2. Install dependencies with `pip install .`
3. Run with `python .\src\main.py`
