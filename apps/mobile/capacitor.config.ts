import type { CapacitorConfig } from '@capacitor/cli';

// Only the bundled launcher has access to Capacitor. Remote web content has no bridge.
const config: CapacitorConfig = {
  appId: 'com.vigilay.mobile',
  appName: 'Vigilay Mobile',
  webDir: 'dist',
  server: { androidScheme: 'https', cleartext: false },
  android: { allowMixedContent: false },
};
export default config;
