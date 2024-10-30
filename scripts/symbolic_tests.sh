#!/usr/bin/env bash
set -euo pipefail

# Default values
SOLVER="z3"
TIMEOUT=300
NUM_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
TARGET_DIR="examples"
SPECIFIC_CONTRACT=""
DEBUG=false


# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --solver)
            SOLVER="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --cores)
            NUM_CORES="$2"
            shift 2
            ;;
        --contract)
            SPECIFIC_CONTRACT="$2"
            shift 2
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Function to run hevm equivalence check
check_equivalence() {
    local contract=$1

    echo "Testing equivalence for $contract..."

    local cmd="hevm equivalence \
        --code-a \"$(vyper -f bytecode_runtime --no-optimize $contract)\" \
        --code-b \"$(vyper -f bytecode_runtime --experimental-codegen --no-optimize $contract)\" \
        --solver \"$SOLVER\" \
        --smttimeout \"$TIMEOUT\" \
        --num-solvers \"$NUM_CORES\""
    
    if [ "$DEBUG" = true ]; then
        time eval "$cmd"
    else
        eval "$cmd"
    fi
}

# Main testing function
test_contract() {
    local contract=$1

    echo "Processing $contract..."
    
    if ! check_equivalence "$contract"; then
        echo "❌ Equivalence check failed for $contract"
        return 1
    else
        echo "✅ Equivalence check passed for $contract"
    fi
}

# Track if any test failed
any_failed=0

# Main execution
if [ -n "$SPECIFIC_CONTRACT" ]; then
    if [ ! -f "$SPECIFIC_CONTRACT" ]; then
        echo "Contract file not found: $SPECIFIC_CONTRACT"
        exit 1
    fi
    test_contract "$SPECIFIC_CONTRACT" || any_failed=1
else
    # Find all Vyper contracts in examples directory
    find "$TARGET_DIR" -name "*.vy" -type f | while read -r contract; do
        test_contract "$contract" || any_failed=1
    done
fi

exit $any_failed
