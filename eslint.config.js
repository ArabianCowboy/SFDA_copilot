// ESLint flat config for the plain-JS, no-bundler frontend under static/js/.
// Correctness-focused only — Prettier owns formatting (see .prettierrc), so no
// stylistic rules (indentation, quotes, semicolons) are duplicated here.
import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**', 'static/js/**/*.min.js'],
  },
  js.configs.recommended,
  {
    files: ['static/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        // marked and DOMPurify are loaded from a CDN `<script>` tag and used as
        // bare globals (see static/js/modules/stream-render.js, modules/ui.js).
        // bootstrap is always accessed via `window.bootstrap`, so it needs no
        // entry here; the Supabase client is ES-module-imported directly from
        // its CDN URL (see modules/services.js), likewise not a global.
        DOMPurify: 'readonly',
        marked: 'readonly',
      },
    },
    rules: {
      // 'error', not 'warn': a warning never fails `npx eslint` (exit 0
      // regardless), so pre-commit/CI would never actually gate on these.
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
      // "ignore" for null: `x == null` is the idiomatic one-check way to
      // catch both null and undefined, used throughout this codebase.
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
    },
  },
];
