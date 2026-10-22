#!/usr/bin/env bash

# Read-only inspection of the likely WinSCP synchronization destination.
set -u

find /home/ec2-user/langchain -maxdepth 4 -print 2>/dev/null
