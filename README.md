# GTA VI launch-day Twitch forecast — make.fun entry

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/avisii1680769-cell/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/avisii1680769-cell/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for [gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) on make.fun: forecast Twitch concurrent viewers for hours 2–24 of the GTA VI launch day, as five quantiles per hour.

## Model

Analog ensemble in log space. Each comparable launch-day curve is normalized by its own hour-1 viewers into log-ratios, weighted by similarity to the case (hour-1 scale, pre-launch history shape, platform coverage, unlock timing), then weighted quantiles per hour are exponentiated and anchored on the case's hour-1 print.

Practice log-pinball loss: **0.175** (starter: 0.387).

## Run

```sh
python3 -P -s main.py
```

Reads every `*.in` in `$MAKEFUN_INPUT_DIR` (default `/input`) and writes `<id>.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`). Python 3.13 standard library only; deterministic.
