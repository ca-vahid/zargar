const { existsSync } = require('fs');
const { join } = require('path');

// app.json holds everything static (and is where `eas init` writes the project id).
// This file only adds what depends on the machine doing the build:
//  - google-services.json (Firebase): needed for push; the build works without it
//  - EXPO_PUBLIC_API_URL: a different server address baked into the build
module.exports = ({ config }) => {
  const hasServices = existsSync(join(__dirname, 'google-services.json'));
  return {
    ...config,
    android: {
      ...config.android,
      ...(hasServices ? { googleServicesFile: './google-services.json' } : {}),
    },
    extra: {
      ...config.extra,
      apiUrl: process.env.EXPO_PUBLIC_API_URL || (config.extra && config.extra.apiUrl),
      pushConfigured: hasServices,
    },
  };
};
