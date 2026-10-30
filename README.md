# LG Picture Profiles

Home Assistant controls and complete backups for the **TV-owned** profile manager in [LG Picture Bridge](https://github.com/andrew-kennedy/lg-webos-picture-bridge). Requires bridge **0.14.0+** for the editor, rooted LG G6/webOS 11 and Home Assistant **2026.10+**. The TV is the single owner of standards and restoration; this integration performs no native picture-policy writes.

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

The editor requires **bridge 0.14.0+**. Older bridges remain read-only in the new editor while existing entities and backups continue working.

- Select ports, formats and preset families. **More factors** adds exact presets, ALLM, configured game genres and the room variant. Choose **Picture**, **Motion**, **Gaming**, **HDMI connection** or **Preset selection**. Real Cinema is under Motion.
- Use **Show separate controls by** to split selected settings by relevant factors. Removing a split combines them for a wider edit. Unequal standards show **Mixed** until explicitly edited. Browsing never applies settings or selects an HDMI input.
- **Review changes** lists exact original targets and before/after values. Drafts survive filter and room changes, including drafts outside the current view. **Save standards** sends one validated batch and commits one TV standard revision. A conflict requires reviewing against the latest state; failed native application remains journaled for retry.
- **Restore selected** and **Keep adjustments** preview exact keys in the current room. Restoring Motion can reset Real Cinema without altering Contrast in the same native bank. Keep promotes only reviewed temporary values; changed adjustments or room context require a fresh review.
- OLED pixel brightness appears together for SDR, HDR and Dolby Vision; HDR and Dolby Vision remain editable per profile. Shared SDR brightness controls explicitly include all affected banks, even beyond selected ports. Movie brightness has Bright/Dark preferences; games have one shared SDR preference. The integration's three number entities edit these same standards. Raw MQTT setting entities make temporary adjustments.
- **Last TV read** is the native value from opening/refreshing the view, including inactive inputs. Metadata is cached on demand; the editor adds no polling. Refresh-rate boost uses the TV's reported rate, including 165 Hz on the verified G6.
- **Automatic profiles: On/Off** controls day/night application and temporary-adjustment tracking/restoration. Off leaves current TV settings in place. TV remote arrows move focus; OK edits values and opens controls; OK or Back finishes editing. Back leaves the review before leaving the editor.
- Standards live on the TV. LG remote and MQTT edits to managed values remain temporary even when HA is offline. Confirmed standby/new boot schedules restoration; service restarts, disconnections and format changes do not end a viewing session.
- HA supplies retained sunrise/sunset context. Native input/range/ALLM mappings still select movie and game presets. Apple TV and Shield share movie banks; HDMI 3 connection options also affect Switch. No source-based picture recipe is added.
- Existing entity IDs, MQTT discovery ownership, complete backups and the three integration brightness sliders remain unchanged.

**Preset family** is an editor grouping: **Gaming** contains the Game presets, while **Movies** contains Filmmaker, Cinema and Cinema Home. **Exact preset** means one LG picture mode, such as HDR Game, HDR Filmmaker or Dolby Vision Cinema. Each exact preset retains its own picture settings for an input. For example, Movies + Dolby Vision includes Cinema and Cinema Home; selecting the exact Cinema preset narrows that selection to one mode. Format (SDR/HDR/Dolby Vision) and room variant (Base/Bright/Dark) are separate factors.

In **Show separate controls by**, Preset family separates Gaming from Movies, while Exact preset separates individual LG picture modes. Scope filters choose which settings to include; grouping factors choose which included values share a control.

The editor's categories describe the controls, while grouping factors describe which stored values you want to edit together. LG's ordinary Picture values, including Real Cinema and TruMotion de-judder/de-blur, belong to an input and preset. Only `truMotionMode` also uses the HDMI app scope. Game Optimizer values use input, range/ALLM and genre. Port options span all formats. Expanding stored-value details exposes those exact targets; a broad edit updates existing targets once, without creating inheritance rules.

Only keys defined in the collection are managed. New genres require corresponding native-bank definitions. Unrelated accessibility, audio, panel calibration and energy settings are not added or learned. Unconfigured remote-selected presets can be tracked for restoration but cannot be promoted as supported standards.

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

This illustrates the schema, not a complete calibration. Each native target appears once. Devices sharing a bank reference it; independent settings for Apple TV and Shield on the same LG bank would require source-based reapplication. PC picture inputs retain `_pc`; game controls use physical `gameInput` plus `dynamicRange` and `gameGenre`. Only `truMotionMode` uses a separate bank with `app_id: com.webos.app.hdmiN`. Mode mappings use `{input, dynamicRange}` and the `pictureMode` setting.

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
