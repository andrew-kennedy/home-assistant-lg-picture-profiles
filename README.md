# LG Picture Profiles

Home Assistant controls and complete backups for the **TV-owned** profile manager in [LG Picture Bridge](https://github.com/andrew-kennedy/lg-webos-picture-bridge). Requires bridge **0.13.2+**, rooted LG G6/webOS 11 and Home Assistant **2026.10+**. The TV is the single owner of standards and restoration; this integration performs no native picture-policy writes.

## Install or upgrade

1. Add `andrew-kennedy/home-assistant-lg-picture-profiles` in HACS as an Integration, download, then restart Home Assistant.
2. Add **LG Picture Profiles** in Devices & services. The complete UI flow asks for the existing bridge MQTT base topic, TV entity and sun entity. Optional existing brightness helpers can remain as synchronized controls; new installations can use the integration's three number entities.
3. Open **LG Picture Profiles** in the sidebar (admin access), or **Picture profiles** in the TV app. Both use the same editor. Import a verified schema 1 standard document or complete JSON backup while the TV is on.

Upgrading from 0.1/0.2 preserves the entire previous HA Store as a rollback copy and migrates its exact standards, helper values, temporary changes and queued restores to an unconfigured TV. The former HA policy loop stops immediately. Migration finishes only after a matching complete TV backup is committed to HA storage. Until bridge 0.13 is online, status is `awaiting_tv_migration`. A TV that already owns a collection is never overwritten automatically.

## Daily use

- Choose a device, native profile and room variant in the editor. Inactive native profiles can be edited without selecting their HDMI input. **Save standard** commits a draft; **Restore this profile** resets that bank; **Keep current adjustments** promotes its tracked temporary values.
- Existing picture/Game Optimizer MQTT entities remain temporary controls. LG remote changes to managed settings are tracked by the same existing native subscriptions, even when HA is down.
- Standards live on the TV. Only explicit save/import/editor actions change them. A confirmed TV power cycle restores temporary changes; a bridge restart, HA restart, unknown/unavailable state, or format transition does not end a session.
- Native input/range/ALLM mappings select movie and game presets. No source-based picture reapplication is added. Apple TV and Shield share a standard where they share an LG bank; the editor labels this.
- The **Manage picture profiles**, **Restore standard**, **Save current adjustments as standard**, **Profile status** and **Temporary adjustments** entity IDs are preserved. Three new brightness numbers edit shared bright/dark movie SDR and game SDR standards, with bounds 0–100.
- Optional configured input_number helpers mirror these TV-owned brightness values. Changing a helper forwards an explicit edit to the TV; changing a standard in the editor updates its helper. Clearing a helper in Configure stops that link and does not reset the TV preference.
- HA sends sunrise/sunset room context through retained MQTT state. The TV applies only changed environment settings and respects temporary adjustments. During an HA outage, the last known room remains until reconnection.

Only keys defined in the collection are managed. Custom Game Optimizer genres need their own native-bank definitions. Unrelated accessibility, audio, panel calibration and energy settings are not added or learned. A remote-selected picture mode outside the curated collection can be tracked for restoration, but cannot be promoted as a supported standard.

## Backups and recovery

Every profile or temporary-setting change publishes a **complete** retained snapshot on `<base>/profiles/backup`, coalesced into 500 ms batches during slider bursts. The TV also publishes on wake, standby, broker reconnection and HA reconnection. Full snapshots do not enter entity attributes or Recorder history.

The snapshot includes all standards and room variants, device bindings, brightness preferences, temporary values and recovery scopes. An envelope contains `state_json` plus a SHA-256 of those exact UTF-8 bytes. HA validates it, saves it through its atomic Store, then acknowledges the exact owner/instance/sequence/checksum. Corrupt, stale and duplicate snapshots cannot overwrite a newer backup; duplicates are acknowledged without another disk write. HA retains the latest snapshot and the previous five standard revisions, as well as the legacy migration copy. They are included in ordinary HA backups.

**Download backup** exports the complete envelope, including temporary adjustments for inspection. Importing it restores standards/preferences and queues native verification, rather than replaying historical temporary adjustments. Backups can be downloaded while the TV is off. Edits require an available TV because there is only one authority.

TV storage writes stay sparse: saved profiles change only on explicit standard edits; a small recovery journal changes when dirty-key membership, power, restore intent or environment changes. Repeated values of an already dirty slider are kept in RAM and MQTT. On a bridge restart, the TV reconstructs temporary values by reading only journaled banks. Restores compare current values, skip unchanged settings and verify readback. Newer concurrent remote changes win over older queued work. Failed restores remain journaled and use recovery-only backoff.

The backup is complete for **managed picture profiles**, not a firmware or whole-TV image. Broker credentials and unrelated TV account/system settings are excluded. See the [ownership and protocol documentation](https://github.com/andrew-kennedy/lg-webos-picture-bridge/blob/main/docs/profile-ownership.md) for storage and recovery details.

## Actions and configuration

- `export_profiles`: JSON plus readable YAML for the standard document.
- `import_profiles`: import a verified document or YAML into the TV; replaces the collection and restores its managed standards.
- `export_backup`: return the complete received envelope (optionally a previous standard revision).
- `restore_backup`: explicitly restore standards/preferences from a complete envelope.
- `restore_standard`: reset `active` or `all` managed banks on the TV.
- `save_standard`: explicitly promote tracked `active` or `all` adjustments.
- `reconcile`: ask the TV to retry pending recovery/environment work.
- `preview`: show the TV's collection/status, or the saved backup while offline.

Use the integration's **Configure** screen to rename it, change the sun/TV entities or link/unlink optional brightness helpers. The MQTT base is fixed per entry; add another entry for another TV. Never edit live `.storage` manually. Retired recipe/environment automations must remain removed so they do not compete with TV ownership; the bridge rejects legacy profile writes after initialization. HDMI icon commands and source/CEC/power automations continue independently.

## Standard document

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

This illustrates the schema, not a complete calibration. Each native target appears once. Devices sharing a bank reference it; independent settings for Apple TV and Shield on the same LG bank would require source-based reapplication. PC picture inputs retain `_pc`; game controls use physical `gameInput` plus `dynamicRange` and `gameGenre`. Motion controls use a separate bank with `app_id: com.webos.app.hdmiN`. Mode mappings use `{input, dynamicRange}` and the `pictureMode` setting.

`brightness_role` is `movie_sdr` or `game_sdr`. Its effective brightness comes from the TV's shared preferences (bright/dark movie or game), independently of whether an HA helper is linked. Quote YAML strings such as `"off"` and `"on"`. Panel-specific white balance/CMS calibration is never copied automatically.

## Development

```sh
uv venv --python 3.14
uv pip install homeassistant==2026.10.4 paho-mqtt==2.1.0 pytest pytest-asyncio ruff
uv run pytest -q
uv run ruff check .
python scripts/sync-editor.py ../lg-webos-picture-bridge
```

The editor is vendored from the bridge repository with its SHA recorded in `frontend/editor-source.json`. Its browser tests live in the bridge repository. Recovery/remote-edit/native-bank tests also live with the TV engine; HA tests cover backup integrity/durability, migration, control forwarding, UI options and MQTT session handling. No periodic HA settings polling is used.
