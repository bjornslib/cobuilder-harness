#!/bin/bash
# Commit Range Detection Utility
# Uses git reflog to detect commits since last push
#
# Epic 2: Commit Range Analysis (my-project-45t)
# AC-4: Correctly identify all commits since last push
# AC-5: Gracefully handle first push with fallback to last 10 commits
#
# Usage:
#   source .claude/utils/commit-range.sh
#   # Exports: COMMIT_RANGE, COMMIT_COUNT, COMMIT_LIST, LAST_PUSH_SHA
#
# Or run directly:
#   .claude/utils/commit-range.sh
#   # Outputs JSON with commit range info

set -euo pipefail

# ============================================
# CONFIGURATION
# ============================================

# Maximum commits to analyze on first push (when no push history exists)
MAX_FIRST_PUSH_COMMITS=10

# Fallback if reflog search fails
FALLBACK_COMMITS=10

# ============================================
# HELPER FUNCTIONS
# ============================================

# Get current branch name
get_current_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
}

# Get remote tracking branch
get_tracking_remote() {
    local branch="$1"
    git config --get "branch.${branch}.remote" 2>/dev/null || echo "origin"
}

# Find last push point using reflog
# Returns the commit SHA that was pushed last, or empty if none found
find_last_push_point() {
    local branch="$1"
    local remote="$2"

    # Method 1: Check reflog for push entries
    # git reflog shows entries like: "update by push"
    local push_sha
    push_sha=$(git reflog show --grep-reflog='update by push' -1 --format='%h' 2>/dev/null || echo "")

    if [ -n "$push_sha" ]; then
        echo "$push_sha"
        return 0
    fi

    # Method 2: Check remote tracking ref
    # This shows where the remote thinks the branch is
    local remote_ref="${remote}/${branch}"
    if git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
        # Get the SHA of the remote tracking branch
        local remote_sha
        remote_sha=$(git rev-parse --short "$remote_ref" 2>/dev/null || echo "")

        # Verify this SHA is an ancestor of HEAD (i.e., we haven't rebased)
        if [ -n "$remote_sha" ] && git merge-base --is-ancestor "$remote_sha" HEAD 2>/dev/null; then
            echo "$remote_sha"
            return 0
        fi
    fi

    # Method 3: Search reflog for any push-related entries
    # Look for patterns indicating a push happened
    local reflog_push
    reflog_push=$(git reflog --format='%h %gs' 2>/dev/null | grep -i 'push' | head -1 | awk '{print $1}' || echo "")

    if [ -n "$reflog_push" ]; then
        echo "$reflog_push"
        return 0
    fi

    # No push point found
    return 1
}

# Get commit range from last push to HEAD
get_commit_range() {
    local last_push_sha="$1"

    if [ -n "$last_push_sha" ]; then
        # Get all commits from last push (exclusive) to HEAD (inclusive)
        echo "${last_push_sha}..HEAD"
    else
        # First push scenario: use last N commits
        echo "HEAD~${MAX_FIRST_PUSH_COMMITS}..HEAD"
    fi
}

# Count commits in range
count_commits() {
    local range="$1"

    # Handle commit range counting
    local count
    count=$(git rev-list --count "$range" 2>/dev/null)
    local exit_code=$?

    # If command succeeded, return the count (even if 0)
    if [ $exit_code -eq 0 ] && [ -n "$count" ]; then
        echo "$count"
        return 0
    fi

    # Command failed - likely invalid range (first push case)
    # Fall back to counting last N commits
    local total_commits
    total_commits=$(git rev-list --count HEAD 2>/dev/null || echo "0")

    if [ "$total_commits" -lt "$MAX_FIRST_PUSH_COMMITS" ]; then
        echo "$total_commits"
    else
        echo "$MAX_FIRST_PUSH_COMMITS"
    fi
}

# Get list of commit SHAs in range
list_commits() {
    local range="$1"

    # Get commits in reverse chronological order (newest first)
    git rev-list --reverse "$range" 2>/dev/null || {
        # Fallback for first push
        git rev-list --reverse -n "$MAX_FIRST_PUSH_COMMITS" HEAD 2>/dev/null || echo ""
    }
}

# Detect force push scenario
detect_force_push() {
    local branch="$1"
    local remote="$2"

    local remote_ref="${remote}/${branch}"

    # If remote ref exists and is not an ancestor of HEAD, this might be after a force push
    if git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
        if ! git merge-base --is-ancestor "$remote_ref" HEAD 2>/dev/null; then
            echo "true"
            return 0
        fi
    fi

    echo "false"
}

# ============================================
# MAIN LOGIC
# ============================================

main() {
    # Ensure we're in a git repository
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        echo '{"error": "Not a git repository", "success": false}' >&2
        return 1
    fi

    # Get current branch and remote
    local branch
    branch=$(get_current_branch)

    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        # Detached HEAD state
        echo '{"error": "Detached HEAD state - cannot determine branch", "success": false}' >&2
        return 1
    fi

    local remote
    remote=$(get_tracking_remote "$branch")

    # Find last push point
    local last_push_sha=""
    local is_first_push="false"

    if last_push_sha=$(find_last_push_point "$branch" "$remote"); then
        is_first_push="false"
    else
        is_first_push="true"
        last_push_sha=""
    fi

    # Detect force push
    local is_force_push
    is_force_push=$(detect_force_push "$branch" "$remote")

    # Get commit range
    local commit_range
    if [ "$is_first_push" = "true" ]; then
        # First push: limit to last N commits or all if less
        local total_commits
        total_commits=$(git rev-list --count HEAD 2>/dev/null || echo "0")

        if [ "$total_commits" -le "$MAX_FIRST_PUSH_COMMITS" ]; then
            # Few commits - analyze all from root
            local first_commit
            first_commit=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1 || echo "")
            if [ -n "$first_commit" ]; then
                commit_range="${first_commit}^..HEAD"
            else
                commit_range="HEAD~${total_commits}..HEAD"
            fi
        else
            commit_range="HEAD~${MAX_FIRST_PUSH_COMMITS}..HEAD"
        fi
    else
        commit_range="${last_push_sha}..HEAD"
    fi

    # Count commits
    local commit_count
    commit_count=$(count_commits "$commit_range")

    # Get commit list
    local commit_list
    commit_list=$(list_commits "$commit_range" | tr '\n' ' ' | sed 's/ $//')

    # Export variables for sourcing
    export COMMIT_RANGE="$commit_range"
    export COMMIT_COUNT="$commit_count"
    export COMMIT_LIST="$commit_list"
    export LAST_PUSH_SHA="$last_push_sha"
    export IS_FIRST_PUSH="$is_first_push"
    export IS_FORCE_PUSH="$is_force_push"
    export CURRENT_BRANCH="$branch"

}

# Function to output JSON (for direct execution)
output_json() {
    cat << EOF
{
    "success": true,
    "branch": "$CURRENT_BRANCH",
    "remote": "$(get_tracking_remote "$CURRENT_BRANCH")",
    "commit_range": "$COMMIT_RANGE",
    "commit_count": $COMMIT_COUNT,
    "commit_list": "$(echo "$COMMIT_LIST" | sed 's/"/\\"/g')",
    "last_push_sha": "$LAST_PUSH_SHA",
    "is_first_push": $IS_FIRST_PUSH,
    "is_force_push": $IS_FORCE_PUSH
}
EOF
}

# Determine if script is being sourced or executed directly
_commit_range_sourced=false
if [ -n "${BASH_SOURCE:-}" ]; then
    if [ "${BASH_SOURCE[0]:-$0}" != "${0}" ]; then
        _commit_range_sourced=true
    fi
elif [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
    case "$ZSH_EVAL_CONTEXT" in
        *:file*) _commit_range_sourced=true ;;
    esac
fi

# Run main and optionally output JSON
if [ "$_commit_range_sourced" = "true" ]; then
    # Sourced - just run main to set exports, no JSON output
    main "$@"
else
    # Executed directly - run main and output JSON
    main "$@"
    output_json
fi
