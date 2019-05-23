#!/usr/bin/env bash

output=$(coveralls 2>&1)

if [[ $? -eq 0 ]]; then
  printf '%s\n' "$output"
else
  printf 'Skipping coverage upload.\n'
fi
