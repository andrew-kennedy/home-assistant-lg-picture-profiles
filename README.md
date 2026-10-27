# LG Picture Profiles

A Home Assistant companion for [LG Picture Bridge](https://github.com/andrew-kennedy/lg-webos-picture-bridge). Keep verified picture standards, make temporary adjustments through the existing MQTT entities, and restore the correct saved preset even after the input or HDR format changes.

Requires Home Assistant 2026.10 or newer, HACS, an existing MQTT integration, and LG Picture Bridge **0.11.0 or newer** on a supported rooted LG G6. The companion does not root a TV or update firmware. It reuses Home Assistant's MQTT connection; it needs no SSH key, broker password, or TV administrator credential.

## Install

1. In HACS, add `https://github.com/andrew-kennedy/home-assistant-lg-picture-profiles` as a custom **Integration** repository and download it.
2. Restart Home Assistant, then add **LG Picture Profiles** under Settings → Devices & services.
3. Select the TV media-player entity and enter the bridge's MQTT base topic. The existing Picture command sensor exposes `command_topic`: remove its final `/command` segment. Optionally select your day/night movie and SDR game brightness helpers.
4. Import your verified standard document with `lg_picture_profiles.import_profiles`. Use `lg_picture_profiles.preview` to inspect differences while the TV is available.
5. Disable any older automation that also reapplies these profiles or day/night settings, then turn on **Manage picture profiles**.

Management starts disabled. Installation and importing data do not switch inputs or enable picture management. HACS supplies subsequent integration updates; the TV bridge still updates independently through Homebrew Channel.

## Daily use

- Existing picture and Game Optimizer MQTT entity IDs remain unchanged.
- A confirmed entity adjustment to a setting defined in the standard becomes temporary. It still uses the TV's persistent setting API; this is tracked restoration, not a claim of RAM-only picture settings.
- **Restore standard** resets managed saved banks using the current day/night values. It works even when another input is active. If the TV is off, the restore remains pending until it is available.
- **Save current adjustments as standard** reads back and promotes tracked adjustments in the active context. Apple TV and Shield share a standard when they share the same TV preset.
- A confirmed TV `off` state ends the session. Pending overrides restore on the next available wake. `unknown`/`unavailable`, HDMI format changes, and Home Assistant restarts do not by themselves end a session.
- Day/night changes respect temporary overrides. Restoring after sunset uses the night standard, not a stale daytime snapshot.
- **Profile status** and **Temporary adjustments** show compact status. Full documents are kept out of entity attributes and the recorder.

Only settings explicitly defined in the imported document are managed. Direct changes from LG's own remote and settings outside the document are not automatically classified as temporary; an explicit Restore standard can reset managed values changed outside Home Assistant. Custom Game Optimizer genres need their own saved-bank definitions.

## Data and device bindings

Standards live in Home Assistant's versioned `.storage` through its native storage helper. Temporary adjustments and pending restores are separate from standards and survive restarts. Use `lg_picture_profiles.export_profiles` to obtain JSON and YAML for backup or Git; import a revised document to apply edits. Do not manually edit `.storage` while HA is running.

The schema is a collection of named saved banks:

```yaml
schema: 1
name: Living room standards
devices:
  apple_tv: Apple TV
  shield: NVIDIA Shield
banks:
  - id: hdmi3_sdr_movies
    name: Shared SDR movie picture
    devices: [apple_tv, shield]
    target:
      category: picture
      dimension:
        input: hdmi3
        pictureMode: filmMaker
    settings:
      backlight: 3
      contrast: 95
      color: 50
      sharpness: 0
      colorTemperature: -40
      peakBrightness: "off"
    variants:
      bright:
        backlight: 100
        peakBrightness: high
      dark:
        backlight: 3
        peakBrightness: "off"
    brightness_role: movie_sdr
```

Quote strings such as `"off"` and `"on"` when importing YAML; YAML parsers can otherwise interpret them as booleans. The export action quotes ambiguous strings automatically. The example illustrates the schema, not a complete calibration.

Each native target appears once. Devices sharing a bank reference that same bank; assigning different values to Apple TV and Shield on the same HDMI movie preset would require source-based reapplication. PC inputs retain their `_pc` picture dimension; Game Optimizer controls use the physical `gameInput` plus `dynamicRange` and `gameGenre`.

For a Game Optimizer bank, use `category: other`, dimensions such as `{gameInput: hdmi1, dynamicRange: hdrALLM, gameGenre: Standard}`, and native keys such as `gameColorDepth`, `gameSharpness`, and `gameAdjustContrast`. Motion controls use their own picture bank with `app_id: com.webos.app.hdmi1`. Mode mappings use dimensions `{input: hdmi3, dynamicRange: dolbyHdr}` and setting `pictureMode`; room variants can select Cinema or Cinema Home.

The optional `brightness_role` is `movie_sdr` or `game_sdr`. A configured HA helper supplies that role's brightness. Saving a brightness adjustment as standard updates the assigned helper, which is shared by all banks using that role. Without helpers, values come directly from the document. No unit-specific white-balance or color-management calibration is copied.

## Operation and failure handling

The TV retains native input/range/ALLM mode selection. The companion reacts to sunrise/sunset, brightness-helper changes, confirmed TV power events, and bridge recovery. It performs no periodic settings polling and writes only differences. Reconnects and power-on with an already confirmed environment do not rewrite profiles.

Explicit commands carry a short expiry, a bridge session, and a unique request ID. Identical retries reuse that ID; the bridge deduplicates writes. Restores name the original saved bank, compare the last read value before writing, and verify readback. A newer concurrent edit causes a conflict rather than a blind overwrite. Interrupted or partially applied restores keep their pending state for retry. The companion never retains MQTT command messages or wakes the TV itself.

Disabling management stops automatic day/night and session handling but preserves standards and pending adjustments. Explicit restore/export actions remain available. Keep only one automation or integration responsible for the picture environment.

## Development

```sh
uv venv --python 3.14
uv pip install homeassistant==2026.10.4 paho-mqtt==2.1.0 pytest pytest-asyncio ruff
uv run pytest -q
uv run ruff check .
```

Tests cover native scope identity, shared HDMI banks, day/night precedence, same-request deduplication, restart recovery, failures, and adjustments concurrent with restoration. The TV-side command implementation and its tests live in the bridge repository.

MIT licensed. Neither project is affiliated with LG, NVIDIA, Apple, or Home Assistant.
