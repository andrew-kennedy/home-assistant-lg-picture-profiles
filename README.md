# LG Picture Profiles

Home Assistant controls and complete backups for the **TV-owned** profile manager in [LG Picture Bridge](https://github.com/andrew-kennedy/lg-webos-picture-bridge). Requires bridge **0.13.2+**, rooted LG G6/webOS 11 and Home Assistant **2026.10+**. The TV is the single owner of standards and restoration; this integration performs no native picture-policy writes.

## Install or upgrade

1. Add `andrew-kennedy/home-assistant-lg-picture-profiles` in HACS as an Integration, download, then restart Home Assistant.
2. Add **LG Picture Profiles** in Devices & services. The complete UI flow asks for the existing bridge MQTT base topic, TV entity and sun entity. The integration creates its own three SDR brightness sliders; no input_number helpers are required.
3. Open **LG Picture Profiles** in the sidebar (admin access), or **Picture profiles** in the TV app. Both use the same editor. File import/download controls are available in the Home Assistant panel on a phone or computer; the TV app omits them. Import a verified schema 1 standard document or complete JSON backup through the HA panel while the TV is on.

Upgrading from 0.3 removes the retired helper bindings from both setup data and options. Existing TV standards, brightness preferences, temporary adjustments and complete backups remain unchanged. Move any dashboards or automations from the old helpers to the integration’s number entities, then delete helpers you no longer need; the integration does not delete unrelated user-owned entities.

If upgrading an older helper-based 0.1/0.2 setup, first install 0.3.2 and turn on the updated bridge to complete TV ownership migration. That version preserves the former HA Store and transfers helper values to the TV. The 0.4 upgrade checks the saved complete backup before discarding active helper bindings, preventing an unfinished migration from losing those values. A TV that already owns a collection is never overwritten automatically.

## Entity ownership and organization

The bridge publishes individual picture settings, CEC controls and signal sensors through Home Assistant's built-in MQTT discovery. This keeps supported options, numeric limits, availability and confirmed state defined by the TV. Those controls work without this companion. The companion creates only profile-specific controls and provides the editor, environment context and complete backups; it also communicates over MQTT.

Starting in 0.4.5, the companion's eight entities link to the existing MQTT bridge device, so both sets of controls appear on its device page. They retain their integration ownership, unique IDs, entity IDs and entity customizations. The obsolete companion-only device is removed through Home Assistant's supported helper migration API. Entity-based automations and dashboards continue to work; any references to the former companion **device ID** should instead target the bridge device or the individual entities.

Linking uses the exact MQTT device identifier from the configured bridge topic. Late discovery or device recreation is handled by one device-registry listener; there is no polling. The companion never takes over or rewrites MQTT entity definitions or device metadata. It subscribes only to profile status, availability and complete backups, not the raw settings streams.

## Daily use

- Choose a device, **SDR / HDR / Dolby Vision**, and room variant. Gaming devices with SDR/HDR standards have two format choices. Picture, distinct Game Optimizer controls and Motion appear together. Equivalent picture and gaming controls appear once, including normal/ALLM values; disagreements show **Mixed** until you explicitly choose a common value. Dolby Vision follows the room's saved Cinema/Cinema Home mapping. **All devices** only filters the list. Inactive profiles can be edited without selecting their HDMI input.
- **Save standard** commits only changed values. **Restore this profile** resets its displayed settings and format-specific preset mappings; **Keep current adjustments** promotes their tracked temporary values. Other formats and HDMI-wide settings remain outside those actions. If an update fails, unconfirmed drafts remain available to review and retry. **View → HDMI port settings** exposes physical-port controls shared across all connected devices and formats. **Advanced picture settings** exposes the individual Picture, Game Optimizer, Motion and preset-selection values behind Picture profiles. An advanced edit affects only that group. The two detailed views do not overlap; every native setting remains accessible. Browsing does not change saved standards.
- **Last TV read** is the selected profile's native value when opened or refreshed. For example, “on” means that setting is enabled. It does not indicate TV power or imply continuous polling. Bridge 0.13.8+ also supplies the correct refresh-rate boost label from TV metadata, including 165 Hz on the G6 despite LG's older internal key name.
- **Automatic profiles: On/Off** controls day/night application and tracking/restoration of temporary adjustments. Off pauses those features and leaves the current TV settings in place. The TV editor supports arrow navigation, OK to edit a value, and OK or Back to finish editing; browser controls in the HA panel retain their usual keyboard and pointer behavior.
- Existing picture/Game Optimizer MQTT entities remain temporary controls. LG remote changes to managed settings are tracked by the same existing native subscriptions, even when HA is down.
- Standards live on the TV. Only explicit save/import/editor actions change them. A confirmed TV power cycle restores temporary changes; a bridge restart, HA restart, unknown/unavailable state, or format transition does not end a session.
- Native input/range/ALLM mappings select movie and game presets. No source-based picture reapplication is added. Apple TV and Shield share a standard where they share an LG bank; the editor labels this.
- The **Manage picture profiles**, **Restore standard**, **Save current adjustments as standard**, **Profile status** and **Temporary adjustments** entity IDs are preserved. Three new brightness numbers edit shared bright/dark movie SDR and game SDR standards, with bounds 0–100.
- The three integration brightness sliders edit saved standards, while the raw MQTT picture controls make temporary adjustments. Retired input_number helpers are no longer read, synchronized or offered in setup/options.
- HA sends sunrise/sunset room context through retained MQTT state. The TV applies only changed environment settings and respects temporary adjustments. During an HA outage, the last known room remains until reconnection.

**HDMI port settings versus picture profiles:** HDMI 3 has one set of port options (such as ALLM, VRR and QFT) shared by Apple TV, Shield and Switch. Picture values belong to the input and picture preset for each signal format; Apple TV and Shield share movie presets while Switch uses game presets. LG stores Game Optimizer values separately by input, signal-format/ALLM and game genre. The normal profile view combines matching controls for explicit edits; Advanced exposes each stored group. These are not independent profiles for every device name or simply two copies for an On/Off switch.

Only keys defined in the collection are managed. Custom Game Optimizer genres need their own native-bank definitions. Unrelated accessibility, audio, panel calibration and energy settings are not added or learned. A remote-selected picture mode outside the curated collection can be tracked for restoration, but cannot be promoted as a supported standard.

## Backups and recovery

Every profile or temporary-setting change publishes a **complete** retained snapshot on `<base>/profiles/backup`, coalesced into 500 ms batches during slider bursts. The TV also publishes on wake, standby, broker reconnection and HA reconnection. Full snapshots do not enter entity attributes or Recorder history.

The snapshot includes all standards and room variants, device bindings, brightness preferences, temporary values and recovery scopes. An envelope contains `state_json` plus a SHA-256 of those exact UTF-8 bytes. HA validates it, saves it through its atomic Store, then acknowledges the exact owner/instance/sequence/checksum. Corrupt, stale and duplicate snapshots cannot overwrite a newer backup; duplicates are acknowledged without another disk write. HA retains the latest snapshot and the previous five standard revisions. They are included in ordinary HA backups.

The former HA migration document/journal is retained only until the migrated TV backup is validated and saved. Version 0.4.2 also removes that obsolete copy from completed migrations on upgrade, including while the TV is offline. An unfinished migration keeps its source data; a failed save does not discard it. Current backups and standard revision history are preserved.

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
- `preview`: the complete cached profile state, including standards, brightness preferences, temporary adjustments, recovery scopes and bridge status. While offline it returns the saved snapshot with an explicit offline status. It does not audit all native settings, change profiles or add a stored copy. Version 0.4.2 restores this full view after 0.4.1 briefly summarized it.

Use the integration's **Configure** screen to rename it or change the sun/TV entities. The MQTT base is fixed per entry; add another entry for another TV. Never edit live `.storage` manually. Retired recipe/environment automations must remain removed so they do not compete with TV ownership; the bridge rejects legacy profile writes after initialization. HDMI icon commands and source/CEC/power automations continue independently.

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

`brightness_role` is `movie_sdr` or `game_sdr`. Its effective brightness comes from the TV's shared preferences (bright/dark movie or game), exposed by the integration’s own number entities. Quote YAML strings such as `"off"` and `"on"`. Panel-specific white balance/CMS calibration is never copied automatically.

## Development

```sh
uv venv --python 3.14
uv pip install homeassistant==2026.10.4 paho-mqtt==2.1.0 pytest pytest-asyncio ruff
uv run pytest -q
uv run ruff check .
python scripts/sync-editor.py ../lg-webos-picture-bridge
```

The editor and its presentation model are vendored from the bridge repository with both SHAs recorded in `frontend/editor-source.json`. Their browser tests live in the bridge repository. Recovery/remote-edit/native-bank tests also live with the TV engine; HA tests cover backup integrity/durability, migration, control forwarding, UI options and MQTT session handling. No periodic HA settings polling is used.
