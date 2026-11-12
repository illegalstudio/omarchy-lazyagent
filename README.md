<p align="center">
  <img src="assets/logo-mark.svg" alt="Omarchy Lazyagent logo" width="130">
</p>

<h1 align="center">Omarchy Lazyagent</h1>

<p align="center">
  <em>Your coding agent rate limits, directly from the Omarchy bar.</em>
</p>

<p align="center">
  <a href="https://github.com/illegalstudio/omarchy-lazyagent/stargazers"><img src="https://img.shields.io/github/stars/illegalstudio/omarchy-lazyagent?style=flat-square&logo=github&logoColor=white&label=stars&color=7CE38B" alt="Stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/illegalstudio/omarchy-lazyagent?style=flat-square&color=7CE38B" alt="License: MIT"></a>
  <a href="https://omarchy.org"><img src="https://img.shields.io/badge/Omarchy-4.x-7CE38B?style=flat-square" alt="Omarchy 4.x"></a>
  <a href="https://x.com/nahime0"><img src="https://img.shields.io/badge/Follow-%40nahime0-7CE38B?style=flat-square&logo=x&logoColor=white" alt="Follow @nahime0 on X"></a>
</p>

<p align="center">
  <strong>Used vs expected &middot; Pace verdicts &middot; Reset countdowns &middot; Powered by lazyagent</strong>
</p>

<p align="center">
  A native Omarchy Shell widget that shows every rate-limit window <a href="https://github.com/illegalstudio/lazyagent">lazyagent</a> knows about: Claude Code, Codex, Grok, Kimi Code, and Cursor. Each window shows how much has been used, where a perfectly linear consumer would be, whether you are underutilizing, on track, or overutilizing, and when the window resets.
</p>

<p align="center">
  <a href="https://opensource.nahi.me"><strong>Official Website</strong></a>
</p>

---

## Install

This plugin is a front end: every number it shows comes from [lazyagent](https://github.com/illegalstudio/lazyagent), which **must be installed separately** before the panel can display anything. The plugin never downloads or installs it for you.

### 1. Install lazyagent

On Omarchy (and any other Arch-based system) the recommended way is the native Arch package published with every [lazyagent release](https://github.com/illegalstudio/lazyagent/releases/latest). The snippet below resolves the latest version, downloads the `Lazyagent_<version>_linux_amd64.pkg.tar.zst` asset, verifies it against the release checksums, and installs it with pacman:

```bash
version="$(curl -fsSL https://api.github.com/repos/illegalstudio/lazyagent/releases/latest | grep -Po '"tag_name":\s*"v\K[^"]+')"
base="https://github.com/illegalstudio/lazyagent/releases/download/v${version}"
curl -fLO "${base}/Lazyagent_${version}_linux_amd64.pkg.tar.zst"
curl -fLO "${base}/lazyagent_${version}_linux_checksums.txt"
sha256sum -c --ignore-missing "lazyagent_${version}_linux_checksums.txt"
sudo pacman -U "./Lazyagent_${version}_linux_amd64.pkg.tar.zst"
```

The package installs the `lazyagent` command in `/usr/bin` together with the desktop launcher, so the plugin finds it without any configuration. Updating means running the same snippet again: it always picks the newest release.

lazyagent will soon be available on the [AUR](https://aur.archlinux.org/) as well; once it is, `yay -S lazyagent` (or your AUR helper of choice) becomes the simplest path and keeps it updated with the rest of the system.

Other options, such as the portable `lazyagent-cli_<version>_linux_amd64.tar.gz` archive, the AppImage, or Homebrew on Linux, are documented in the [lazyagent install guide](https://github.com/illegalstudio/lazyagent#install). Any of them works as long as `lazyagent` ends up on your `PATH`, in `~/.local/bin`, or in a mise-managed install.

Verify the installation before adding the plugin:

```bash
lazyagent --version
lazyagent limits
```

### 2. Add the plugin

```bash
omarchy plugin add https://github.com/illegalstudio/omarchy-lazyagent.git --enable
```

The widget is placed in the right section of the bar by default. Move an existing instance with:

```bash
omarchy bar move illegalstudio.omarchy-lazyagent --section right
```

## Remove

```bash
omarchy plugin disable illegalstudio.omarchy-lazyagent
omarchy plugin remove illegalstudio.omarchy-lazyagent
```

Removing the plugin does not remove `lazyagent`. If you installed it with the Arch package and no longer need it, remove it with `sudo pacman -R lazyagent`.

## Using the widget

The bar icon is a small gauge. Its fill follows the most used window across every agent, so the tightest limit is readable at a glance. A dot appears when a window is nearly exhausted, when any window is overutilizing, or when an agent failed to report.

Click the icon to open the panel. Each metered pool gets a section, and each rate-limit window inside it gets a row:

- **Used** is the percentage of the window consumed, drawn as the meter fill.
- The **marker** on the meter is the expected percentage: the linear pace for the time elapsed in the window.
- The **pace pill** is lazyagent's verdict. Underutilizing means used is below 0.85 × expected, on track is within 0.85 to 1.15 ×, overutilizing is above 1.15 ×. The ratio and the expected percentage sit next to it.
- **Resets in** counts down live while the panel is open.

Windows limited to one model or feature get their own row and meter, named after their scope, for example Claude's **7-day window (Fable)**. When the provider says how the scoped meter relates to the plan-wide one ("11% of the weekly limit used, capped at 50%"), that line sits under the row.

Each section ends with a **More** button that shows what it hides, such as "4 resets · 1 credit pool". It opens:

- **Limit resets** the account holds (Claude reset grants such as the Fable launch resets, Codex banked resets): how many are left, whether one can be redeemed now, and live countdowns to when they expire or come back. The panel only reports them; redeeming a reset stays in the provider's own client.
- **Extra credits** beyond the included usage (Claude extra usage, Codex credits, Cursor on-demand spend, Grok prepaid balance), with a thin meter when the provider reports spend against a limit.
- The provenance line and disclaimer lazyagent attaches to the provider.

Open sections stay open across refreshes. Press `M` to open or close every section at once.

Agents that are installed but failed to answer are listed under **Issues**. Agents that are simply not installed or not logged in are mentioned in one dim line at the bottom.

Right-click the bar icon to refresh without opening the panel. Opening the panel refreshes only when the data is older than a minute.

## Refreshes, backoff, and stale data

lazyagent reads each provider through the undocumented endpoints their own CLIs use, and those endpoints rate-limit quickly. The plugin is careful with them:

- **Cached snapshots.** The bridge keeps the last snapshot in `~/.local/state/omarchy-lazyagent/limits.json` (or under `$XDG_STATE_HOME`). Automatic refreshes ask for data no older than a given age and are answered from that file when possible: the shell start accepts data as old as `refreshIntervalSec`, opening the panel accepts one minute, the periodic timer 30 seconds. Restarting the shell therefore does not call the providers again.
- **Backoff on rate limits.** When any agent answers with a rate limit (HTTP 429 or a "rate limited" message), the bridge records an exponential backoff of 2, 4, 8, 16 minutes and so on, capped at 30 minutes. While it runs, every automatic refresh is served from the cache, and the panel title reads "Rate limited · retry in N". The backoff is stored in the state file, so it also survives shell restarts. It clears as soon as a snapshot comes back without rate-limit errors.
- **Stale reports.** An agent that fails to report keeps showing its last good numbers, marked with a red **Stale · N ago** pill and slightly dimmed, for up to three days. The reset countdowns of a stale report count from the moment it was actually read. The **Issues** section explains what happened, when the next attempt is, and how old the data on screen is.
- **Manual refresh always runs.** `R`, the refresh button, the right-click on the icon, and the `refresh` IPC call force a new lazyagent run even during a backoff. Use them knowingly.

## lazyagent setup

Every number comes from `lazyagent limits --json`. See [Install](#install) for how to get lazyagent on Omarchy; the Arch package from the release page is the recommended route, and an AUR package is on its way.

The plugin discovers existing installations through `PATH`, `mise which lazyagent`, `~/.local/bin`, and the Homebrew on Linux prefix. It does not download, install, or update anything, on purpose: a bar widget should not fetch and run binaries on your behalf.

When `lazyagent` is missing, the bar icon is dimmed and the panel shows a notice with **Installation instructions** (opens the [Install](#install) section of this README) and **Check again** buttons. After installing it, click **Check again**, reopen the panel, or wait for the next scheduled refresh; no restart is needed.

lazyagent reads each provider's usage through the undocumented endpoints their own CLIs use. The plugin calls it only on the configured interval, on demand, and when the panel is opened with old data, and it backs off when a provider rate-limits (see [Refreshes, backoff, and stale data](#refreshes-backoff-and-stale-data)). See the [lazyagent disclaimer](https://github.com/illegalstudio/lazyagent#limits) before relying on the numbers.

## Requirements

- Omarchy 4 or newer with the current shell plugin system.
- A separately installed [lazyagent](https://github.com/illegalstudio/lazyagent#install) executable, version 0.15 or newer for the `limits --json` command, 0.16 or newer for scoped windows, resets, and credits (older versions simply show none). On Omarchy, use the Arch package from the release page (see [Install](#install)).
- Python 3 for the bridge script, included with Omarchy.
- Logged-in sessions for the agents you want to see. lazyagent explains where it reads each token from in `lazyagent limits --help`.

## Configuration

Widget settings are stored by Omarchy in `~/.config/omarchy/shell.json`.

| Setting | Default | Purpose |
| --- | ---: | --- |
| `agent` | `all` | Which agents to query: `all`, `claude`, `codex`, `grok`, `kimi`, or `cursor`. |
| `refreshIntervalSec` | `300` | Interval for background refreshes, between 60 and 3600 seconds. |

You can update a setting through Omarchy, for example:

```bash
omarchy bar set illegalstudio.omarchy-lazyagent refreshIntervalSec 600
omarchy bar set illegalstudio.omarchy-lazyagent agent claude
```

## Keyboard controls

When the panel has focus:

| Key | Action |
| --- | --- |
| `R`, `Enter`, `Space` | Refresh limits. |
| `M` | Open or close every **More** section. |
| `J`, `K`, arrows | Scroll the panel. |
| `Tab`, `Shift+Tab` | Switch to the neighbouring bar panel. |
| `Esc` | Close the panel. |

## IPC

```bash
omarchy-shell ipc call illegalstudio.omarchy-lazyagent toggle
omarchy-shell ipc call illegalstudio.omarchy-lazyagent refresh
omarchy-shell ipc call illegalstudio.omarchy-lazyagent status
omarchy-shell ipc call illegalstudio.omarchy-lazyagent more
```

## Development install

From an existing local checkout, expose the repository through the user plugin directory. Do not modify the packaged Omarchy files under `/usr/share/omarchy`.

```bash
ln -s "$PWD" "$HOME/.config/omarchy/plugins/illegalstudio.omarchy-lazyagent"
omarchy plugin enable illegalstudio.omarchy-lazyagent --section right
```

Validate the manifest and run the bridge and model tests with:

```bash
make check
```

Point the bridge at a specific executable with `OMARCHY_LAZYAGENT_BIN=/path/to/lazyagent`, which is also how the tests substitute a fake one.

## Safety

The bridge passes a fixed argument array to `lazyagent` and never invokes a shell. The only variable arguments, the agent filter and the maximum cache age, are checked against a closed list and a digit pattern in both QML and Python. lazyagent's output is capped at 512 KiB, parsed as JSON, and re-emitted with only known keys, coerced types, and bounded list sizes before it reaches Quickshell. The state file goes through the same sanitiser when it is read back, so a corrupt or edited file is simply ignored. A lazyagent run is given 60 seconds before it is abandoned.

The plugin is read-only: it never writes to any provider or to lazyagent's configuration.

## License

[MIT](LICENSE)
