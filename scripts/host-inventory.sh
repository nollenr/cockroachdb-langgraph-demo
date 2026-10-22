#!/usr/bin/env bash

# Read-only AWS host inventory invoked through PuTTY/Plink.
set -u

echo '=== hostname ==='
hostname
hostnamectl

echo '=== operating system ==='
cat /etc/os-release
uname -m

echo '=== development tools ==='
python3 --version || true
python3.11 --version || true
command -v python3 || true
command -v python3.11 || true
pip3 --version || true
python3 -m pip --version || true
python3.11 -m pip --version || true
git --version || true
command -v cockroach || true
cockroach version || true

echo '=== filesystem ==='
df -h / /home/ec2-user

echo '=== synchronized repository candidates ==='
find /home/ec2-user -maxdepth 4 -type d -name product-returns -print 2>/dev/null

echo '=== ec2-user home directory ==='
ls -la /home/ec2-user

echo '=== existing langchain directory ==='
find /home/ec2-user/langchain -maxdepth 3 -print 2>/dev/null
