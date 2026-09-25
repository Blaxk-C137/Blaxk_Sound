#!/usr/bin/env bash
# Stands in for a long sound, so takeover behaviour can be observed.
printf '%s\n' "$$" >> "${RECORDER_LOG:?RECORDER_LOG must be set}"
sleep "${SLEEPER_SECONDS:-30}"
