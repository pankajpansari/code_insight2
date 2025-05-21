#!/bin/bash

source config.env

for folder in "$SUBMISSIONS_DIR"/*; do
    if [ -d "$folder" ]; then
        if [ -f "$folder/shell/wish.c" ]; then
            echo "Processing: $folder/shell/wish.c"
            python3 run_tool.py "$folder/shell/wish.c"
        else
            echo "Skipping $folder: shell/wish.c not found"
        fi
    fi
done

echo "Processing complete!"