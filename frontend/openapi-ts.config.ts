import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../docs/openapi.json',
  output: './src/client',
  plugins: [
    '@hey-api/typescript',
    {
      name: '@hey-api/sdk',
      asClass: true,
    },
  ],
});
