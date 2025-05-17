#!/bin/bash

# Set the source and destination base directories
OUTPUT_DIR="output"
SUBMISSIONS_DIR="submission/all_submissions"

# Check if the source directory exists
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Error: Source directory '$OUTPUT_DIR' does not exist."
    exit 1
fi

# Check if the submissions directory exists
if [ ! -d "$SUBMISSIONS_DIR" ]; then
    echo "Error: Submissions directory '$SUBMISSIONS_DIR' does not exist."
    exit 1
fi

# Process each feedback file
for feedback_file in "$OUTPUT_DIR"/*_feedback_wish.c; do
    # Check if files exist
    if [ ! -f "$feedback_file" ]; then
        echo "No feedback files found in $OUTPUT_DIR."
        exit 1
    fi
    
    # Extract the GitHub username from the filename
    filename=$(basename "$feedback_file")
    github_username=$(echo "$filename" | cut -d'_' -f1)
    
    # Construct the destination path
    repo_dir="$SUBMISSIONS_DIR/shell-$github_username"
    dest_dir="$repo_dir/shell"
    
    echo "Processing $filename for user $github_username"
    
    # Check if the repository directory exists
    if [ ! -d "$repo_dir" ]; then
        echo "Warning: Repository directory '$repo_dir' does not exist. Skipping..."
        continue
    fi
    
    # Create the shell subdirectory if it doesn't exist
    if [ ! -d "$dest_dir" ]; then
        echo "Creating directory: $dest_dir"
        mkdir -p "$dest_dir"
    fi
    
    # Copy the feedback file to the destination
    echo "Copying $feedback_file to $dest_dir/"
    cp "$feedback_file" "$dest_dir/"
    
    # Verify the copy operation
    if [ $? -eq 0 ]; then
        echo "Successfully copied $filename to $dest_dir/"
    else
        echo "Error: Failed to copy $filename to $dest_dir/"
    fi
done

echo "Process completed."