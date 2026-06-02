import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

import i18next from 'eslint-plugin-i18next'

export default defineConfig([
  globalIgnores(['dist', 'src/client']),
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'i18next': i18next,
    },
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      'i18next/no-literal-string': [
        'error',
        {
          markupOnly: true,
          ignoreAttribute: ['className', 'type', 'variant', 'size', 'name', 'id', 'data-testid', 'placeholder', 'to'],
        },
      ],
    },
  },
  {
    files: ['**/*.test.tsx', '**/*.test.ts', '**/__tests__/**', 'src/components/ui/**'],
    rules: {
      'i18next/no-literal-string': 'off',
    },
  },
])
