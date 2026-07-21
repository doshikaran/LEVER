import importPlugin from 'eslint-plugin-import'
import tsParser from '@typescript-eslint/parser'

export default [
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/components/HonestChart.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    // This config only exists to enforce the single import-boundary rule
    // below. It does not know about oxlint's rule set (e.g. react-hooks),
    // so it must not try to validate/honor inline `eslint-disable` comments
    // written for oxlint elsewhere in the codebase.
    linterOptions: { noInlineConfig: true },
    plugins: { import: importPlugin },
    rules: {
      'import/no-restricted-paths': [
        'error',
        {
          zones: [
            {
              target: './src',
              from: 'node_modules/recharts',
              message:
                'Import chart primitives only through HonestChart.tsx — this enforces the zero-anchored-axis rendering-fidelity guardrail.',
            },
          ],
        },
      ],
    },
  },
]
