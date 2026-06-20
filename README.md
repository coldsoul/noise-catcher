# Noise Catcher

Environmental noise monitoring system. Records calibrated dB(A) levels 24/7 from a window-mounted microphone, stores time-series data locally, and publishes daily graphs.

## Hardware

Raspberry Pi 4B + miniDSP UMIK-1 calibrated USB microphone. See [BOM.md](BOM.md) for the full bill of materials.

## Quick Start

```bash
# Install
uv sync

# Record 60 seconds of audio
uv run noise-catcher record --duration 60

# Generate a graph from recorded data
uv run noise-catcher graph
```

## License

MIT
