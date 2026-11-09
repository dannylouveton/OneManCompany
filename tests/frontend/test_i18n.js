#!/usr/bin/env node
/* Tests for frontend/i18n.js translation lookup (French). Run: node tests/frontend/test_i18n.js */

const assert = require("assert");
const path = require("path");

global.window = { alert() {}, confirm() {}, prompt() {} };
global.localStorage = { getItem: () => "fr", setItem() {} };
global.document = { documentElement: {}, readyState: "loading", addEventListener() {} };
require(path.join(__dirname, "..", "..", "frontend", "i18n.js"));
const { t } = window.I18N;

const cases = [
  ["Settings", "Réglages"],
  ["⚙ Settings:", "⚙ Réglages:"],
  ["⚙ Alex COO Details", "⚙ Alex COO — Fiche"],
  ["Alex COO (Le Forgeron) Work Principles", "Principes de travail — Alex COO (Le Forgeron)"],
  [": Operations", ": Opérations"],
  ["Status: Ready | Owner: Alex", "Statut : Prêt | Responsable : Alex"],
  ['Delete sprint "S1"?', "Supprimer le sprint « S1 » ?"],
  ["Failed: boom", "Échec : boom"],
  ["12 tasks", "12 tâches"],
  ["Hello world", "Hello world"],
];
for (const [input, expected] of cases) {
  assert.strictEqual(t(input), expected, `t(${JSON.stringify(input)})`);
}
console.log(`ok - ${cases.length} i18n cases`);
