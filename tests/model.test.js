#!/usr/bin/env node
// Loads Model.js (a QML ".pragma library" file, otherwise plain ES5) under
// node and checks the pure helpers the panel relies on.

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "Model.js"), "utf8")
  .replace(/^\.pragma library\s*$/m, "");
const Model = {};
vm.runInNewContext(source + "\n" + [
  "asNumber", "clamp", "toList", "percentText", "ratioText", "formatDuration",
  "remainingSeconds", "resetText", "agoText", "paceText", "paceDetail",
  "paceTone", "severityRank", "windowAlarming", "windowsOf", "headlineUsed",
  "worstSeverity", "anyOverutilizing", "errorsOfKind", "agentName",
  "silentAgentsText", "statusText", "tooltipText", "backoffRemaining",
  "reportFetchedAtMs", "staleText", "reportFor", "anyStale", "issueText",
  "paceJustReset", "paceAvailableIn", "windowTitle", "resetsOf", "creditsOf",
  "hasExtras", "extrasSummary", "resetCountText", "resetDetail", "resetUsable",
  "creditFraction", "creditText",
].map((name) => `Model.${name} = ${name};`).join("\n"), { Model });

const claudeWindow = {
  label: "5-hour", window_minutes: 300, used_percent: 4, expected_percent: 73.57,
  pace_known: true, pace_ratio: 0.054, pace_label: "underutilizing",
  used_severity: "ok", resets_at: "2026-09-07T14:29:59Z",
  reset_in_seconds: 4757, reset_relative: "in 1h 19m",
};
const codexWindow = {
  label: "7-day", window_minutes: 10080, used_percent: 11, expected_percent: 3.67,
  pace_known: true, pace_ratio: 2.999, pace_label: "overutilizing",
  used_severity: "ok", resets_at: "2026-09-14T09:01:00+02:00",
  reset_in_seconds: 582617, reset_relative: "in 6d 17h",
};
const reports = [
  {
    agent: "claude", provider: "Claude Code", short_name: "Claude",
    windows: [claudeWindow],
    summary: {
      five_hour: { used_percent: 4, expected_percent: 73.57, severity: "ok", text: "" },
      week_global: { used_percent: 5, expected_percent: 91.77, severity: "ok", text: "" },
    },
  },
  {
    agent: "codex", provider: "Codex", short_name: "Codex",
    windows: [codexWindow],
    summary: { five_hour: null, week_global: { used_percent: 11, expected_percent: 3.67, severity: "danger", text: "" } },
  },
];
const errors = [
  { agent: "kimi", kind: "not_installed", message: "Kimi Code CLI is not installed." },
  { agent: "grok", kind: "error", message: "token expired" },
];

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

test("toList accepts array-likes and rejects the rest", () => {
  // Arrays built inside the vm context have a foreign prototype, so compare
  // by shape rather than by identity.
  const shape = (value) => JSON.stringify(value);
  assert.equal(shape(Model.toList([1, 2])), "[1,2]");
  assert.equal(shape(Model.toList({ length: 2, 0: "a", 1: "b" })), '["a","b"]');
  assert.equal(shape(Model.toList(null)), "[]");
  assert.equal(shape(Model.toList("nope")), "[]");
  assert.equal(shape(Model.windowsOf({ windows: { length: 1, 0: { label: "x" } } })), '[{"label":"x"}]');
});

test("percentText rounds to one decimal and drops .0", () => {
  assert.equal(Model.percentText(4), "4%");
  assert.equal(Model.percentText(73.57058), "73.6%");
  assert.equal(Model.percentText("garbage"), "0%");
});

test("ratioText keeps two decimals under ten", () => {
  assert.equal(Model.ratioText(0.054), "0.05×");
  assert.equal(Model.ratioText(2.999), "3×");
  assert.equal(Model.ratioText(12.4), "12×");
});

test("formatDuration mirrors lazyagent's relative format", () => {
  assert.equal(Model.formatDuration(45), "45s");
  assert.equal(Model.formatDuration(4757), "1h 19m");
  assert.equal(Model.formatDuration(582617), "6d 17h");
  assert.equal(Model.formatDuration(720), "12m");
  assert.equal(Model.formatDuration(-5), "0s");
});

test("remainingSeconds counts down from the fetch instant", () => {
  assert.equal(Model.remainingSeconds(claudeWindow, 1000, 1000), 4757);
  assert.equal(Model.remainingSeconds(claudeWindow, 1000, 61000), 4697);
  assert.equal(Model.remainingSeconds(claudeWindow, 1000, 1000 + 5000 * 1000), 0);
  assert.equal(Model.remainingSeconds({ reset_in_seconds: 0 }, 0, 0), 0);
});

test("resetText distinguishes unknown from due", () => {
  assert.equal(Model.resetText(claudeWindow, 1000, 1000), "Resets in 1h 19m");
  assert.equal(Model.resetText({ reset_in_seconds: 0, resets_at: "" }, 0, 0), "");
  assert.equal(Model.resetText({ reset_in_seconds: 0, resets_at: "2026-01-01T00:00:00Z" }, 0, 0), "Reset due");
});

test("agoText", () => {
  assert.equal(Model.agoText(0, 5000), "");
  assert.equal(Model.agoText(1000, 4000), "Updated just now");
  assert.equal(Model.agoText(1000, 1000 + 125 * 1000), "Updated 2m ago");
});

test("pace helpers follow lazyagent's labels", () => {
  assert.equal(Model.paceText(claudeWindow), "Underutilizing");
  assert.equal(Model.paceTone(claudeWindow), "under");
  assert.equal(Model.paceTone(codexWindow), "over");
  assert.equal(Model.paceTone({ pace_known: true, pace_label: "on track" }), "track");
  assert.equal(Model.paceTone({ pace_known: false, pace_label: "" }), "unknown");
  assert.equal(Model.paceText({ pace_known: false }), "Pace unknown");
  assert.equal(Model.paceDetail(claudeWindow), "0.05× of expected 73.6%");
  assert.equal(Model.paceDetail({ pace_known: false }), "");

  // 7-day window 0.5% in: lazyagent withholds the pace until 1% has elapsed.
  const reset = { label: "7-day", window_minutes: 10080, expected_percent: 0.5, pace_known: false };
  assert.equal(Model.paceJustReset(reset), true);
  assert.equal(Model.paceJustReset(claudeWindow), false);
  assert.equal(Model.paceJustReset({ pace_known: false, expected_percent: 0.5, window_minutes: 0 }), false);
  assert.equal(Model.paceText(reset), "Window just reset");
  assert.equal(Model.paceTone(reset), "unknown");
  // 0.5% of 10080 minutes is 50.4 minutes.
  assert.equal(Model.paceAvailableIn(reset, 0, 0), 3024);
  assert.equal(Model.paceDetail(reset, 0, 0), "Pace in ~50m");
  assert.equal(Model.paceDetail(reset, 0, 20 * 60 * 1000), "Pace in ~30m");
  assert.equal(Model.paceDetail(reset, 0, 60 * 60 * 1000), "Pace at the next refresh");
});

test("alarming windows are severe or nearly exhausted", () => {
  assert.equal(Model.windowAlarming(claudeWindow), false);
  assert.equal(Model.windowAlarming({ used_percent: 91, used_severity: "ok" }), true);
  assert.equal(Model.windowAlarming({ used_percent: 20, used_severity: "warn" }), true);
  assert.equal(Model.windowAlarming({ used_percent: 20, used_severity: "danger" }), true);
});

test("aggregates across reports", () => {
  assert.equal(Model.headlineUsed(reports), 11);
  assert.equal(Model.headlineUsed([]), -1);
  assert.equal(Model.worstSeverity(reports), 0);
  assert.equal(Model.worstSeverity([{ windows: [{ used_percent: 95, used_severity: "ok" }] }]), 3);
  assert.equal(Model.anyOverutilizing(reports), true);
  assert.equal(Model.anyOverutilizing([reports[0]]), false);
});

test("errors are split by kind", () => {
  assert.equal(Model.errorsOfKind(errors, "error").length, 1);
  assert.equal(Model.errorsOfKind(errors, "not_installed")[0].agent, "kimi");
  assert.equal(Model.silentAgentsText(errors), "Kimi Code is not installed or not reporting.");
  assert.equal(Model.silentAgentsText([
    { agent: "kimi", kind: "not_installed" },
    { agent: "cursor", kind: "unavailable" },
  ]), "Kimi Code, Cursor are not installed or not reporting.");
  assert.equal(Model.silentAgentsText([]), "");
});

test("agentName", () => {
  assert.equal(Model.agentName("claude"), "Claude Code");
  assert.equal(Model.agentName("cursor"), "Cursor");
  assert.equal(Model.agentName("whatever"), "whatever");
  assert.equal(Model.agentName(""), "Unknown agent");
});

test("backoff and stale helpers", () => {
  assert.equal(Model.backoffRemaining(0, 5000), 0);
  assert.equal(Model.backoffRemaining(10000, 4000), 6);
  assert.equal(Model.backoffRemaining(10000, 20000), 0);

  const stale = { agent: "claude", stale: true, fetched_at: 1000 };
  assert.equal(Model.reportFetchedAtMs(stale, 5), 1000000);
  assert.equal(Model.reportFetchedAtMs({ agent: "codex" }, 5), 5);
  assert.equal(Model.staleText(stale, 1000000 + 125 * 1000), "Stale · 2m ago");
  assert.equal(Model.staleText({ stale: true }, 0), "Stale");
  assert.equal(Model.staleText(reports[0], 0), "");
  assert.equal(Model.reportFor([stale, reports[1]], "codex").provider, "Codex");
  assert.equal(Model.reportFor([], "codex"), null);
  assert.equal(Model.anyStale([stale]), true);
  assert.equal(Model.anyStale(reports), false);

  const limited = { agent: "claude", kind: "error", rate_limited: true, message: "429" };
  assert.equal(Model.issueText(limited, [stale], 1000000 + 600 * 1000, 240),
    "Claude Code: rate limited by the provider. Retrying in 4m. Showing data from 10m ago.");
  assert.equal(Model.issueText(limited, [], 0, 0),
    "Claude Code: rate limited by the provider. Retrying at the next refresh.");
  assert.equal(Model.issueText(errors[1], [], 0, 0), "Grok: token expired");
  assert.equal(Model.issueText(null, [], 0, 0), "");
});

test("statusText covers every state", () => {
  assert.equal(Model.statusText(false, false, true, [], []), "Reading limits");
  assert.equal(Model.statusText(false, false, false, [], []), "Waiting for lazyagent");
  assert.equal(Model.statusText(true, false, false, [], []), "lazyagent is not installed");
  assert.equal(Model.statusText(true, true, false, [], [errors[1]]), "Could not read any limits");
  assert.equal(Model.statusText(true, true, false, [], []), "No agents reporting");
  assert.equal(Model.statusText(true, true, false, reports, []), "Overutilizing");
  assert.equal(Model.statusText(true, true, false, [reports[0]], []), "1 pool reporting");
  assert.equal(Model.statusText(true, true, false,
    [{ windows: [{ used_percent: 99, used_severity: "danger" }] }], []), "A window is nearly exhausted");
  assert.equal(Model.statusText(true, true, false, reports, [], 250), "Rate limited · retry in 4m");
});

test("tooltipText summarises every pool", () => {
  assert.equal(Model.tooltipText(false, false, [], []), "Lazyagent: checking limits");
  assert.equal(Model.tooltipText(true, false, [], []), "Lazyagent: lazyagent is not installed");
  assert.equal(Model.tooltipText(true, true, reports, []),
    "Claude: 5h 4% · week 5%\nCodex: week 11%");
  assert.equal(Model.tooltipText(true, true, [{ ...reports[1], stale: true }], []),
    "Codex: week 11%  (stale)");
  assert.equal(Model.tooltipText(true, true, [], [errors[1]]), "Lazyagent: token expired");
  assert.equal(Model.tooltipText(true, true, [], []), "Lazyagent: no agents reporting");
  assert.equal(Model.tooltipText(true, true, [{ agent: "grok", short_name: "Grok",
    windows: [{ label: "weekly", used_percent: 5 }], summary: {} }], []), "Grok: weekly 5%");
});

test("scoped windows get their own title and tooltip entry", () => {
  const fable = { label: "7-day", scope: "Fable", detail: "11% of the weekly limit used, capped at 50%",
    used_percent: 21 };
  assert.equal(Model.windowTitle(codexWindow), "7-day window");
  assert.equal(Model.windowTitle(fable), "7-day window (Fable)");
  const claude = { ...reports[0], windows: [claudeWindow, fable] };
  assert.equal(Model.tooltipText(true, true, [claude], []), "Claude: 5h 4% · week 5% · Fable 21%");
  // Without summary cells every window is listed, the scoped one by name.
  assert.equal(Model.tooltipText(true, true, [{ short_name: "Claude", summary: {},
    windows: [{ label: "7-day", used_percent: 23 }, fable] }], []), "Claude: 7-day 23% · Fable 7-day 21%");
  assert.equal(Model.headlineUsed([claude]), 21);
});

test("resets count down from the report's fetch instant", () => {
  const grant = { label: "One full limit reset", left: 1, total: 1, usable: true, status: "",
    expires_in_seconds: 3 * 86400 + 7200, next_available_in_seconds: 0 };
  const codex = { label: "Full reset", left: 2, total: 0, usable: true, status: "",
    expires_in_seconds: 0, next_available_in_seconds: 0 };
  const weekly = { label: "5-hour limit reset", left: 0, total: 1, usable: false,
    status: "only at a usage limit", expires_in_seconds: 0, next_available_in_seconds: 90061 };
  assert.equal(Model.resetCountText(grant), "1 of 1 left");
  assert.equal(Model.resetCountText(codex), "2 left");
  assert.equal(Model.resetDetail(grant, 0, 0), "Usable now · expires in 3d 2h");
  assert.equal(Model.resetDetail(grant, 0, 3600 * 1000), "Usable now · expires in 3d 1h");
  assert.equal(Model.resetDetail(grant, 0, 4 * 86400 * 1000), "Usable now · expired");
  assert.equal(Model.resetDetail(codex, 0, 0), "Usable now");
  assert.equal(Model.resetDetail(weekly, 0, 0), "Only at a usage limit · back in 1d 1h");
  assert.equal(Model.resetDetail({ left: 1, usable: false }, 0, 0), "");
  assert.equal(Model.resetUsable(grant), true);
  assert.equal(Model.resetUsable(weekly), false);
  assert.equal(Model.resetUsable({ ...grant, left: 0 }), false);
});

test("credits keep lazyagent's text and meter spend against a limit", () => {
  const extra = { label: "Extra usage", unit: "EUR", enabled: false, balance: null, used: 0, limit: null,
    status: "set by your organization", text: "disabled · set by your organization" };
  const onDemand = { label: "On-demand", unit: "USD", enabled: true, balance: null, used: 45, limit: 50,
    status: "", text: "$45.00 of $50.00 used" };
  assert.equal(Model.creditText(extra), "disabled · set by your organization");
  assert.equal(Model.creditText({ enabled: true }), "available");
  assert.equal(Model.creditText({ enabled: false }), "disabled");
  assert.equal(Model.creditFraction(extra), -1);
  assert.equal(Model.creditFraction(onDemand), 0.9);
  assert.equal(Model.creditFraction({ used: 80, limit: 50 }), 1);
  assert.equal(Model.creditFraction({ used: 5, limit: 0 }), -1);
});

test("More summarises what it hides", () => {
  const report = { resets: [{}, {}, {}, {}], credits: [{}], note: "Note." };
  assert.equal(Model.hasExtras(report), true);
  assert.equal(Model.extrasSummary(report), "4 resets · 1 credit pool");
  assert.equal(Model.extrasSummary({ resets: [{}], credits: [{}, {}] }), "1 reset · 2 credit pools");
  assert.equal(Model.extrasSummary({ note: "Note." }), "Source and notes");
  assert.equal(Model.extrasSummary({}), "");
  assert.equal(Model.hasExtras({ note: "Note." }), true);
  assert.equal(Model.hasExtras({ resets: [], credits: [] }), false);
  assert.equal(Model.hasExtras(null), false);
  assert.equal(Model.resetsOf({}).length, 0);
});

console.log(`\n${passed} model tests passed`);
