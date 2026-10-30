# mobile-app/ — Phase 5 (not implemented yet)

React Native + Expo (Android). Five screens: Home (push-to-talk + text),
Devices, Activity, Security, Settings.

Contract: `../shared/command-schema.json` and `../shared/protocol.md`.
Speech is converted to text **on the device** (Android STT); no raw audio is
streamed in v1. Tokens go in Keystore-backed secure storage, never AsyncStorage.
