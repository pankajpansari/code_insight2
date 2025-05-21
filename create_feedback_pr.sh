#!/bin/bash

source .env

# Check if the submissions directory exists
if [ ! -d "$SUBMISSIONS_DIR" ]; then
    echo "Error: Submissions directory '$SUBMISSIONS_DIR' does not exist."
    exit 1
fi

# Process each repository
for repo_dir in "$SUBMISSIONS_DIR"/shell-*; do
    # Check if it's a directory
    if [ ! -d "$repo_dir" ]; then
        continue
    fi
    
    # Extract the GitHub username from the repo directory name
    repo_name=$(basename "$repo_dir")
    github_username=${repo_name#shell-}
    
    echo "====================================="
    echo "Processing repository for user: $github_username"
    
    # Navigate to the repository
    cd "$repo_dir" || {
        echo "Error: Could not navigate to $repo_dir. Skipping..."
        continue
    }
    
    # Check if the shell directory and feedback file exist
    if [ ! -d "shell" ] || [ ! -f "shell/${github_username}_feedback_wish.c" ]; then
        echo "Warning: Shell directory or feedback file does not exist for $github_username. Skipping..."
        cd - > /dev/null
        continue
    fi
    
    # Make sure we're on main/master branch and pull latest changes
    DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')
    if [ -z "$DEFAULT_BRANCH" ]; then
        DEFAULT_BRANCH="main"  # Fallback to main if we can't determine default branch
        echo "Could not determine default branch, using 'main'"
    fi
    
    echo "Checking out default branch: $DEFAULT_BRANCH"
    git checkout "$DEFAULT_BRANCH"
    git pull origin "$DEFAULT_BRANCH"
    
    # Create and check out a new branch called 'feedback'
    echo "Creating new branch: feedback"
    git checkout -b feedback
    
    # Add the feedback file
    echo "Adding feedback file"
    git add shell/
    
    # Check if there are changes to commit
    if git diff --cached --quiet; then
        echo "No changes to commit for $github_username. Skipping..."
        git checkout "$DEFAULT_BRANCH"
        cd - > /dev/null
        continue
    fi
    
    # Commit the changes
    echo "Committing changes"
    git commit -m "feedback on your shell assignment"
    
    # Push the branch to the remote repository
    echo "Pushing to origin"
    git push origin feedback
   
    # Return to the original directory
    cd - > /dev/null
    
    echo "Completed processing for $github_username"
    echo "====================================="
done

echo "Process completed."