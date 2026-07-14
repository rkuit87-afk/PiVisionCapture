# DB1 Trigger Delay Control

Add this member at the end of the standard-access `DB_Vission` (DB1) static
section in TIA Portal:

| Name | Type | Byte | Owner | Initial value | Purpose |
|------|------|------|-------|---------------|---------|
| `iTriggerDelay` | `Int` | `24` | TIA operator | `780` | Trigger-to-camera-frame delay in milliseconds |

`bSawDownCompare` occupies byte `22.0`. S7 standard alignment places the
next `Int` at byte 24, so this addition does not move any existing DB1 member.
The DB grows from 24 to 26 bytes.

## TIA Steps

1. Open `DB_Vission` (DB1), add `iTriggerDelay : Int` as the final static
   member, and set its start value to `780`.
2. Compile DB1 and download the DB change during an approved machine window.
3. Confirm DB1 is 26 bytes and watch `DB1.iTriggerDelay` online.
4. Set the desired delay in milliseconds. Set `780` for the next validation.
5. Restart `shadow_capture_app.py` after changing the DB definition. The app
   reads the value at every `bTrigger` rising edge; it does not write the DB.

The accepted range is 1 to 4500 ms. A missing member or a value outside that
range leaves the YAML fallback (`780 ms`) active.
