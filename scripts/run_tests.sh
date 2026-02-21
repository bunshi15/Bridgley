#!/bin/bash
# Run all tests
set -e

echo "Running unit tests..."
python -m pytest tests/ -v --tb=short

echo ""
echo "✅ All tests passed!"
