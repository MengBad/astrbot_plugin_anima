# Migration Guide - v1.3.0

## Who Needs Action?

Most users do not need any manual migration.

This release is designed to be backward compatible with existing Anima and Sylanne state files.

## What Changed Operationally?

### Version Number Unification

The version number has been unified across all files:
- `main.py` @register decorator: "1.3.0"
- `metadata.yaml` version: "1.3.0"
- `README.md` badge: 1.3.0

### No Functional Changes

This release contains no functional changes to the core narrative engine, observability panels, or dual-engine architecture. All existing behavior is preserved.

## Recommended Operator Checks

After upgrading:

1. Restart or reload the plugin.
2. Confirm the version number shows as v1.3.0 in logs.
3. Run `/anima_help` to verify commands are available.
4. Open the WebUI portal and confirm all Observatory panels load.
5. Run one normal conversation turn to verify the core pipeline works.
6. Check logs for any unexpected errors.

## Rollback

Rollback to the previous plugin version is safe.

No data migration was performed, so rolling back will not lose any data.
