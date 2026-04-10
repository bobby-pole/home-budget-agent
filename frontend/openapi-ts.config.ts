import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../contracts/openapi.json',
  output: './src/client',
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
  ],
});
