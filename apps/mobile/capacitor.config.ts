import type { CapacitorConfig } from '@capacitor/cli';

// La interfaz queda empaquetada; solo la capa HTTP nativa habla con Vigilay API.
const config: CapacitorConfig = {
  appId: 'com.vigilay.mobile',
  appName: 'Vigilay Mobile',
  webDir: 'dist',
  server: { androidScheme: 'https', cleartext: false },
  android: { allowMixedContent: false },
  plugins: {
    CapacitorHttp: { enabled: true },
    CapacitorCookies: { enabled: true },
  },
};
export default config;
