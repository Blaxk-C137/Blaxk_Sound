#!/usr/bin/env bash
# Stands in for an audio backend. Records what it was asked to play.
printf '%s\n' "$*" >> "${RECORDER_LOG:?RECORDER_LOG must be set}"
